"""Exercise the exact same monthly lookup used by the Streamlit stock page."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from unittest import TestCase, main
from unittest.mock import patch

from xuheng.desk_api import dispatch, SnapshotChanged
from xuheng.stock_valuation import valuation_history
from xuheng.study_store import encode


class StockHistoryTests(TestCase):
    def test_cloud_edition_dates_aliases_and_thread_safe_reuse(self):
        code = '920001.BJ'
        old = '830001.BJ'
        data = encode({'20211112': {old: [1, 10, 3]}, '20211130': {old: [2, None, 3]},
                       '20211231': {old: [3, 13, 3], code: [4, 14, 3]}})
        edition = {'day': '20211231', 'files': {'values/2021': 'a'*64}}
        with tempfile.TemporaryDirectory() as folder:
            class Store:
                day = '20220105'
                root = Path(folder)
                manifest = {}
                catalog = {code: [code, '样本', 'stock', None, None, 'L', '20190101', None],
                           '000300.SH': ['000300.SH', '基准', 'index']}
                snapshot = {'aliases': {old: code}}
            store = Store()
            with patch('xuheng.stock_valuation.edition', return_value=edition), patch('xuheng.stock_valuation.content',return_value=data) as source:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    result = list(pool.map(lambda _: valuation_history(store,code), range(3)))
                expected = {'day':store.day,'edition':'20211231','rows':[['20211130',None,2],['20211231',14,4]]}
                self.assertEqual(result, [expected]*3)
                self.assertEqual(source.call_count,1)
                self.assertEqual(dispatch(store,'/api/stock-valuation?symbol='+old+'&asOf='+store.day,None,b''),expected)
                with self.assertRaises(SnapshotChanged):
                    dispatch(store,'/api/stock-valuation?symbol='+code+'&asOf=20220104',None,b'')
                with self.assertRaises(ValueError):
                    dispatch(store,'/api/stock-valuation?symbol=000300.SH',None,b'')
                store.manifest={'sample':True}
                self.assertEqual(valuation_history(store,code)['rows'],[])


if __name__=='__main__':
    main()
