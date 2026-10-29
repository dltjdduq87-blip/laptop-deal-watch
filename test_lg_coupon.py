import unittest
from datetime import datetime, timedelta, timezone
import watchlist

KST = timezone(timedelta(hours=9))
EV = [{'id': 'lg', 'name': 'LG 블프', 'start': '2026-10-29', 'end': '2026-11-30', 'coupon_site': 'LG',
       'coupon_tiers': [[500000, 50000], [2500000, 230000], [3000000, 270000]], 'coupon_note': '앱 전용'}]


class LgCouponTest(unittest.TestCase):
    def test_tier_and_site(self):
        self.assertEqual(watchlist.coupon_estimate({'site': 'LG', 'price_krw': 3268370}, EV, '2026-10-29')[:2], (2998370, 270000))
        self.assertEqual(watchlist.coupon_estimate({'site': 'LG', 'price_krw': 2763530}, EV, '2026-11-30')[1], 230000)
        self.assertIsNone(watchlist.coupon_estimate({'site': '다나와', 'price_krw': 3268370}, EV, '2026-10-29'))
        self.assertIsNone(watchlist.coupon_estimate({'site': 'LG', 'price_krw': 3268370}, EV, '2026-12-01'))

    def test_message_line(self):
        g = [{'id': 'gram', 'label': '그램 프로16', 'name_pattern': '16Z90U-?KU7', 'min_ram': 32}]
        p = [{'name': 'LG 그램 프로16 16Z90U-KU70K', 'site': 'LG', 'price_krw': 3268370, 'ram_gb': 32, 'url': 'u', 'in_stock': True}]
        out = watchlist.due(g, p, {}, ['LG'], now=datetime(2026, 10, 29, 4, tzinfo=timezone.utc), coupon_events=EV)
        self.assertIn('2,998,370원', out[0][1])

    def test_model_field_match_and_freshness(self):
        now = datetime(2026, 10, 29, 4, tzinfo=timezone.utc)
        g = [{'id': 'gram', 'label': 'g', 'name_pattern': '16Z90U-?KU7', 'min_ram': 32}]
        p = [{'name': 'LG 그램 Pro', 'model': '16Z90U-KU7WK', 'site': 'LG', 'price_krw': 3383400, 'ram_gb': 32, 'in_stock': True}]
        self.assertEqual(len(watchlist.due(g, p, {}, ['LG'], now=now)), 1)
        st = {'a': {'last_observation': {'site': 'LG', 'cpu': 'X7', 'observed_at': (now - timedelta(hours=1)).isoformat()}},
              'b': {'last_observation': {'site': 'LG', 'cpu': 'X7', 'observed_at': (now - timedelta(days=5)).isoformat()}},
              'c': {'last_observation': {'site': 'LG', 'cpu': 'X7', 'in_stock': False, 'observed_at': now.isoformat()}}}
        self.assertEqual(len(watchlist.fresh_official(st, now)), 1)

    def test_official_summary(self):
        now = datetime(2026, 10, 29, 4, tzinfo=timezone.utc)
        g = [{'id': 'gram', 'label': 'g', 'name_pattern': '16Z90U-?KU7', 'min_ram': 32}]
        p = [{'name': 'LG 그램 Pro AI 2026', 'model': '16Z90U-KU7BK', 'site': 'LG', 'price_krw': 3510000,
              'advertised_max_benefit_unverified': 3264300, 'ram_gb': 32, 'in_stock': True},
             {'name': '다나와 16Z90U-KU7BK', 'site': '다나와', 'price_krw': 3369860, 'ram_gb': 32}]
        key, msg = watchlist.official_coupon_alert(g, p, EV, ['LG'], now=now)
        self.assertIn('3,240,000원', msg)
        self.assertIn('2,994,300원', msg)
        self.assertNotIn('다나와', msg)
        self.assertIsNone(watchlist.official_coupon_alert(g, p, EV, ['LG'], now=datetime(2026, 12, 2, tzinfo=timezone.utc)))


if __name__ == '__main__':
    unittest.main()
