"""Validate transport/cache behavior with the exact immutable objects prepared for deployment."""
import tempfile,sys,hashlib,threading,time,os
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from xuheng.packed_archive import PackedArchive,ORIGIN
from xuheng.archive import Archive,ArchiveError
from xuheng.frames import Rules
from xuheng.portfolio import run

class Mirror(PackedArchive):
    source=root/'.private/cloud-release/objects'
    def _download(self,pack,offset=None,n=None):
        with (self.source/pack).open('rb') as f:
            if offset is not None:f.seek(offset)
            ans=f.read() if n is None else f.read(n)
        with self.measure:self.reads+=1;self.bytes+=len(ans)
        return ans

with tempfile.TemporaryDirectory() as d:
    s=Mirror.__new__(Mirror);s.measure=threading.Lock();s.bytes=s.reads=0
    s.__init__(d,ORIGIN,(root/'.private/cloud-release/index.sha256').read_text().strip(),'fake-read-for-local-test');truth=Archive(root/'.private/database')
    s.prefetch(['snapshot','coverage','series/000300.SH']);assert s.snapshot==truth.snapshot and s.coverage==truth.coverage and s.series('000300.SH')==truth.series('000300.SH')
    assert s.reads==3 and s.bytes<=1500000,(s.reads,s.bytes);print('Homepage records:',s.reads,s.bytes,flush=True)
    for code in ['600000.SH','000001.SZ','920185.BJ','000001.SH','000300.SH']:
        assert s.series(code)==truth.series(code)
    s.reads=s.bytes=0
    cases=[(Rules(count=30),'20000508',s.day),(Rules(model='pb',count=5,interval=3),'20210101','20221130'),(Rules(model='vol',cadence='days',interval=17,bench='000905.SH'),'20230801','20231231'),(Rules(model='manual',cadence='hold',count=2,symbols=('000001.SZ','600519.SH'),weighting='tb',bench='000905.SH'),'20240101','20241130')]
    for rule,a,b in cases:
        then=time.perf_counter();r=run(s,rule,a,b);expected=run(truth,rule,a,b)
        assert r==expected,(rule,a,b);io=s.reads
        again=run(s,rule,a,b);assert again==r and s.reads==io
        print(rule.model,rule.cadence,len(r['months']),round(r['main']['total'],7),'I/O',io,round(time.perf_counter()-then,2),flush=True)
    cold=Mirror.__new__(Mirror);cold.measure=threading.Lock();cold.bytes=cold.reads=0;cold.__init__(d,ORIGIN,s.release_id,'local-only');assert cold.series('600000.SH')==truth.series('600000.SH') and cold.reads==0
    objecthash=s.items['series/600000.SH'][3];(s._cachefile(objecthash)).write_bytes(b'wrong');new=Mirror.__new__(Mirror);new.measure=threading.Lock();new.bytes=new.reads=0;new.__init__(d,ORIGIN,s.release_id,'local-only');assert new.series('600000.SH')==truth.series('600000.SH') and new.reads==1
    assert s.json('no/such/key',True) is None
print('PASS: full local SQLite agrees with packed transport, no warm downloads, damaged cached record refetched.')
