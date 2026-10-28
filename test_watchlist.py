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
    def test_register_drop_and_quiet(self):
        state = {}
        first = watchlist.due(G, P, state)
        self.assertEqual(len(first), 2)
        self.assertIn('감시 등록 · 현재 최저가 2,549,000원', first[0][1])
        self.assertNotIn('무거운', first[1][1])
        self.assertEqual(watchlist.due(G, P, state), [])
        cheaper = [dict(P[0], price_krw=2399000)] + P[1:]
        again = watchlist.due(G, cheaper, state)
        self.assertEqual(len(again), 1)
        self.assertIn('▼ 150,000원 (5.9% 할인)', again[0][1])

    def test_b390_inferred_from_cpu(self):
        p = {'name': '갤럭시북6 프로', 'cpu': '인텔 코어 울트라X7(S3) 358H', 'gpu': '내장그래픽 Intel Graphics'}
        self.assertEqual(ai_game.tier(p), 'A')
        self.assertEqual(ai_game.tier(P[0]), 'B')


if __name__ == '__main__':
    unittest.main()
