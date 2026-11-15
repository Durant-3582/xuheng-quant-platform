"""Streamlit entrypoint: execute the versioned source included in this code-only repository."""
import hashlib,os,sys,tempfile,runpy
from pathlib import Path
from zipfile import ZipFile
src=Path(__file__).resolve().parent/'source.zip'
sha='fe665fbf0c00dca261200d966bea0dfc3ce0195be8e7d0470cc3968b3059e240'
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
os.environ.setdefault('XUHENG_ACCESS_SHA256','4ff19e42bedd791c81bed54acdfe8cb333fa81563cfe53c190735060902bcf08')
os.environ.setdefault('XUHENG_PREVIEW_FROM_TUSHARE','1')
os.environ.setdefault('XUHENG_HOSTED_SAMPLE_DIR',str(Path(tempfile.gettempdir())/'xuheng-private-course-20261113-v1'))
if str(base) not in sys.path:
    sys.path.insert(0,str(base))
_ = runpy.run_path(str(base/'streamlit_app.py'),run_name='__main__')
