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


if __name__ == '__main__':
    unittest.main()
