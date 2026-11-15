"""Read only the requested, verified gzip records of a private, immutable release."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import hmac
from pathlib import Path
from urllib.parse import urlsplit
import gzip,json,os,re,tempfile,threading,time
import requests
from .archive import Archive,ArchiveError

HASH=re.compile(r'[0-9a-f]{64}')
MAX_PACK=16*1024**2
ORIGIN='https://xuheng-course-archive-3582.alivetomato8.chatgpt.site'

def market_reader(provider):
    return hmac.digest(provider.strip().encode(), b'xuheng/market-read/v1/appgprj_6af9102ba4608191addb0f2e49174e36', 'sha256').hex()

def current_release(default,reader,directory):
    origin=default['origin'].rstrip('/')
    if origin!=ORIGIN:raise ArchiveError('无法识别正式行情服务。')
    path=Path(directory)/'last-release.json';previous=dict(default)
    def valid(r):return isinstance(r,dict) and HASH.fullmatch(str(r.get('index',''))) and re.fullmatch(r'20\d{6}',str(r.get('day',''))) and r['day']>=default['day']
    try:
        old=json.loads(path.read_bytes())
        if valid(old):previous=old
    except (ValueError,OSError):pass
    try:
        with requests.get(origin+'/v1/current',headers={'X-Archive-Read':reader},timeout=(3,6),allow_redirects=False) as r:
            if r.status_code==404:return previous
            if r.status_code in (301,302,303,307,308,401,403):raise ArchiveError('正式行情凭据未通过服务端认证。')
            r.raise_for_status();next_release=r.json()
        if not valid(next_release) or type(next_release.get('bars')) is not int or next_release['bars']<1:raise ArchiveError('线上行情版本指针不完整。')
        if next_release['day']<previous['day']:return previous
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as tmp:
            tmp.write(json.dumps(next_release).encode());name=tmp.name
        os.replace(name,path);return next_release
    except requests.RequestException:return previous

class PackedArchive(Archive):
    def __init__(self,directory,origin,index_hash,service):
        u=urlsplit(origin)
        if u.scheme!='https' or u.hostname!='xuheng-course-archive-3582.alivetomato8.chatgpt.site' or u.netloc!=u.hostname or u.path not in ('','/') or u.query or u.fragment or not HASH.fullmatch(index_hash):
            raise ArchiveError('私有行情存储配置无效。')
        if not service:raise ArchiveError('正式行情库的服务端读取凭据尚未配置。')
        self.base=origin.rstrip('/');self.service=service;self.release_id=index_hash;self.remote=True
        self.root=Path(directory)/index_hash;self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        self._threads=threading.local();self._locks=[threading.RLock() for _ in range(53)]
        self._pool=ThreadPoolExecutor(max_workers=6,thread_name_prefix='market-read')
        self._check_lock=threading.RLock();self._seen=set()
        try:
            descriptor=self._cached(index_hash)
            if descriptor is None:
                descriptor=self._download(index_hash);self._save(index_hash,descriptor)
            obj=json.loads(gzip.decompress(descriptor))
            self.manifest=obj['manifest'];self.day=self.manifest['day'];self.items=obj['items'];self.sizes=obj['sizes']
            if not (obj['version']==1 and self.manifest['format']==1 and self.manifest['sample'] is False and re.fullmatch(r'20\d{6}',self.day)
                    and self.manifest['bars']>0 and len(self.items)>=self.manifest['securities'] and 'snapshot' in self.items and 'coverage' in self.items):
                raise ValueError('incomplete release')
            for digest,n in self.sizes.items():
                if not HASH.fullmatch(digest) or not isinstance(n,int) or not 0<n<=MAX_PACK:raise ValueError('pack metadata')
            for key,(pack,off,n,h) in self.items.items():
                if pack not in self.sizes or not isinstance(off,int) or not isinstance(n,int) or off<0 or n<=0 or off+n>self.sizes[pack] or not HASH.fullmatch(h):raise ValueError('record metadata')
        except (ValueError,KeyError,TypeError,OSError) as e:
            if isinstance(e,ArchiveError):raise
            raise ArchiveError('正式行情目录校验失败。') from e

    def _cachefile(self,key):return self.root/key[:2]/key

    def _cached(self,key):
        p=self._cachefile(key)
        try:data=p.read_bytes()
        except FileNotFoundError:return None
        with self._check_lock:
            if key not in self._seen:
                if sha256(data).hexdigest()!=key:
                    p.unlink(missing_ok=True);return None
                self._seen.add(key)
        return data

    def _save(self,key,data):
        if sha256(data).hexdigest()!=key:raise ArchiveError('行情内容校验失败，未写入缓存。')
        p=self._cachefile(key);p.parent.mkdir(mode=0o700,exist_ok=True)
        tmp=None
        try:
            with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:
                tmp=Path(f.name);f.write(data)
            os.replace(tmp,p)
            with self._check_lock:self._seen.add(key)
        finally:
            if tmp:tmp.unlink(missing_ok=True)

    def _download(self,pack,offset=None,n=None):
        if not hasattr(self._threads,'http'):self._threads.http=requests.Session()
        headers={'X-Archive-Read':self.service,'Accept-Encoding':'identity'}
        if offset is not None:headers['Range']=f'bytes={offset}-{offset+n-1}'
        for attempt in range(3):
            try:
                with self._threads.http.get(self.base+'/v1/objects/'+pack,headers=headers,timeout=(5,35),allow_redirects=False,stream=True) as r:
                    if r.status_code in (301,302,303,307,308,401,403):raise ArchiveError('正式行情存储未通过服务端认证。')
                    if r.status_code==404:raise ArchiveError('本期正式库缺少一个已登记的数据包。')
                    r.raise_for_status()
                    if r.headers.get('X-Archive-SHA256')!=pack:raise ArchiveError('行情存储返回的内容标识不符。')
                    if r.status_code==206 and offset is not None:
                        if r.headers.get('Content-Range')!=f'bytes {offset}-{offset+n-1}/{self.sizes[pack]}':raise ArchiveError('行情字节区间不符。')
                        data=r.content
                        if len(data)!=n:raise ArchiveError('行情记录不完整。')
                        return data
                    if r.status_code!=200:raise ArchiveError('正式行情存储返回异常状态。')
                    if int(r.headers.get('Content-Length',MAX_PACK))>MAX_PACK:raise ArchiveError('行情对象超出预期大小。')
                    data=r.content
                    if len(data)>MAX_PACK or sha256(data).hexdigest()!=pack:raise ArchiveError('完整行情对象校验失败。')
                    return data if offset is None else data[offset:offset+n]
            except requests.RequestException:
                if attempt==2:raise ArchiveError('暂时无法连接正式行情存储，请稍后重试。') from None
                time.sleep(.18*(2**attempt))

    def _fetch_group(self,pack,records):
        with self._locks[int(pack[:4],16)%len(self._locks)]:
            needed=sorted((off,n,h) for off,n,h in records if not self._cachefile(h).is_file())
            if not needed:return
            # Adjacent small requested records use a single GET; do not fetch unrelated large ranges.
            groups=[]
            for rec in needed:
                if not groups or rec[0] > groups[-1][-1][0]+groups[-1][-1][1]+16384:groups.append([])
                groups[-1].append(rec)
            for group in groups:
                start=group[0][0];end=group[-1][0]+group[-1][1];chunk=self._download(pack,start,end-start)
                for off,n,h in group:self._save(h,chunk[off-start:off-start+n])

    def prefetch(self,keys):
        grouped=defaultdict(list)
        for key in dict.fromkeys(keys):
            val=self.items.get(key)
            if val and not self._cachefile(val[3]).is_file():grouped[val[0]].append(val[1:])
        tasks=[self._pool.submit(self._fetch_group,pack,records) for pack,records in grouped.items()]
        for task in tasks:task.result()

    def _blob(self,key,optional=False):
        spec=self.items.get(key)
        if not spec:
            if optional:return None
            raise ArchiveError('本期行情库没有这条记录。')
        pack,off,n,h=spec;data=self._cached(h)
        if data is None:
            self._fetch_group(pack,[(off,n,h)]);data=self._cached(h)
        if data is None or len(data)!=n:raise ArchiveError('无法读取完整的行情记录。')
        return gzip.decompress(data)
