import unittest

import ai_game
import watchlist

P = [
    {'name': 'HP 옴니북 울트라 14-kd0056TU / SSD 1TB', 'cpu': '인텔 코어 울트라7(S3) 356H (4.7GHz) 50TOPS', 'gpu': '내장그래픽 Intel Graphics', 'ram_gb': 32, 'weight_kg': 1.27, 'price_krw': 2549000, 'url': 'https://x/1'},
    {'name': 'HP 옴니북 울트라 14-kd0057TU / SSD 1TB', 'cpu': '인텔 코어 울트라7(S3) 356H (4.7GHz) 50TOPS', 'gpu': '내장그래픽 Intel Graphics', 'ram_gb': 32, 'weight_kg': 1.27, 'price_krw': 2749000, 'url': 'https://x/2'},
    {'name': 'LG 그램 14 울트라9', 'cpu': '인텔 코어 울트라9(S3) 386H (4.9GHz) 50TOPS', 'gpu': '내장그래픽 Intel Graphics', 'ram_gb': 32, 'weight_kg': 1.1, 'price_krw': 2390000, 'url': 'https://x/3'},
    {'name': '무거운 16인치', 'cpu': '인텔 코어 울트라7(S3) 356H', 'ram_gb': 32, 'weight_kg': 1.8, 'price_krw': 1900000, 'url': 'https://x/4'},
]
G = [{'id': 'omni', 'label': '옴니북', 'name_pattern': r'14-kd00\d\d', 'min_ram': 32},
     {'id': 'similar', 'label': '비슷한 성능', 'cpu_pattern': r'울트라[79]\s*\(S3\)\s*3[5-8]\dH', 'max_weight': 1.4, 'min_ram': 32}]


class WatchlistTest(unittest.TestCase):
    def _run(self, products, state, now):
        out = watchlist.due(G, products, state, now=now)
        for _k, _m, gid, price in out:
            watchlist.commit(state, gid, price, now)
        return out

    def test_register_drop_quiet_and_rebound(self):
        from datetime import datetime, timedelta, timezone
        t = datetime(2026, 10, 28, tzinfo=timezone.utc)
        state = {}
        first = self._run(P, state, t)
        self.assertEqual(len(first), 2)
        self.assertIn('감시 등록 · 현재 최저가 2,549,000원', first[0][1])
        self.assertNotIn('무거운', first[1][1])
        self.assertEqual(self._run(P, state, t), [])
        cheaper = [dict(P[0], price_krw=2399000)] + P[1:]
        again = self._run(cheaper, state, t)
        self.assertEqual(len(again), 1)
        self.assertIn('▼ 150,000원 (5.9% 할인)', again[0][1])
        # 가격이 다시 올랐다가 같은 가격으로 돌아와도 '할인' 재알림 없음
        self.assertEqual(self._run(P, state, t + timedelta(hours=1)), [])
        self.assertEqual(self._run(cheaper, state, t + timedelta(hours=2)), [])

    def test_expired_baseline_still_alerts_lower_and_legacy_int_resets(self):
        from datetime import datetime, timedelta, timezone
        t = datetime(2026, 10, 1, tzinfo=timezone.utc)
        state = {'watch_groups': {'omni': {'low': 2549000, 'at': t.isoformat()}}}
        cheaper = [dict(P[0], price_krw=2400000)] + P[1:]
        out = watchlist.due(G[:1], cheaper, state, now=t + timedelta(days=8))
        self.assertEqual(len(out), 1)
        self.assertIn('▼ 149,000원', out[0][1])
        state = {'watch_groups': {'omni': 2000000}}
        self.assertEqual(watchlist.due(G[:1], P, state, now=t), [])
        self.assertEqual(state['watch_groups']['omni']['low'], 2549000)

    def test_repeat_drop_after_reset_has_new_key_and_naive_date(self):
        from datetime import datetime, timedelta, timezone
        t = datetime(2026, 10, 1, tzinfo=timezone.utc)
        a = watchlist.due(G[:1], [dict(P[0], price_krw=2000000)], {'watch_groups': {'omni': {'low': 2200000, 'at': t.isoformat()}}}, now=t)
        b = watchlist.due(G[:1], [dict(P[0], price_krw=2000000)], {'watch_groups': {'omni': {'low': 2200000, 'at': t.isoformat()}}}, now=t + timedelta(days=10))
        self.assertNotEqual(a[0][0], b[0][0])
        naive = {'watch_groups': {'omni': {'low': 2600000, 'at': '2026-10-01T00:00:00'}}}
        self.assertEqual(len(watchlist.due(G[:1], P, naive, now=t)), 1)

    def test_ram_unknown_tagged(self):
        p = dict(P[0]); p.pop('ram_gb')
        msg = watchlist.due(G[:1], [p], {})[0][1]
        self.assertIn('RAM 미확인', msg)

    def test_failed_delivery_retries(self):
        state = {}
        self.assertEqual(len(watchlist.due(G, P, state)), 2)   # commit 안 함 = 전송 실패
        self.assertEqual(len(watchlist.due(G, P, state)), 2)

    def test_brand_filter(self):
        china = dict(P[0], name='체리 노트북 14-kd0099', url='https://x/c')
        ms = watchlist.members(G[0], [china], brands=('삼성', 'LG', 'HP'))
        self.assertEqual(ms, [])
        hp = watchlist.members(G[0], P, brands=('HP',), require_genuine=('HP',))
        self.assertEqual(len(hp), 2)
        self.assertTrue(hp[0]['_needs_genuine_check'])
        msg = watchlist.due(G[:1], P, {}, ('HP',), ('HP',))[0][1]
        self.assertIn('국내 정품·A/S 확인 필요', msg)

    def test_vram_warning(self):
        p = {'name': 'LG 그램 프로17', 'gpu': '외장그래픽 RTX3050 VRAM: 4GB 45W'}
        self.assertEqual(ai_game.vram_warning(p), 'AI용 VRAM 부족(4GB)')
        self.assertEqual(ai_game.tier(p), 'A')
        self.assertIn('⚠ AI용 VRAM 부족(4GB)', ai_game.describe(p))
        self.assertIsNone(ai_game.vram_warning({'gpu': '외장그래픽 RTX4050 VRAM: 6GB'}))
        self.assertIsNone(ai_game.vram_warning({'gpu': '내장그래픽 Arc B390 12코어'}))

    def test_b390_inferred_from_cpu(self):
        p = {'name': '갤럭시북6 프로', 'cpu': '인텔 코어 울트라X7(S3) 358H', 'gpu': '내장그래픽 Intel Graphics'}
        self.assertEqual(ai_game.tier(p), 'A')
        self.assertEqual(ai_game.tier(P[0]), 'B')
        self.assertEqual(ai_game.strong_igpu({'cpu': 'AMD 라이젠 AI 맥스+ PRO 395'}), 'Radeon 8060S')
        self.assertEqual(ai_game.strong_igpu({'cpu': 'AMD Ryzen AI Max 390'}), 'Radeon 8050S')
        self.assertEqual(ai_game.strong_igpu({'cpu': 'AMD Ryzen AI Max+ 388'}), 'Radeon 8060S')


if __name__ == '__main__':
    unittest.main()
