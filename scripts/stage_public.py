"""Prepare a source-only checkout for Streamlit Community Cloud."""
import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    ".gitignore", ".streamlit/config.toml", "README.md", "requirements.txt",
    "streamlit_app.py", "static/site-id.txt", "static/full-release.json",
    "xuheng/browser_settings/index.html", "checks/check_browser_settings.mjs",
    "ops/publish_after_close.py", "ops/cloud_history.py", "ops/upload_private.py", "ops/盘后发布.md",
    ".github/workflows/after-close.yml",
    "盘后更新行情.command",
)


def stage(out):
    if out.exists() and any(out.iterdir()):
        raise ValueError("请选择一个空的发布目录。")
    files = [ROOT / name for name in PUBLIC_FILES]
    for folder in ("xuheng", "ingest", "checks", "scripts"):
        files.extend(sorted((ROOT / folder).glob("*.py")))

    secrets = []
    for name in ("TUSHARE_TOKEN", "XUHENG_ARCHIVE_WRITE_KEY", "XUHENG_ARCHIVE_TOKEN"):
        if os.environ.get(name):
            secrets.append(os.environ[name].strip().encode())
    for name in (".private/tushare-token", ".streamlit/.local-course-pass"):
        path = ROOT / name
        if path.is_file():
            secrets.append(path.read_bytes().strip())

    # Validate the whole source list before writing any publishable files.
    sources = {}
    for path in files:
        if path.is_symlink() or path.resolve() != path:
            raise ValueError(f"发布目录不能包含符号链接：{path.relative_to(ROOT)}")
        data = path.read_bytes()
        data.decode("utf-8")
        if any(secret and secret in data for secret in secrets):
            raise ValueError(f"源码中包含已配置的凭据：{path.relative_to(ROOT)}")
        sources[path.relative_to(ROOT)] = data

    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in sources.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if os.access(ROOT / name, os.X_OK):
            target.chmod(0o755)
    # Only the hosted checkout defaults to public access and the cloud archive.
    (out / "static/public-course.txt").write_text("streamlit-community-cloud\n", encoding="utf-8")
    print(f"发布目录已就绪，共 {len(sources) + 1} 个文件，入口为 streamlit_app.py。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    stage(parser.parse_args().out)
