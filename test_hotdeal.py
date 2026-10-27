import unittest

import hotdeal

RSS = '''<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
<item><title>[네이버] ASUS TUF A14 RTX4060 32GB 공식인증점 (2,290,000원/무료)</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=1</link><pubDate>Mon, 26 Oct 2026 15:16:36 GMT</pubDate></item>
<item><title>[쿠팡] 노트북 파우치 15인치 (9,900원)</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=2</link></item>
<item><title>[G마켓] 레노버 리전 5 병행수입 (1,890,000원)</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=3</link></item>
<item><title>[네이버] 갤럭시북5 프로 16GB 179만원</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=4</link></item>
<item><title>[토스쇼핑] 나쵸 6입 (7,680원)</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=5</link></item>
</channel></rss>'''


class HotdealTest(unittest.TestCase):
    def test_parse_and_filter(self):
        items = hotdeal.parse_rss(RSS, '뽐뿌')
        self.assertEqual(len(items), 5)
        self.assertTrue(items[0]['link'].startswith('https://'))
        seen = []
        deals = hotdeal.new_laptop_deals(items, seen)
        titles = [d['title'] for d in deals]
        self.assertEqual(len(deals), 3)
        self.assertFalse(any('파우치' in t or '나쵸' in t for t in titles))
        self.assertIn('TUF', deals[0]['title'])
        self.assertEqual(set(deals[0]['fit']), {'32GB+', '외장/고성능 GPU', '예산 내'})
        self.assertTrue(deals[0]['official_seller'])
        legion = next(d for d in deals if '리전' in d['title'])
        self.assertIn('병행', legion['as_line'])
        book = next(d for d in deals if '갤럭시북' in d['title'])
        self.assertEqual(book['price_krw'], 1790000)
        self.assertIn('국내 A/S', book['as_line'])
        self.assertEqual(hotdeal.new_laptop_deals(items, seen), [])

    def test_no_false_gram(self):
        self.assertFalse(hotdeal.is_laptop('[인스탁스샵] 인스타그램 팔로우 이벤트'))
        self.assertFalse(hotdeal.is_laptop('[스팀] 프로그램 할인'))
        self.assertTrue(hotdeal.is_laptop('[네이버] LG그램 프로 17Z90TR'))

    def test_all_manufacturers(self):
        for title in ['[11번가] 한성컴퓨터 TFG5076XG 32GB', '[쿠팡] 15.6인치 RTX4050 게이밍 32GB (1,190,000원)',
                      '[G마켓] 레드미북 프로 16', '[네이버] 주연테크 리오나인 노트북']:
            self.assertTrue(hotdeal.is_laptop(title), title)
        d = hotdeal.analyze({'feed': 'x', 'id': '1', 'title': '[쿠팡] 15.6인치 RTX4050 32GB', 'link': 'l'})
        self.assertEqual(d['brand'], '미확인')
        self.assertIn('확인 필요', d['as_line'])

    def test_message(self):
        d = hotdeal.new_laptop_deals(hotdeal.parse_rss(RSS, '뽐뿌'), [])[0]
        m = hotdeal.message(d)
        self.assertIn('공식 A/S', m)
        self.assertIn('판매처: 네이버', m)


if __name__ == '__main__':
    unittest.main()
