"""Streamlit entrypoint: execute the versioned source included in this code-only repository."""
import hashlib,importlib,os,sys,tempfile,threading,runpy
from pathlib import Path
from zipfile import ZipFile
src=Path(__file__).resolve().parent/'source.zip'
sha='d294ca16242a87285d730974fc3c5f2833bcde651058f71ee3ebbdd1c9767bb0'
base=Path(tempfile.gettempdir())/('xuheng-source-'+sha)
if not base.is_dir():
    if hashlib.sha256(src.read_bytes()).hexdigest()!=sha:raise RuntimeError('代码包校验失败')
    with tempfile.TemporaryDirectory(dir=base.parent) as tmp:
        stage=Path(tmp)/'source';stage.mkdir(mode=0o700)
        with ZipFile(src) as z:
            if any(Path(n).is_absolute() or '..' in Path(n).parts for n in z.namelist()):raise ValueError('无效的项目路径')
            z.extractall(stage)
        try:stage.rename(base)
        except OSError:
            if not base.is_dir():raise
os.environ.setdefault('XUHENG_PUBLIC_COURSE','1')
os.environ.setdefault('XUHENG_CLOUD_ARCHIVE','1')
# Community Cloud can reload the script without restarting its Python interpreter.
# A previously imported package would otherwise keep resolving modules in the old bundle.
with sys.__dict__.setdefault('_xuheng_source_lock',threading.RLock()):
    old=sys.modules.get('xuheng')
    if old is not None and Path(getattr(old,'__file__','') or '.').resolve().parent!=base/'xuheng':
        for name in tuple(sys.modules):
            if name=='xuheng' or name.startswith('xuheng.'):
                sys.modules.pop(name,None)
        importlib.invalidate_caches()
    if not sys.path or sys.path[0]!=str(base):
        sys.path[:]=[str(base),*(part for part in sys.path if part!=str(base))]
_ = runpy.run_path(str(base/'streamlit_app.py'),run_name='__main__')
