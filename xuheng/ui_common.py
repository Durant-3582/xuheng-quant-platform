from datetime import date, datetime
import hashlib
import hmac
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .archive import Archive, ArchiveError

ROOT=Path(__file__).resolve().parents[1]
CLOUD_DEFAULT = "1" if (ROOT / "static" / "public-course.txt").is_file() else ""
NAV={"overview":"市场总览","indices":"指数中心","stocks":"个股研究","factors":"因子选股","strategies":"策略回测","portfolio":"组合表现"}
COLORS=["#176552","#a66335","#465d96","#81639a","#646b6d"]
STATUS={"ready":"已有日线","empty":"未返回日线","denied":"权限受限"}


def conf(key, default=""):
    if key in os.environ:
        return os.environ[key]
    if st.secrets.load_if_toml_exists():
        return st.secrets.get(key, default)
    return default


def access():
    if conf('XUHENG_PUBLIC_COURSE', CLOUD_DEFAULT)=='1':
        return
    digest=conf("XUHENG_ACCESS_SHA256")
    if not digest or len(digest)!=64:
        st.warning("课程访问口令尚未配置，请联系平台维护者。")
        st.stop()
    if hmac.compare_digest(st.session_state.get("access_grant",""),digest):
        return
    def valid(value):
        return isinstance(value,str) and len(value)<=300 and hmac.compare_digest(hashlib.sha256(value.encode()).hexdigest(),digest)
    if valid(st.query_params.get("course","")):
        st.session_state["access_grant"]=digest
        return
    st.title("序衡 · A 股投研")
    st.write("课程研究工作台。打开课程专用链接，或输入课程口令后查看。")
    with st.form("access"):
        value=st.text_input("课程访问口令",type="password",max_chars=300)
        submit=st.form_submit_button("进入工作台",type="primary")
    if submit and valid(value):
        st.session_state["access_grant"]=digest
        st.rerun()
    if submit: st.error("口令不正确，请检查是否使用了最新的课程链接。")
    st.stop()


@st.cache_resource(max_entries=2, show_spinner=False)
def open_database(directory, base, token, repo, tag, version):
    return Archive(directory, base, token, repo, tag)


@st.cache_resource(max_entries=2, show_spinner=False)
def open_full_release(directory,origin,index_hash,reader):
    from .packed_archive import PackedArchive
    result=PackedArchive(directory,origin,index_hash,reader)
    # The first confirmed release is visible immediately after its three home objects are ready.
    result.prefetch(['snapshot','coverage','series/000300.SH'])
    return result

@st.cache_data(ttl=300,max_entries=4,show_spinner=False)
def active_full_release(default,reader,directory):
    from .packed_archive import current_release
    return current_release(default,reader,directory)


def connection():
    if conf('XUHENG_CLOUD_ARCHIVE', CLOUD_DEFAULT)=='1':
        import json,tempfile
        release=json.loads((ROOT/'static/full-release.json').read_text())
        provider=provider_token()
        if not provider:raise ArchiveError('正式行情服务尚未配置 Tushare 数据源。')
        # Only a domain-separated, read-only capability ever leaves the app for archive reads.
        from .packed_archive import market_reader
        reader=market_reader(provider)
        directory=str(Path(tempfile.gettempdir())/'xuheng-prices-v1')
        live=active_full_release(release,reader,directory)
        archive=open_full_release(directory,release['origin'],live['index'],reader)
        if archive.day!=live['day'] or (live.get('bars') and archive.manifest['bars']!=live['bars']):raise ArchiveError('正式库日期或数量与发布记录不一致。')
        return archive
    local_full=ROOT/'.private/database';local_sample=ROOT/'.private/walkthrough/database'
    default=(local_full if (local_full/'manifest.json').is_file() or conf('XUHENG_GITHUB_REPO') or conf('XUHENG_ARCHIVE_BASE')
             or not (local_sample/'manifest.json').is_file() else local_sample)
    directory = Path(conf("XUHENG_DATA_DIR", str(default)))
    if (not (directory/'manifest.json').is_file() and not conf('XUHENG_GITHUB_REPO') and not conf('XUHENG_ARCHIVE_BASE')
            and conf('XUHENG_PREVIEW_FROM_TUSHARE')=='1'):
        from .bootstrap import hosted_sample
        init=hosted_sample(conf('XUHENG_HOSTED_SAMPLE_DIR',str(ROOT/'.private/hosted-sample')),provider_token())
        if init is not None:directory=init
    manifest = directory / "manifest.json"
    version = manifest.stat().st_mtime_ns if manifest.is_file() else 0
    return open_database(str(directory), conf("XUHENG_ARCHIVE_BASE"), conf("XUHENG_ARCHIVE_TOKEN"),
                         conf("XUHENG_GITHUB_REPO"), conf("XUHENG_GITHUB_TAG"), version)


def provider_token():
    value = conf("TUSHARE_TOKEN")
    file = ROOT / ".private" / "tushare-token"
    return value or (file.read_text().strip() if file.is_file() else "")


def day(v):
    return datetime.strptime(v,"%Y%m%d").date()


def iso(v):
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if v else "—"


def ds(v):
    return v.strftime("%Y%m%d")


def pct(v,n=2):
    return "—" if v is None or pd.isna(v) else f"{v:+,.{n}f}%"


def fmt(v,n=2):
    return "—" if v is None or pd.isna(v) else f"{v:,.{n}f}"


def dates(label,default,cutoff,key,disabled=False):
    return ds(st.date_input(label,day(default),min_value=date(2000,1,1),max_value=day(cutoff),format="YYYY-MM-DD",key=key,disabled=disabled))


def option(label, items, key, default=None, disabled=False):
    keys=list(items)
    return st.selectbox(label,keys,index=keys.index(default) if default in keys else 0,
        format_func=lambda k:items[k],key=key,disabled=disabled)


def curve(lines,title,yleft="",baseline=None):
    fig=go.Figure()
    for i,(label,rows) in enumerate(lines):
        if not rows: continue
        fig.add_trace(go.Scatter(x=[iso(d) for d,v in rows],y=[v for d,v in rows],name=label,
                mode="lines" if len(rows)>1 else "markers", connectgaps=False,
                line={"width":2.0,"color":COLORS[i%len(COLORS)]},hovertemplate="%{y:,.3f}<extra>%{fullData.name}</extra>"))
    if baseline is not None:
        fig.add_hline(y=baseline,line_width=1,line_dash="dot",line_color="#899a8b")
    fig.update_layout(height=325,margin=dict(l=56,r=18,t=14,b=44),hovermode="x unified",
                      paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=len(fig.data)>1, legend=dict(orientation="h",y=1.02,yanchor="bottom",x=0),
                      xaxis=dict(type="date",title=None,automargin=True,nticks=5,hoverformat="%Y-%m-%d",
                                 tickformatstops=[dict(dtickrange=[None,86400000*28],value="%m-%d\n%Y"),
                                                  dict(dtickrange=[86400000*28,"M12"],value="%Y-%m"),
                                                  dict(dtickrange=["M12",None],value="%Y")]),
                      yaxis=dict(title=None,automargin=True,gridcolor="#e3e9e1",zeroline=False))
    st.markdown("**"+title+"**"+("　·　"+yleft if yleft else ""))
    st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False,"scrollZoom":False},theme=None)


def table(records):
    if len(records):
        st.dataframe(pd.DataFrame(records),use_container_width=True,hide_index=True)
    else:
        st.caption("没有符合条件的记录。")


def rangebars(bars,key):
    windows = [60,126,252] if key == 'cfg_overview' else [20,60,252]
    modes={**{str(n):f"近 {n} 个交易日" for n in windows},"all":"全部历史","custom":"自定义交易日数"}
    parts=st.columns([2,1])
    with parts[0]: mode=option("显示区间",modes,key+"-range","252")
    n=len(bars) if mode=="all" else int(mode) if mode.isdigit() else None
    if n is None:
        with parts[1]: n=int(st.number_input("最近多少个交易日",min_value=1,max_value=10000,value=120,key=key+"-days"))
    return bars[-n:] if bars and n else []


def label(store,c):
    return f"{store.catalog[c][1]}　{c}"


def symbol_choices(store,c):
    if not hasattr(store,'_search_aliases'):
        aliases={}
        for old,new in store.snapshot.get('aliases',{}).items():
            if new in store.catalog and new!=old:aliases.setdefault(new,[]).append(old)
        store._search_aliases=aliases
    previous=store._search_aliases.get(c,[])
    return label(store,c)+('（曾用代码 '+', '.join(previous)+'）' if previous else '')
