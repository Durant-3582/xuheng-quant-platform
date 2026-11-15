"""Streamlit entrypoint: execute the versioned source included in this code-only repository."""
import hashlib,os,sys,tempfile,runpy
from pathlib import Path
from zipfile import ZipFile
src=Path(__file__).resolve().parent/'source.zip'
sha='17b05c97542aa38b79cad9f22da3002a63204354e26348d94b1fac09384d264f'
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
if str(base) not in sys.path:
    sys.path.insert(0,str(base))
_ = runpy.run_path(str(base/'streamlit_app.py'),run_name='__main__')
