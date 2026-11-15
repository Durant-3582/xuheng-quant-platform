"""Stage an allowlisted development release for the private course repository."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FILES = ('__init__ archive private_release frames portfolio comparison details research '
         'ui_common ui_research ui_portfolio').split()


def main(out):
    if out.exists() and list(out.iterdir()):
        raise ValueError('请选择一个空的输出目录。')
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    data=ROOT/'.private/walkthrough/database'
    manifest=json.loads((data/'manifest.json').read_bytes())
    if manifest.get('sample') is not True or manifest['securities'] != 18:
        raise ValueError('此打包命令只处理标明范围的 18 个验收标的。')
    bundle=out/'independent.zip'
    with ZipFile(bundle,'w',ZIP_DEFLATED,compresslevel=1) as archive:
        archive.write(ROOT/'streamlit_app.py','streamlit_app.py')
        for module in FILES:
            name='xuheng/'+module+'.py'; archive.write(ROOT/name,name)
        archive.write(data/'manifest.json','database/manifest.json')
        for part in manifest['files'].values():
            path=data/part['file']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=part['sha256']:
                raise ValueError('行情文件校验失败。')
            archive.write(path,'database/'+path.name)
    version=hashlib.sha256(bundle.read_bytes()).hexdigest()
    digest=hashlib.sha256((ROOT/'.streamlit/.local-course-pass').read_text().strip().encode()).hexdigest()
    launcher='''"""Start the self-contained research preview with its verified, private sample database."""
from pathlib import Path
import hashlib
import os
import runpy
import sys
import tempfile
from zipfile import ZipFile

package = Path(__file__).resolve().parent / 'independent.zip'
version = 'BUNDLE_HASH'
root = Path(tempfile.gettempdir()) / ('xuheng-independent-' + version)
if not root.is_dir():
    if hashlib.sha256(package.read_bytes()).hexdigest() != version:
        raise RuntimeError('独立版文件未通过校验。')
    with tempfile.TemporaryDirectory(dir=root.parent) as work:
        stage = Path(work) / 'app'
        stage.mkdir(mode=0o700)
        with ZipFile(package) as bundle:
            for name in bundle.namelist():
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise ValueError('应用包文件名无效。')
            bundle.extractall(stage)
        try:
            stage.rename(root)
        except OSError:
            if not root.is_dir():raise
os.environ.setdefault('XUHENG_DATA_DIR', str(root/'database'))
os.environ.setdefault('XUHENG_ACCESS_SHA256', 'ACCESS_DIGEST')
if str(root) not in sys.path:sys.path.insert(0,str(root))
runpy.run_path(str(root/'streamlit_app.py'),run_name='__main__')
'''
    (out/'streamlit_app.py').write_text(launcher.replace('BUNDLE_HASH',version).replace('ACCESS_DIGEST',digest))
    shutil.copyfile(ROOT/'requirements.txt',out/'requirements.txt')
    print(f'私有验收发布：{len(manifest["files"])} 个已校验分片；3 个部署文件。')


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);main(ap.parse_args().directory)
