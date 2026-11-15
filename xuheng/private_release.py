"""Read an immutable release in an explicitly private GitHub repository."""
import re
import requests
from .archive import ArchiveError


class PrivateRelease:
    def __init__(self,repo,tag,token):
        if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}",tag):
            raise ArchiveError("请配置私有行情仓库、发布标签和只读访问凭据。")
        self.url="https://api.github.com/repos/"+repo
        self.token=token
        if self.meta("").get("private") is not True:
            raise ArchiveError("行情归档必须来自私有仓库。")
        release=self.meta("/releases/tags/"+tag)
        self.files={}
        for page in range(1,21):
            entries=self.meta(f"/releases/{int(release['id'])}/assets",{"per_page":100,"page":page})
            for item in entries:
                if item["name"]=="manifest.json" or re.fullmatch(r"[a-z0-9-]+\.sqlite",item["name"]):
                    self.files[item["name"]]=int(item["id"])
            if len(entries)<100:break
        if "manifest.json" not in self.files:raise ArchiveError("私有发布版本中未找到行情目录。")

    def request(self,path,accept,params=None):
        headers={"Authorization":"Bearer "+self.token,"Accept":accept}
        r=requests.get(self.url+path,headers=headers,params=params,stream=True,timeout=(8,90))
        try:r.raise_for_status()
        except Exception:r.close();raise
        return r

    def meta(self,path,params=None):
        with self.request(path,"application/vnd.github+json",params) as r:return r.json()

    def get(self,name):
        if name not in self.files:raise ArchiveError("该私有发布缺少所需行情文件。")
        return self.request("/releases/assets/"+str(self.files[name]),"application/octet-stream")
