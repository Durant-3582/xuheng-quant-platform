"""Check scheduling boundaries, bounded recovery, and lost dispatch responses without making a request."""
from datetime import datetime
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ops import cloud_clock as clock


class ClockTests(unittest.TestCase):
    def test_slots(self):
        for stamp, news, market in (
            ('2026-11-16 00:08', '2026-11-15 23:39', '2026-11-15 22:17'),
            ('2026-11-16 00:09', '2026-11-16 00:09', '2026-11-15 22:17'),
            ('2026-11-16 19:17', '2026-11-16 19:09', '2026-11-16 19:17'),
            ('2026-11-16 22:16', '2026-11-16 22:09', '2026-11-16 19:17'),
            ('2026-11-16 22:39', '2026-11-16 22:39', '2026-11-16 22:17')):
            def local(s):
                return datetime.fromisoformat(s + ':00+08:00')
            self.assertEqual(clock.scheduled_slots(local(stamp)), (local(news).timestamp(), local(market).timestamp()))

    def test_missing_timer_can_never_rearm_itself_immediately(self):
        clock.check_wait('11800', 10000, 11800)
        for due, current in [('11800', 10001), ('10000', 12000), ('abc', 12000), ('9'*90, 12000)]:
            with self.assertRaises(ValueError):
                clock.check_wait(due, 10000, current)

    def test_reconciliation(self):
        run = dict(id=1, display_title='cloud-clock 11800', created_at='2026-11-16T00:00:00Z',
                   status='completed', conclusion='failure')
        slot = clock.created(run)
        self.assertFalse(clock.covered([run], slot))
        self.assertTrue(clock.covered([run, dict(run,id=2)], slot))
        self.assertTrue(clock.covered([dict(run,conclusion='success')], slot))
        self.assertFalse(clock.covered([dict(run,conclusion='success')], slot+1))
        waiting = dict(run, status='waiting')
        self.assertTrue(clock.covered([waiting], slot+1))
        self.assertTrue(clock.next_waiting([waiting], 9))
        self.assertFalse(clock.next_waiting([waiting], 1))
        with (patch.object(clock, 'runs', side_effect=[[], [waiting]]),
              patch.object(clock, 'api', side_effect=URLError('response lost')) as post,
              patch.object(clock.time, 'sleep')):
            self.assertFalse(clock.dispatch_once(clock.CLOCK, {'due':'11800'}, lambda rows: clock.next_waiting(rows, 9)))
            self.assertEqual(post.call_count, 1)


if __name__ == '__main__':
    unittest.main()
