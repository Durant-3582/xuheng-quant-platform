"""Build private daily portfolio inputs. Row i is traded at today's open on yesterday's signal."""
from collections import defaultdict
from pathlib import Path
import gzip, hashlib, struct, tempfile
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import sync
from portfolio import BENCHMARKS

DT=np.dtype([('prices','<i4',(3,)),('flags','u1'),('factor','<f8',(3,)),('fit','<f4',(4,))])
SCALE=10000
LIMIT=200

def previous_window(x,n):
    sums=np.concatenate(([0.],np.cumsum(x,dtype='float64')))
    return sums[n:]-sums[:-n]

def build(store,day):
    catalog=sync.read(store/'snapshot'/(day+'.gz'))
    meta={r[0]:r for r in catalog['items']}
    codes=sorted(k for k,v in meta.items() if v[2]=='stock')
    def history(code):
        s=sync.read(store/'series'/(code+'.gz'))
        if s['symbol']!=code or s['until']<day:raise ValueError('行情未就绪 '+code)
        return s['bars']
    cal=[r[0] for r in history('000001.SH') if sync.START<=r[0]<=day]
    if cal!=[r[0] for r in history('399001.SZ') if sync.START<=r[0]<=day] or cal[-1]!=day:raise ValueError('交易日历不一致')
    keys={d:i for i,d in enumerate(cal)};D=len(cal);N=len(codes)
    index_return=[];markets=np.zeros((D,4),dtype=float)
    for j,code in enumerate(BENCHMARKS):
        bars={b[0]:b for b in history(code) if b[0]>=meta[code][6]}
        ret=np.full(D,np.nan)
        for i,d in enumerate(cal):
            b=bars.get(d)
            if b and b[1] and b[4]:markets[i,j*2:j*2+2]=[b[1],b[4]]
            if i and b and cal[i-1] in bars and b[4] and (prev:=b[5] or bars[cal[i-1]][4]):ret[i]=b[4]/prev-1
        index_return.append(ret)
    groups=defaultdict(list)
    for i,d in enumerate(cal):groups[d[:6]].append(i)
    output=store/'research'/day;output.mkdir(parents=True,exist_ok=True)
    venues=np.array([{'SH':0,'SZ':1,'BJ':2}[c[-2:]] for c in codes],dtype='u1')
    versions={};digests={}
    with tempfile.TemporaryDirectory(dir=store) as work:
        arr=np.memmap(Path(work)/'daily',dtype=DT,mode='w+',shape=(N,D))
        for code_i,code in enumerate(codes):
            bars=[b for b in history(code) if b[0] in keys]; out=arr[code_i]
            out['factor']=np.nan
            if not bars:continue
            ds=np.fromiter((keys[b[0]] for b in bars),dtype=int)
            if np.any(np.diff(ds)<=0):raise ValueError('日线重复或乱序 '+code)
            q=np.array([[b[1],b[2],b[3],b[4],b[5],b[7]] for b in bars],dtype=float)
            op,hi,lo,cl,pr,vol=q.T
            mark=(cl>0)&(pr>0);opened=mark&(op>0)&(vol>0)
            for j,(v,valid) in enumerate([(op,opened),(cl,mark),(pr,mark)]):
                vals=np.rint(v[valid]*SCALE)
                if np.any(vals>2147483647) or np.any(np.abs(v[valid]*SCALE-vals)>1e-5):raise ValueError('价格精度超出存储范围 '+code)
                out['prices'][ds[valid],j]=vals.astype('i4')
            px=np.floor(op[opened]*100+.5000001).astype('i8');ref=np.floor(pr[opened]*100+.5000001).astype('i8')
            up=np.zeros(len(px),dtype=bool);down=up.copy()
            for band in (5,10,20,30):
                up|=(px==(ref*(100+band)+50)//100)
                down|=(px==(ref*(100-band)+50)//100)
            out['flags'][ds[opened]]=(~((px>ref)&up)).astype('u1')+2*(~((px<ref)&down)).astype('u1')
            good=(q>0).all(axis=1);g=ds[good];ratio=cl[good]/pr[good]
            nextg=g+1;out['flags'][nextg[nextg<D]]|=8
            for n in (20,60):
                if len(g)<n:continue
                ws=sliding_window_view(ratio,n)
                dest=nextg[n-1:];ok=dest<D
                out['factor'][dest[ok],0 if n==60 else 2]=np.round((np.prod(ws,axis=1)[ok]-1)*100,5)
                if n==20:out['factor'][dest[ok],1]=np.round(np.std(ws,axis=1,ddof=1)[ok]*np.sqrt(252)*100,5)
            if len(g)>1:
                adj=np.r_[False,np.diff(g)==1]
                for j,idxr in enumerate(index_return):
                    valid=adj&np.isfinite(idxr[g]);x=idxr[g[valid]];y=ratio[valid]-1
                    if len(x)<120:continue
                    sx=previous_window(x,120);sy=previous_window(y,120)
                    xx=previous_window(x*x,120)-sx*sx/120;xy=previous_window(x*y,120)-sx*sy/120
                    beta=np.divide(xy,xx,out=np.zeros_like(xy),where=xx>1e-12)
                    variance=(previous_window(y*y,120)-sy*sy/120-beta*xy)/118
                    goodfit=(xx>1e-12)&(variance>1e-12)
                    av=np.where(goodfit,np.round((sy-beta*sx)/120,10),0)
                    vv=np.where(goodfit,np.round(variance,12),0)
                    # Suspending a stock doesn't manufacture daily pairs. Reuse the latest completed fit only on a valid signal close.
                    starts=g[valid][119:];ids=np.searchsorted(starts,g,side='right')-1
                    ok=(ids>=0)&(nextg<D)
                    out['fit'][nextg[ok],2*j]=av[ids[ok]];out['fit'][nextg[ok],2*j+1]=vv[ids[ok]]
            if (code_i+1)%1000==0:print('逐日信号',code_i+1,'/',N,flush=True)
        arr.flush()
        for ym,ns in groups.items():
            block=np.array(arr[:,ns[0]:ns[-1]+1],copy=True)
            active=np.flatnonzero((block['flags']!=0).any(axis=1)|(block['prices'][:,:,1]!=0).any(axis=1))
            b=block[active];nd=len(ns);na=len(active)
            buf=bytearray(struct.pack('<4sHH',b'XHD1',nd,na));buf.extend(active.astype('<u2').tobytes())
            while len(buf)%4:buf.append(0)
            # Separate security-major columns give neighboring dates effective compression.
            for k in range(3):buf.extend(b['prices'][:,:,k].astype('<i4').tobytes())
            for k in range(4):buf.extend(b['fit'][:,:,k].astype('<f4').tobytes())
            buf.extend(b['flags'].tobytes())
            while len(buf)%4:buf.append(0)
            vv=venues[active]
            for ti in range(nd):
                for k in range(3):
                    v=b['factor'][:,ti,k];valid=np.flatnonzero(np.isfinite(v))
                    sorted_idx=valid[np.argsort(-v[valid] if k==0 else v[valid],kind='stable')]
                    keep=np.zeros(na,dtype=bool)
                    for ex in range(3):keep[sorted_idx[vv[sorted_idx]==ex][:LIMIT]]=True
                    tops=sorted_idx[keep[sorted_idx]]
                    buf.extend(struct.pack('<H',len(tops)));buf.extend(tops.astype('<u2').tobytes())
                    buf.extend(v[tops].astype('<f4').tobytes())
            blob=gzip.compress(buf,compresslevel=4,mtime=0)
            if len(blob)>6000000:raise ValueError('逐日分片过大 '+ym+' '+str(len(blob)))
            h=hashlib.sha256(blob).hexdigest();name='days-'+ym+'-'+h
            path=output/(name+'.gz');tmp=path.with_suffix('.part');tmp.write_bytes(blob);tmp.replace(path)
            digests[name]=h;versions[ym]='research/'+day+'/'+name
            if ym.endswith('12'):print('逐日归档',ym,flush=True)
    obj=dict(format=1,day=day,codes=codes,dates=cal,market=markets.tolist(),parts=versions)
    obj['version']=hashlib.sha256(sync.js(obj)).hexdigest()
    index=output/'days-index.gz';sync.save(index,obj)
    digests['days-index']=hashlib.sha256(index.read_bytes()).hexdigest()
    (output/'days-digests.json').write_bytes(sync.js(digests))
    print('逐日档案完成',N,D,len(versions),'个月',round(sum((output/(k+'.gz')).stat().st_size for k in digests)/1e6,1),'MB',flush=True)

if __name__=='__main__':
    root=sync.STORE;build(root,sorted((root/'snapshot').glob('*.gz'))[-1].stem)
