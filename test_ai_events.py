import unittest
from datetime import datetime, timezone, timedelta

import ai_game
import events
import watch

KST = timezone(timedelta(hours=9))


class AiGameTest(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(ai_game.tier({'gpu': '외장그래픽 RTX5060 VRAM: 8GB 105W'}), 'S')
        self.assertEqual(ai_game.tier({'gpu': '외장그래픽 RTX3050 VRAM: 4GB'}), 'A')
        self.assertEqual(ai_game.tier({'gpu': '외장그래픽 RTX4050'}), 'A')
        self.assertEqual(ai_game.tier({'gpu': '내장그래픽 Arc 140V', 'cpu': '코어 울트라7 258V 47TOPS'}), 'B')
        self.assertEqual(ai_game.tier({'gpu': '내장그래픽 Iris Xe', 'cpu': 'i5-1340P'}), 'C')
        self.assertEqual(ai_game.tier({'gpu': '내장그래픽 Arc B390 12코어', 'cpu': '388H 50TOPS'}), 'A')
        self.assertEqual(ai_game.tier({'gpu': '내장그래픽 Radeon 8060S'}), 'A')
        self.assertIn('B390', ai_game.describe({'gpu': 'Arc B390'}))
        self.assertIn('RTX5060 8GB', ai_game.describe({'gpu': 'RTX5060 VRAM: 8GB'}))

    def test_band_ranking_prefers_gpu_tier_then_price_and_excludes_weak(self):
        base = {'ram_gb': 32, 'weight_kg': 1.4, 'price_band': '230~300만원', 'site': '에누리', 'url': 'u'}
        cands = [dict(base, name='싼 내장', model_key='싼 내장', effective_price_krw=2300000, price_krw=2300000, gpu='Iris Xe'),
                 dict(base, name='입문 RTX', model_key='입문 RTX', effective_price_krw=2400000, price_krw=2400000, gpu='RTX3050 VRAM: 4GB'),
                 dict(base, name='고급 RTX', model_key='고급 RTX', effective_price_krw=2600000, price_krw=2600000, gpu='RTX4060 VRAM: 8GB'),
                 dict(base, name='AI PC', model_key='AI PC', effective_price_krw=2350000, price_krw=2350000, gpu='Arc', cpu='47TOPS')]
        top = watch.rank_by_band(cands, 3, 'A')['230~300만원']
        self.assertEqual([p['model_key'] for p in top], ['고급 RTX', '입문 RTX'])
        top_b = watch.rank_by_band(cands, 3, 'B')['230~300만원']
        self.assertEqual([p['model_key'] for p in top_b], ['고급 RTX', '입문 RTX', 'AI PC'])


EV = [{'id': 'e1', 'name': '테스트 행사', 'start': '2026-11-01', 'end': '2026-11-11', 'notice_days': 7, 'source_url': 'https://x',
       'coupon_drops': [{'id': 'c1', 'name': '1만원 쿠폰', 'at': '2026-11-11T10:00:00+09:00', 'source_url': 'https://y'}]},
      {'id': 'nosrc', 'name': '출처 없음', 'start': '2026-11-01', 'end': '2026-11-02'}]


def keys(dt):
    return [k for k, _ in events.due_alerts(EV, dt.astimezone(timezone.utc))]


class EventsTest(unittest.TestCase):
    def test_notice_window_and_start(self):
        self.assertEqual(keys(datetime(2026, 10, 24, 12, tzinfo=KST)), [])
        self.assertEqual(keys(datetime(2026, 10, 25, 9, tzinfo=KST)), ['event:e1:notice'])
        self.assertEqual(keys(datetime(2026, 11, 1, 0, 30, tzinfo=KST)), ['event:e1:start'])
        self.assertEqual(keys(datetime(2026, 11, 12, 9, tzinfo=KST)), [])

    def test_coupon_three_stages_and_missed_window_not_sent_late(self):
        self.assertIn('coupon:e1:c1:d1', keys(datetime(2026, 11, 10, 21, tzinfo=KST)))
        self.assertIn('coupon:e1:c1:pre', keys(datetime(2026, 11, 11, 9, 20, tzinfo=KST)))
        self.assertIn('coupon:e1:c1:open', keys(datetime(2026, 11, 11, 10, 5, tzinfo=KST)))
        late = keys(datetime(2026, 11, 11, 11, 0, tzinfo=KST))
        self.assertFalse([k for k in late if k.startswith('coupon:')])

    def test_start_message_lists_top_candidates(self):
        msgs = dict(events.due_alerts(EV, datetime(2026, 11, 2, tzinfo=KST), ['[S] 2,350,000원 ASUS TUF']))
        self.assertIn('ASUS TUF', msgs['event:e1:start'])
        self.assertIn('근거: https://x', msgs['event:e1:start'])


if __name__ == '__main__':
    unittest.main()
