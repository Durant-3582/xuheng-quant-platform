"""Regression checks for disclosure vintages, ties, missing data and industry trade timing."""
from pathlib import Path
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from xuheng.disclosed import annual_roe, latest, revisions
from xuheng.factor_studies import percentile, rho, scored, score_order, test_factors, weights, window
from xuheng.industry_study import backtest, exchange, month_key
from xuheng.portfolio_risk import estimate
from xuheng.desk_api import parse_rules
from xuheng.portfolio import validate
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ingest'))
from study_sources import report_pages


class ResearchTests(unittest.TestCase):
    def test_same_day_research_correction(self):
        from xuheng import study_store
        store = SimpleNamespace(day='20261113', remote=True, manifest={})
        def pointer(day, digest):
            return {'format':1, 'day':day, 'files':{'panel/2026':digest * 64}}
        seed, fixed = pointer(store.day,'a'), pointer(store.day,'b')
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / 'static/study-release.json'
            baseline.parent.mkdir()
            baseline.write_text(json.dumps(seed))
            response = Mock()
            response.json.side_effect = [fixed, pointer('20261112','c')]
            with patch.object(study_store,'ROOT',Path(tmp)), patch.object(study_store,'_checked',{}), \
                    patch.object(study_store.requests,'get',return_value=response) as get, \
                    patch.object(study_store.time,'monotonic',side_effect=[1,2,3,200,201]):
                self.assertEqual(study_store.edition(store,refresh=False),seed)
                get.assert_not_called()
                self.assertEqual(study_store.edition(store),fixed)
                self.assertEqual(study_store.factor_snapshot(store),(store.day,tuple(fixed['files'].items())))
                self.assertEqual(study_store.edition(store),fixed)
                self.assertEqual(study_store.edition(store,refresh=False),fixed)
                self.assertEqual(get.call_count,2)
            store.day = '20261116'
            response.json.side_effect = [pointer(store.day,'c')]
            with patch.object(study_store,'ROOT',Path(tmp)), patch.object(study_store,'_checked',{}), \
                    patch.object(study_store.requests,'get',return_value=response):
                self.assertEqual(study_store.edition(store,refresh=False)['day'],store.day)

    def test_multifactor_cache_and_locked_research_version(self):
        from xuheng import desk_api, portfolio
        class Store:
            release_id = 'same-market'
        store = Store()
        a = ('20261113',(('panel/2026','a'*64),))
        b = ('20261113',(('panel/2026','b'*64),))
        raw = dict(model='multi',count=10,fee=10,interval=1,weighting='equal',bench='000300.SH',
                   factorWeights={'mom':100})
        rule = parse_rules(raw)
        with patch.object(portfolio,'factor_snapshot',side_effect=[a,a,b]), \
                patch.object(portfolio,'_compute',side_effect=[{'id':1},{'id':2}]) as calc:
            self.assertEqual([portfolio.run(store,rule,'20250101','20251031')['id'] for _ in range(3)],[1,1,2])
            self.assertEqual(calc.call_count,2)
        key = b'test-only'
        # A non-multifactor winner remains bound to the input shared by all candidates.
        signed = {'rules':{**raw,'model':'mom'}, 'factorSnapshot':desk_api.snapshot_digest(a)}
        winner = desk_api.seal(signed,'winner',store.release_id,key)
        with patch.object(desk_api,'factor_snapshot',return_value=a):
            locked = desk_api.portfolio(store,{'action':'lock','token':winner},key)['token']
        with patch.object(desk_api,'factor_snapshot',return_value=b):
            for action, token in [('lock',winner),('test',locked),('review',locked)]:
                with self.assertRaisesRegex(desk_api.SnapshotChanged,'多因子研究数据已更新'):
                    desk_api.portfolio(store,{'action':action,'token':token},key)

    def test_covariance_cash_and_insufficient_history(self):
        x=np.linspace(-.01,.01,120)
        r=np.column_stack([x,-.5*x])
        books={'equal':{'A':.6,'B':.2},'tb':{}}
        results,usable=estimate(['A','B'],r,books)
        self.assertEqual(usable.sum(),120)
        self.assertEqual(results['tb']['state'],'cash')
        self.assertAlmostEqual(results['equal']['cash'],20)
        np.testing.assert_allclose([row[2] for row in results['equal']['rows']],[120,-20])
        self.assertAlmostEqual(sum(row[3] for row in results['equal']['rows']),results['equal']['vol'])
        self.assertAlmostEqual(results['equal']['matrix'][0][1],-1)
        r[:61,1]=np.nan
        self.assertEqual(estimate(['A','B'],r,books)[0]['equal']['state'],'short')
        neutral={'tb':{'A':1/3,'B':2/3}}
        self.assertEqual(estimate(['A','B'],np.column_stack([x,-.5*x]),neutral)[0]['tb']['state'],'constant')

    def test_multifactor_model_validation(self):
        from types import SimpleNamespace
        s=SimpleNamespace(day='20261113')
        base=dict(model='multi',count=10,fee=10,interval=1,weighting='tb',bench='000300.SH',factorWeights={'pb':40,'roe':35,'mom':25})
        validate(s,parse_rules(base),'20260101',s.day)
        for wrong in ({'factorWeights':{'mom':99}}, {'factorWeights':{'mom':101}}, {'factorWeights':{'unknown':100}},
                      {'intervalUnit':'days'},{'intervalUnit':'hold'}):
            with self.assertRaises(ValueError):
                validate(s,parse_rules({**base,**wrong}),'20260101',s.day)

    def test_announcements_and_restatements(self):
        rows=[['20221231','20230401','0',1,12,40,30,8,10],['20221231','20230401','1',1,13,40,30,8,10],
              ['20221231','20230401','1',1,13,40,30,None,11],['20221231','20230902','1',1,14,40,30,9,11],
              ['20230331','20230422','1',0,2,38,31,9,12],['20231231','20240420','1',2,18,42,27,15,11]]
        rev=revisions(rows)
        self.assertEqual(latest(rev,'20230331'),[])
        april=latest(rev,'20230405')[0]
        self.assertEqual((april[3],april[6],april[7]),(None,8,None))
        self.assertEqual(latest(rev,'20231030')[0][0],'20230331')
        by_day=annual_roe(rev,['20230331','20230405','20230901','20230903','20240421','20260731'])
        self.assertEqual({k:r[3] for k,r in by_day.items()},{'20230903':14,'20240421':18})

    def test_percentiles_and_pool(self):
        np.testing.assert_allclose(percentile(np.array([4.,2.,4.,1.])),[83.33333333,33.33333333,83.33333333,0])
        a=np.asarray([[1000001,3,6,-1,None,2,7],[2000001,1,2,5,4,None,3],
                      [2000002,2,3,1,None,4,5],[3000001,None,0,4,4,5,6]],dtype=float)
        w=weights({'weights':{'mom':40,'pb':60}})
        rows,rank,parts=scored(a,w,'')
        np.testing.assert_array_equal(rows[:,0],[2000001,2000002])
        np.testing.assert_allclose(rank,[0,100])
        self.assertEqual(scored(a,w,'BJ')[0].shape,(0,7))
        np.testing.assert_allclose(scored(a,weights({'weights':{'vol':100}}),'SH')[1],[50])
        for bad in ({'x':100},{'mom':20},{'mom':-1,'pb':101},{'roe':float('nan')}):
            with self.assertRaises(ValueError):weights({'weights':bad})
        self.assertIsNone(rho(np.ones(5),np.arange(5)))
        self.assertAlmostEqual(rho(np.arange(5),np.arange(4,-1,-1)),-1)
        with self.assertRaises(ValueError):window({'from':'20240230','to':'20240920'},'20240920')

    def test_self_financing_rotation(self):
        rate=0.001
        op=np.array([100.,50.])
        units,cash,capital,cost=exchange(np.zeros(2),1.,op,np.array([1.,0.]),rate)
        self.assertAlmostEqual(units[0]*100,1/(1+rate))
        self.assertAlmostEqual(units@op+cash+cost,capital)
        op=np.array([110.,60.])
        second,cash,capital,cost=exchange(units,cash,op,np.array([0.,1.]),rate)
        expected=capital*(1-rate)/(1+rate)
        self.assertAlmostEqual(second[1]*60,expected)
        self.assertAlmostEqual(second@op+cash+cost,capital)
        flat,cash,capital,cost=exchange(second,cash,op,np.zeros(2),rate)
        self.assertTrue(np.all(flat==0))
        self.assertAlmostEqual(cash,capital*(1-rate))
        self.assertEqual(month_key('20260130',-1),'202512')
        self.assertEqual(month_key('20260130',-12),'202501')

    def test_factor_horizons_use_original_ranks_and_closed_months(self):
        days=['20231229','20240131','20240229','20240329','20240430','20240531','20240628']
        ids=np.array([1600000,2000001,3000002,1600001,2000002,3000003])
        x=np.arange(1.,7.)
        periods,panels=[],{}
        for i in range(6):
            sig,end=days[i],days[i+1]
            mom=-x if i==1 else x
            panels[sig]=np.column_stack([ids,mom,x,x,x,x,x,x,x])
            panels['returns_'+sig]=np.column_stack([ids,x])
            periods.append([sig,end[:6]+'05',end])
        buf=io.BytesIO()
        np.savez_compressed(buf,**panels)
        idx={'years':{'2024':periods},'day':days[-1]}
        with patch('xuheng.factor_studies.content',return_value=buf.getvalue()):
            r=test_factors(idx,'',weights({'weights':{'mom':100}}),'',{'from':'20240101','to':'20240628'})
            short=test_factors(idx,'',weights({'weights':{'mom':100}}),'',{'from':'20240101','to':'20240530'})
        self.assertEqual([k[1] for k in r['persistence']],[6,5,4,1])
        np.testing.assert_allclose([k[2] for k in r['persistence']],[4/6,3/5,.5,1])
        self.assertEqual(short['persistence'][-1],[6,0,None,0])
        pb_roe=next(p for p in r['overlap'] if p[:2]==['pb','roe'])
        self.assertAlmostEqual(pb_roe[2],-1)
        self.assertEqual(pb_roe[3],6)
        tied=score_order(panels[days[0]],np.ones(6))
        self.assertEqual(ids[tied].tolist(),[2000001,3000002,2000002,3000003,1600000,1600001])

    def test_financial_pagination_with_ties(self):
        raw=[dict(ts_code=c,end_date=p,ann_date='20240420',id=i) for c in ['A','B','C']
             for p in ['20231231','20230930','20230630'] for i in range(45)]
        calls=[]
        def fetch(_,q,fields):
            calls.append(q)
            candidates=[r for r in raw if r['ts_code'] in q['ts_code'].split(',') and q['start_date']<=r['end_date']<=q['end_date']]
            candidates.sort(key=lambda r:(r['end_date'],r['id'] if len(calls)%2 else -r['id']),reverse=True)
            return candidates[:100]
        with patch('study_sources.sync.api',side_effect=fetch):
            got=list(report_pages(['A','B','C'],'20240501','20240420'))
        ident=lambda r:(r['ts_code'],r['end_date'],r['id'])
        self.assertEqual(sorted(map(ident,raw)),sorted(map(ident,got)))
        self.assertTrue(all(q.get('ann_date')=='20240420' and 'offset' not in q for q in calls))

    def test_month_end_and_opening_without_published_prices(self):
        dates=[];d=date(2020,1,1)
        while d<=date(2022,3,4):
            if d.weekday()<5:
                dates.append(d.strftime('%Y%m%d'))
            d+=timedelta(days=1)
        prices=np.column_stack((np.arange(len(dates))+100.,np.arange(len(dates))*.5+200.))
        op=prices-.1
        for missing in ('20220131','20220201'):
            prices[dates.index(missing)]=np.nan
            op[dates.index(missing)]=np.nan
        ends={d[:6]:i for i,d in enumerate(dates)}
        observed={d[:6]:i for i,d in enumerate(dates) if np.isfinite(prices[i]).any()}
        data=(dates,op,prices,ends,np.ones(len(dates))*500.,[('A','甲'),('B','乙')],observed)
        result=backtest(data,'20220101','20220304',1,.001,False)
        feb=result['log'][1]
        self.assertEqual((feb['signal'],feb['observed'],feb['entry']),('20220131','20220128','20220202'))
        self.assertEqual(result['missing'],['20220131','20220201'])
        self.assertTrue(all(r['names']==['甲'] for r in result['log']))


if __name__=='__main__':
    unittest.main()
