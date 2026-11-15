"""Advance the all-A MA200 series from archived daily trades and month-start state."""
import hashlib
import io
from itertools import groupby

import numpy as np

from xuheng.frames import DailyBlock
from xuheng.study_store import content, encode


def breadth_history(store, previous, reader, put):
    from xuheng.factor_studies import read

    base = store.daily
    codes, dates = base['codes'], base['dates']
    code_ids = {code:i for i,code in enumerate(codes)}
    starts, ends = [], []
    for c in codes:
        listed, ended = store.stock_life[c]
        starts.append(max(int(listed or 0), 20211115 if c.endswith('.BJ') else 0))
        ends.append(int(ended or 99991231))
    life = np.array([starts, ends], dtype=np.int32)
    columns = hashlib.sha256(encode(codes)).hexdigest()
    groups = [(k,list(g)) for k,g in groupby(dates,key=lambda d:d[:6])]
    parts = {k:base['parts'][k].split('/')[-1] for k,_ in groups}
    past = hashlib.sha256()
    ring = np.zeros((200,len(codes)))
    level = np.ones(len(codes))
    counts = np.zeros(len(codes),dtype=np.int64)
    total = np.zeros(len(codes))
    history, saved_month = [], ''
    if previous and 'breadth/state' in previous['files']:
        with np.load(io.BytesIO(content(previous,'breadth/state',reader)),allow_pickle=False) as state:
            month = str(state['month'])
            through = int(month+'01')
            digest = hashlib.sha256()
            for k,_ in groups:
                if k >= month:
                    break
                digest.update(parts[k].encode())
            if (month in parts and str(state['columns'])==columns and str(state['past'])==digest.hexdigest()
                    and np.array_equal(np.minimum(life,through),np.minimum(state['life'],through))):
                ring, level, counts, total = (state[k] for k in ('ring','level','counts','total'))
                history = [r for r in read(previous,'breadth',reader) if r[0][:6]<month]
                saved_month = month
                past = digest
    for month, trading in groups:
        if month < saved_month:
            continue
        if month == groups[-1][0]:
            buf = io.BytesIO()
            np.savez_compressed(buf,month=month,columns=columns,past=past.hexdigest(),life=life,
                                ring=ring,level=level,counts=counts,total=total)
            put('breadth/state',buf.getvalue())
        block = DailyBlock(store._blob(base['parts'][month]), trading, codes)
        ids = np.array([code_ids[c] for c in block.codes],dtype=int)
        for t, day in enumerate(trading):
            op, close, ref = block.quotes[:,:,t]
            eligible = ((op>0)&(close>0)&(ref>0)&(life[0,ids]<=int(day))&(life[1,ids]>=int(day)))
            idx = ids[eligible]
            slot = counts[idx]%200
            level[idx] *= close[eligible]/ref[eligible]
            total[idx] += level[idx]-ring[slot,idx]
            ring[slot,idx] = level[idx]
            counts[idx] += 1
            valid = idx[counts[idx]>=200]
            avg = total[valid]/200
            above = int(np.count_nonzero(level[valid]>avg*(1+1e-12)))
            benchmark = base['market'][store.date_ids[day]][1]
            history.append([day,above,len(valid),len(idx),benchmark if benchmark and benchmark>0 else None])
        past.update(parts[month].encode())
    if [r[0] for r in history] != dates:
        raise ValueError('市场宽度交易日与行情日历不一致。')
    put('breadth',encode(history))
    return history[-1][:4]
