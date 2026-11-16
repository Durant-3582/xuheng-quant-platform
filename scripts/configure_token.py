"""Keep the provider credential on the machine that runs the data update."""
import getpass
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    folder = Path(__file__).resolve().parents[1] / '.private'
    folder.mkdir(mode=0o700, exist_ok=True)
    if sys.platform == 'darwin':
        script = ('text returned of (display dialog "粘贴 Tushare Token。仅供独立版后台向 Tushare 请求数据。" '
                  'default answer "" with hidden answer with title "Rocket · 配置 Tushare" '
                  'buttons {"取消", "保存"} default button "保存" cancel button "取消")')
        response = subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, text=True)
        if response.returncode:
            return 1
        token = response.stdout.strip()
    else:
        token = getpass.getpass('Tushare Token（隐藏输入）：').strip()
    if not token.isascii() or not token.isalnum() or not 16 <= len(token) <= 160:
        print('输入格式无效，请复制个人中心里的完整 Token。')
        return 1
    with tempfile.NamedTemporaryFile(mode='w', dir=folder, delete=False) as handle:
        handle.write(token + '\n')
    os.chmod(handle.name, 0o600)
    os.replace(handle.name, folder / 'tushare-token')
    print('已保存到本机独立项目，后台可开始连接 Tushare。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
