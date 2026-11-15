"""Provision a local course access link without an upstream data token."""
import hashlib
import os
from pathlib import Path
import secrets

root=Path(__file__).resolve().parents[1]
p=root/".streamlit"/"secrets.toml"
saved=root/".streamlit"/".local-course-pass"
if p.exists() or saved.exists(): raise SystemExit("已有课程口令配置，未覆盖。")
p.parent.mkdir(exist_ok=True);saved.parent.mkdir(exist_ok=True,mode=0o700)
value=secrets.token_urlsafe(32)
def write_private(path,body):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_EXCL|os.O_CREAT,0o600),"w") as f: f.write(body)
write_private(saved,value+"\n")
write_private(p,'XUHENG_ACCESS_SHA256 = "'+hashlib.sha256(value.encode()).hexdigest()+'"\n')
print("已为本机配置课程访问。")
