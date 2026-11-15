"""Small, rate-limited official Tushare lookups, kept distinct from the frozen research release."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import re,threading,time
import requests
import streamlit as st
from .ui_common import provider_token,iso,fmt

ZONE=ZoneInfo('Asia/Shanghai'); ENDPOINT='https://api.tushare.pro'
FIELDS='ts_code,trade_date,open,high,low,close,pct_chg'; CODE=re.compile(r'[A-Z0-9_-]{1,32}\.[A-Z]{2,6}')
class FeedError(ValueError):pass

@st.cache_resource(show_spinner=False)
def _limiter():return threading.Lock(),[0.]

def fetch(api,code,lo,hi,token):
    if api not in {'daily','index_daily','sw_daily','ci_daily'} or not CODE.fullmatch(code):raise FeedError('无效的证券代码。')
    fields=FIELDS if api in ('daily','index_daily') else FIELDS.replace('pct_chg','pct_change')
    # Shared pacing caps interactive use across visitors; cache keys also include the release date and live calendar day.
    lock,next_time=_limiter()
    with lock:
        delay=next_time[0]-time.monotonic()
        if delay>1.25:raise FeedError('行情接口正在处理其他查询，请稍后再试。')
        next_time[0]=max(time.monotonic(),next_time[0])+.5
    if delay>0:time.sleep(delay)
    try:
        with requests.post(ENDPOINT,json={'api_name':api,'token':token,'params':{'ts_code':code,'start_date':lo,'end_date':hi,'limit':20},'fields':fields},timeout=(5,13),allow_redirects=False) as response:
            response.raise_for_status();body=response.json()
    except (ValueError,requests.RequestException):raise FeedError('暂时未连上 Tushare；已入库的历史查询与回测仍可使用。') from None
    if body.get('code')!=0:
        msg=str(body.get('msg') or '')
        if any(w in msg for w in ('权限','积分','访问此接口')):raise FeedError('当前 Tushare 账号没有该行情接口权限。')
        raise FeedError('Tushare 本次未返回行情（状态码 '+str(body.get('code'))+'）。')
    table=body.get('data') or {};rows=[]
    for rr in table.get('items') or []:
        row=dict(zip(table.get('fields',[]),rr));d=row.get('trade_date','')
        if row.get('ts_code')!=code or not re.fullmatch(r'\d{8}',d) or not lo<=d<=hi:raise FeedError('上游返回的证券或日期与请求不一致。')
        if row.get('close') is not None:rows.append({k:row.get(k if k!='pct_chg' or api in ('daily','index_daily') else 'pct_change') for k in FIELDS.split(',')})
    if len({x['trade_date'] for x in rows})!=len(rows):raise FeedError('上游返回重复交易日。')
    return sorted(rows,key=lambda row:row['trade_date'],reverse=True)

@st.cache_data(ttl=300,max_entries=400,show_spinner=False)
def recent(api,code,asof,_token):
    stamp=datetime.strptime(asof,'%Y%m%d');lo=(stamp-timedelta(days=35)).strftime('%Y%m%d');rows=fetch(api,code,lo,asof,_token)
    return rows,datetime.now(ZONE).strftime('%Y-%m-%d %H:%M:%S')

def cache_scope(s):return (s.day,datetime.now(ZONE).strftime('%Y%m%d'))

def market_api_panel(s):
    with st.expander('Tushare 数据状态与更新日期'):
        st.caption('比较接口最新日线与全市场回测库的截止日。同一查询缓存 5 分钟。')
        k='live_probe_result';version,today=cache_scope(s)
        if st.button('检查 Tushare 最新交易日',key='live_market_check'):
            token=provider_token();st.session_state.pop(k,None)
            if not token:st.warning('网站尚未配置 Tushare Token。')
            else:
                try:
                    with st.spinner('查询 Tushare 个股与指数日线…'):
                        a,b=_market_probe(today,token)
                    st.session_state[k]=(version,today,a,b)
                except FeedError as e:st.warning(str(e))
        saved=st.session_state.get(k)
        if saved and saved[:2]==(version,today):
            _,_,a,b=saved;common={x['trade_date'] for x in a[0]} & {x['trade_date'] for x in b[0]}
            if not common:st.info('两个接口样本最近没有共同的报价日。');return
            latest=max(common)
            st.write(f'Tushare 两个样本最近共同有报价日：**{iso(latest)}**　·　回测库截至 **{iso(version)}**。')
            st.caption(f"平安银行 {iso(a[0][0]['trade_date'])} 收盘 {fmt(a[0][0]['close'])}；上证指数 {iso(b[0][0]['trade_date'])} 收盘 {fmt(b[0][0]['close'],3)}。接口取数时间：{max(a[1],b[1])}（北京时间）。")
            if latest>version:st.info('接口已有较新日线；全市场回测仍以页面注明的完整数据版本为准。')


def _market_probe(today,token):
    a=recent('daily','000001.SZ',today,token);b=recent('index_daily','000001.SH',today,token)
    if not a[0] or not b[0]:raise FeedError('用于核对的股票或指数最近没有返回有效日线。')
    return a,b

def security_api_panel(s,code,kind,group):
    api='daily' if kind=='stock' else ('sw_daily' if group=='industry' and code.endswith('.SI') else 'ci_daily' if group=='industry' and code.endswith('.CI') else 'index_daily')
    with st.expander('查询 Tushare 最新日线'):
        st.caption('直接查询这只证券最近的盘后报价，停牌或退市后可能没有新报价。已发布的回测结果不随单只证券的查询改变。')
        stamp,today=cache_scope(s);key='live_'+kind+'_data'
        if st.button('查询接口最新报价',key='live_'+kind+'_button'):
            st.session_state.pop(key,None);token=provider_token()
            if not token:st.warning('网站尚未配置 Tushare Token。')
            else:
                try:
                    with st.spinner('连接 Tushare…'):rows,when=recent(api,code,today,token)
                    st.session_state[key]=(code,today,rows[:5],when)
                except FeedError as e:st.warning(str(e))
        reply=st.session_state.get(key)
        if reply and reply[:2]==(code,today):
            _,_,rows,when=reply
            if rows:
                st.write('**'+code+'** · API 最近报价 '+iso(rows[0]['trade_date'])+'　·　已入库截至 '+iso(stamp))
                st.dataframe([{'交易日':iso(row['trade_date']),'开盘':row['open'],'最高':row['high'],'最低':row['low'],'收盘':row['close'],'涨跌幅（%）':row['pct_chg']} for row in rows],hide_index=True,use_container_width=True)
            else:st.info('最近 35 个自然日没有这只证券的有效收盘报价。')
            st.caption('接口取数时间：'+when+'（北京时间）。')
