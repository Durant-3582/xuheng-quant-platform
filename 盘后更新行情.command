#!/bin/zsh
set -eu
cd "${0:A:h}"
for interpreter in "$HOME/anaconda3/bin/python3" "$HOME/miniconda3/bin/python3" python3; do
    if "$interpreter" -c 'import numpy,pandas,requests' >/dev/null 2>&1; then
        exec "$interpreter" ops/publish_after_close.py
    fi
done
echo '未找到可运行更新的 Python。请按项目 README 安装依赖。'
exit 1
