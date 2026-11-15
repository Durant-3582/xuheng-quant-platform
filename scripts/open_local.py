"""Start only this local Streamlit app, and only disclose the course link to its verified loopback port."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler
from urllib.parse import urlencode
import webbrowser

root=Path(__file__).resolve().parents[1]
full=root/'.private/database'
sample=root/'.private/walkthrough/database'
if not (full/'manifest.json').is_file() and not (sample/'manifest.json').is_file():
    raise SystemExit('本机还没有建好的行情库。')
passfile=root/'.streamlit/.local-course-pass'
if not passfile.exists():raise SystemExit('请先运行 scripts/create_access.py 创建课程访问口令。')
opener=build_opener(ProxyHandler({})); marker=(root/'static/site-id.txt').read_bytes()
def own(port):
    try:
        with opener.open(f'http://127.0.0.1:{port}/app/static/site-id.txt',timeout=.4) as response:
            return response.status==200 and response.read(len(marker)+1)==marker
    except OSError:return False
def free(port):
    try:
        with socket.socket() as sock:sock.bind(('127.0.0.1',port))
        return True
    except OSError:return False
def main():
    ps=range(8516,8530);running=next((p for p in ps if own(p)),None)
    port=running or next((p for p in ps if free(p)),None)
    if not port:raise SystemExit('本机预览端口均已占用。')
    child=None
    if not running:
        env=os.environ.copy();env.pop('XUHENG_DATA_DIR',None)
        child=subprocess.Popen([sys.executable,'-m','streamlit','run','streamlit_app.py','--server.address','127.0.0.1',
           '--server.port',str(port),'--server.headless','true'],cwd=root,env=env)
        for _ in range(120):
            if child.poll() is not None:raise SystemExit('本地工作台未能启动。')
            if own(port):break
            time.sleep(.25)
        else:
            child.terminate();raise SystemExit('本机入口启动超时。')
    if '--no-browser' not in sys.argv:
        code=passfile.read_text().strip()
        webbrowser.open(f'http://127.0.0.1:{port}/?'+urlencode({'course':code,'page':'portfolio'}))
        print('已在默认浏览器中打开本机工作台。')
    else:print(f'独立版已在本机 127.0.0.1:{port} 提供服务。',flush=True)
    if child:
        try:child.wait()
        except KeyboardInterrupt:child.terminate()
if __name__=='__main__':main()
