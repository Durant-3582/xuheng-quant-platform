"""Increment previously archived securities by trading date, with atomic files and a resumable checkpoint."""
import datetime as dt
from zoneinfo import ZoneInfo
import sync

def run(p,old,today):
    check=p/"last-incremental"
    base=max(old,check.read_text().strip()) if check.exists() else old
    sessions=sync.api("trade_cal",{"exchange":"SSE","is_open":"1","start_date":base,"end_date":today},"cal_date")
    for d in sorted(r["cal_date"] for r in sessions if r["cal_date"]>base):
        if not sync.api("daily",{"trade_date":d,"limit":1},"ts_code"):break
        directory=sync.inventory(d); directory_path=p/"directory"/(d+".gz")
        sync.save(directory_path,directory)
        quote=sync.day_quotes(d,directory)
        if not all(c in quote for c in ("000001.SH","399001.SZ")):
            raise RuntimeError("沪深基准日线尚未发布完整，保留原交易日并等待重试。")
        for item in directory["items"]:
            code=item[0]; path=p/"series"/(code+".gz")
            if path.exists():
                series=sync.read(path)
                if series["until"]>=d:continue
                if series["status"]!="ready" and code in quote:
                    series=sync.historical(item,d)
                if code in quote:
                    bars=series["bars"];bar=quote[code]
                    if not bars or bars[-1][0]<d:bars.append(bar)
                    series["status"]="ready"
                series["until"]=d
            else:
                try: series=sync.historical(item,d)
                except sync.Denied:series={"symbol":code,"until":d,"bars":[],"status":"denied"}
            sync.save(path,series)
        sync.save(p/"snapshot"/(d+".gz"),sync.one_day(d,directory,quote,pb_store=p))
        tmp=check.with_suffix(".tmp");tmp.write_text(d);tmp.replace(check)
        print("已更新",d,len(quote),"个当日标的",flush=True)

