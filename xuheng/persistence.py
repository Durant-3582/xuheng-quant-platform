"""Only research settings go into this visitor's browser. Returns and API credentials never do."""
from datetime import date
import math
from pathlib import Path
import re
import secrets

import streamlit as st
from streamlit.components.v1 import declare_component

bridge=declare_component("xuheng_settings",path=str(Path(__file__).parent/'browser_settings'))
DEFAULT=(('600519.SH',40.),('000001.SZ',30.),('300750.SZ',30.))
FREQUENCIES={'hold','months','quarter','half','days'}


def roster(s,pairs):
    if not isinstance(pairs,(tuple,list)) or len(pairs)>200:return None
    out=[];seen=set()
    for row in pairs:
        if not isinstance(row,(list,tuple)) or len(row)!=2:return None
        c,w=row
        if not isinstance(c,str) or c in seen or c not in s.catalog or s.catalog[c][2]!='stock':return None
        if not isinstance(w,(float,int)) or not math.isfinite(w) or not 0<=w<=100:return None
        seen.add(c);out.append((c,round(float(w),6)))
    return out


def transferable(s,key,v,decode):
    m=re.fullmatch(r'cfg_(range|study)_(?:[0-7]_)?([A-Za-z]+|weight_[0-9]{1,3})',key) if isinstance(key,str) else None
    if not m:return None
    field=m[2]
    if field=="rankweights":
        return v if isinstance(v,str) and len(v)<=4000 else None
    if field in ('a','b','trainA','trainB','testA','testB'):
        try:
            d=date.fromisoformat(v) if decode and isinstance(v,str) else v
            if not isinstance(d,date) or not '20000101'<=d.strftime('%Y%m%d')<=s.day:return None
            return d if decode else d.isoformat()
        except ValueError:return None
    enums={'model':{'mom','vol','rev','pb','manual'},'source':{'all','manual'},'manw':{'equal','tb','manual'},
           'sysw':{'equal','tb','manual'},'freqcustom':FREQUENCIES,'freqmodel':FREQUENCIES,
           'benchmark':{'000300.SH','000001.SH','000905.SH','000852.SH','899050.BJ'},
           'exchange':{'','SH','SZ','BJ'},'ctrl':{'mom','vol','rev'},'criterion':{'return','sharpe','drawdown'}}
    if field in enums:
        return v if isinstance(v,str) and v in enums[field] and not (key.startswith('cfg_study_') and field=='model' and v=='manual') else None
    bounds={'count':(1,200),'days':(1,10000),'daysmodel':(1,10000),'candidates':(2,8),'candidatesFactor':(2,8),'candidatesManual':(2,8),'fee':(0.,100.)}
    lo,hi=bounds.get(field,(0.,100.) if field.startswith('weight_') else (1,0))
    if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:return None
    if field in ('count','days','daysmodel','candidates','candidatesFactor','candidatesManual'):return int(v) if int(v)==v else None
    return float(v)


def clean_windows(windows,s):
    if not isinstance(windows,list):return []
    def good(d):
        if not isinstance(d,str) or not re.fullmatch(r'\d{8}',d):return False
        try:date.fromisoformat(d);return '20000101'<=d<=s.day
        except ValueError:return False
    return [(a,b) for pair in windows[:300] if isinstance(pair,(list,tuple)) and len(pair)==2
            for a,b in [pair] if good(a) and good(b) and a<=b]


def restore(s):
    ss=st.session_state
    ss.setdefault('portfolio_roster',[])
    ss.setdefault('roster_equal',True)
    incoming=ss.pop('_browser_restore',None)
    if not isinstance(incoming,dict):return
    saved=roster(s,incoming.get('roster'))
    if saved is not None:
        ss['portfolio_roster']=saved;ss['roster_equal']=incoming.get('equal') is True
    draft=incoming.get('draft')
    if not isinstance(draft,dict) or draft.get('version')!=s.manifest['files']['catalog']['sha256']:return
    inputs=draft.get('inputs',{})
    if isinstance(inputs,dict) and len(inputs)<=1800:
        for k,v in inputs.items():
            parsed=transferable(s,k,v,True)
            if parsed is not None:ss[k]=parsed
    if draft.get('tab') in ('区间回测','参数比较与样本外检验'):ss['cfg_portfolio_tab']=draft['tab']
    windows=clean_windows(draft.get('seen'),s)+ss.get('seen_performance_windows',[])
    ss['seen_performance_windows']=sorted(set(windows))
    if draft.get('locked') is True:
        locked=roster(s,draft.get('lockedRoster'))
        if locked is not None:ss['restore_locked_roster']=locked


def persist(s):
    ss=st.session_state
    if '_browser_sid' not in ss:ss['_browser_sid']=secrets.token_urlsafe(12)
    inputs={}
    for k in ss:
        if k.startswith(('cfg_range_','cfg_study_')):
            v=transferable(s,k,ss[k],False)
            if v is not None:inputs[k]=v
    draft={'version':s.manifest['files']['catalog']['sha256'],'inputs':inputs,'tab':ss.get('cfg_portfolio_tab'),
           'seen':ss.get('seen_performance_windows',[]),'locked':'frozen_study' in ss,
           'lockedRoster':ss.get('study_locked_roster',[])}
    readable=ss.get('_browser_loaded',False)
    reply=bridge(sid=ss['_browser_sid'],write=readable,roster=ss['portfolio_roster'],equal=ss.get('roster_equal',True),draft=draft,
                 ack=ss.get('_portfolio_browser_event',''),
                 key='visitor_settings',default=None)
    if isinstance(reply,dict) and reply.get('sid')==ss['_browser_sid'] and reply.get('id')!=ss.get('_portfolio_browser_event'):
        ss['_portfolio_browser_event']=reply.get('id')
        ss['_portfolio_storage_error']=reply.get('storageError') is True
        if reply.get('event') in ('load','sync'):
            # Only a brand new server session may restore the saved tab or study.
            # A component remount after the visitor clicked a control may synchronize
            # their shared roster, but must never replay an older tab or parameter set.
            incoming=dict(reply)
            if readable or reply.get('event')=='sync':incoming.pop('draft',None)
            ss['_browser_loaded']=True;ss['_browser_restore']=incoming;st.rerun()
    if ss.get('_portfolio_storage_error'):
        st.caption('浏览器未允许保存研究设置。本次会话仍可使用自选名单和参数。')


def valid_filters(rows):
    rules={}
    if isinstance(rows,list):
        for row in rows:
            if not isinstance(row,dict):
                continue
            name,sector=row.get('name'),row.get('sector')
            if (not isinstance(name,str) or not 1<=len(name.strip())<=40 or
                not isinstance(sector,str) or not 1<=len(sector)<=120 or
                row.get('factor') not in ('mom','vol','pe','pb','turn') or row.get('market') not in ('','SH','SZ','BJ')):
                continue
            rules[name.strip()]={'factor':row['factor'],'market':row['market'],'sector':sector}
    return rules


def apply_filter_edit(rules,edit):
    rules.pop(edit['name'],None)
    if edit['action']=='save':
        rules[edit['name']]=edit['rule']


def edit_filter(action,name,rule):
    state=st.session_state
    edit={'id':secrets.token_urlsafe(10),'action':action,'name':name,'rule':rule}
    edits=state.setdefault('_factor_edits',[])
    edits.append(edit)
    apply_filter_edit(state.setdefault('_factor_rules',{}),edit)
    if action=='save':
        state['factor_rule_choice']=name


def filter_settings():
    state=st.session_state
    if '_filter_sid' not in state:
        state['_filter_sid']=secrets.token_urlsafe(12)
    pending=state.setdefault('_factor_edits',[])
    rules=state.setdefault('_factor_rules',{})
    reply=bridge(mode='filters',sid=state['_filter_sid'],edits=pending,key='factor_rule_storage',default=None)
    if (isinstance(reply,dict) and reply.get('sid')==state['_filter_sid'] and
        reply.get('id')!=state.get('_filter_browser_event') and isinstance(reply.get('rules'),list)):
        state['_filter_browser_event']=reply.get('id')
        state['_filter_storage_error']=reply.get('storageError') is True
        done=set(reply.get('applied',[]))
        pending=[edit for edit in pending if edit['id'] not in done]
        rules=rules.copy() if state['_filter_storage_error'] else valid_filters(reply['rules'])
        for edit in pending:
            apply_filter_edit(rules,edit)
        state['_factor_rules']=rules
        state['_factor_edits']=pending
    return rules

