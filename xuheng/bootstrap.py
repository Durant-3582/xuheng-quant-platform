"""Build a small, unmistakably labelled hosted QA archive once per machine, behind the course gate."""
import fcntl
import os
from pathlib import Path
import sys
import threading

import streamlit as st


@st.cache_resource(show_spinner=False)
def _task(directory,token):
    state={'running':True,'error':False}
    def worker():
        d=Path(directory);d.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            with (d/'seed.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                if not (d/'database/manifest.json').is_file():
                    p=str(Path(__file__).resolve().parents[1]/'ingest')
                    if p not in sys.path:sys.path.insert(0,p)
                    from walkthrough import from_tushare
                    from_tushare(d,token)
        except Exception as exc:
            state['error']=type(exc).__name__
        finally:state['running']=False
    threading.Thread(target=worker,daemon=True,name='sample-import').start()
    return state


def hosted_sample(directory,token):
    path=Path(directory)
    if (path/'database/manifest.json').is_file():return path/'database'
    if not token:return None
    status=_task(str(path),token)
    if status['error']:
        st.warning('未能从 Tushare 完成验收样本初始化，本次未发布不完整数据。')
        if st.button('重新连接数据源'):
            _task.clear();st.rerun()
    else:
        @st.fragment(run_every=4)
        def waiting():
            # The worker publishes the manifest last; never open a partial archive.
            if (path/'database/manifest.json').is_file() or status['error']:
                st.rerun(scope='app')
            st.info('正在从 Tushare 初始化行情。完成后会自动打开市场页面。')
            if st.button('立即检查'):
                st.rerun(scope='app')
        waiting()
    st.stop()
