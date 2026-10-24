import json
import unittest
from datetime import datetime, timezone, timedelta

import sweep as S

CFG = {'spec_codes': ['5696', '235'], 'start_price': 1500000, 'end_price': 3000000, 'pages_per_run': 2, 'delay': 0,
       'max_age_hours': 24}


def item(model_id, name, price, weight='1.12kg', ram='32GB', cards=None, sold_out=False, option='SSD 1TB'):
    return {'id': str(model_id), 'name': name, 'condiName': option, 'priceInfo': {'price': price}, 'mallCount': 5,
            'isSoldOut': sold_out, 'isRental': False, 'cardPriceInfo': cards,
            'specs': [{'values': [{'raw': '35.5cm(14인치)'}]}, {'values': [{'raw': weight}]},
                      {'values': [{'raw': '윈도우11홈'}]},
                      {'groupName': 'CPU', 'values': [{'values': [{'raw': '인텔'}]}, {'values': [{'raw': '코어 울트라5'}]}]},
                      {'groupName': '그래픽', 'values': [{'values': [{'raw': '내장그래픽'}]}]},
                      {'groupName': '구성', 'values': [{'values': [{'raw': ram}]}, {'values': [{'raw': '1TB'}]}]}]}


def page(items, current=1, total_pages=3):
    data = {'initProductList': {'listCount': {'catalog': 99}, 'totalPages': total_pages, 'currentPage': current, 'items': items}}
    body = json.dumps(data, ensure_ascii=False)
    push = lambda s: '<script>self.__next_f.push([1,' + json.dumps(s, ensure_ascii=False) + '])</script>'
    return push(body[:30]) + push(body[30:])


class SweepTest(unittest.TestCase):
    def test_filter_url_keeps_robots_allowed_list_path(self):
        url = S.filter_url(CFG, 2)
        self.assertTrue(url.startswith('https://price.enuri.com/list?'))
        self.assertIn('spec=5696,235', url)
        self.assertIn('startPrice=1500000', url)
        self.assertIn('activeOption=excludeUsedAndRental', url)
        self.assertIn('page=2', url)
        self.assertNotIn('/api/', url)

    def test_item_record_specs_and_cards(self):
        r = S.item_record(item(7, 'ASUS 젠북 14', 2100000, cards=[{'cardName': 'KB국민카드', 'cardPrice': 2050000}]), 't')
        self.assertEqual((r['ram_gb'], r['weight_kg']), (32, 1.12))
        self.assertEqual(r['cpu'], '인텔 코어 울트라5')
        self.assertEqual(r['os'], '윈도우11홈')
        self.assertEqual(r['url'], 'https://price.enuri.com/catalog/7')
        self.assertEqual(r['model_key'], 'ASUS 젠북 14')
        self.assertEqual(r['list_card_prices'], [{'label': 'KB국민카드', 'price_krw': 2050000}])
        self.assertIsNone(r['checkout_verified_krw'])

    def test_vram_or_ssd_never_used_as_ram(self):
        it = item(8, 'X', 2000000)
        it['specs'][-1]['values'] = [{'values': [{'raw': '1TB'}]}]
        self.assertIsNone(S.item_record(it, 't')['ram_gb'])

    def test_rotation_cache_and_expiry(self):
        pages = {1: page([item(1, 'A', 2000000)], 1), 2: page([item(2, 'B', 2100000)], 2), 3: page([item(3, 'C', 2200000)], 3)}

        def fetch(url):
            n = int(url.split('page=')[1]) if 'page=' in url else 1
            return pages[n]
        state = {}
        now = datetime(2026, 10, 25, tzinfo=timezone.utc)
        row, products = S.sweep(fetch, state, CFG, now=now, sleep=lambda s: None)
        self.assertEqual(row['pages_read'], [1, 2])
        self.assertEqual(sorted(p['model'] for p in products), ['A', 'B'])
        row, products = S.sweep(fetch, state, CFG, now=now + timedelta(minutes=5), sleep=lambda s: None)
        self.assertEqual(row['pages_read'], [3, 1])
        self.assertEqual(sorted(p['model'] for p in products), ['A', 'B', 'C'])
        self.assertEqual(state['enuri_sweep']['sweeps_completed'], 1)
        later = now + timedelta(hours=25)
        row, products = S.sweep(fetch, state, CFG, now=later, sleep=lambda s: None)
        self.assertEqual(row['pages_read'], [2, 3])
        self.assertEqual(sorted(p['model'] for p in products), ['B', 'C'])  # A expired, not re-seen

    def test_failure_uses_cache_then_reports_error(self):
        state = {}
        S.sweep(lambda u: page([item(1, 'A', 2000000)], 1, 1), state, CFG, sleep=lambda s: None)

        def blocked(url):
            raise ValueError('HTTP_403')
        row, products = S.sweep(blocked, state, CFG, sleep=lambda s: None)
        self.assertEqual(row['status'], 'collected')
        self.assertIn('이전 관측', row['note'])
        row, products = S.sweep(blocked, {}, CFG, sleep=lambda s: None)
        self.assertEqual((row['status'], row['code']), ('blocked', 'HTTP_403'))
        self.assertEqual(products, [])


if __name__ == '__main__':
    unittest.main()
