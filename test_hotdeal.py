import unittest

import hotdeal

RSS = '''<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
<item><title>[네이버] ASUS TUF A14 RTX4060 32GB 공식인증점 (2,290,000원/무료)</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=1</link><pubDate>Mon, 26 Oct 2026 15:16:36 GMT</pubDate></item>
<item><title>[쿠팡] 노트북 파우치 15인치 (9,900원)</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=2</link></item>
<item><title>[G마켓] 델 XPS 14 병행수입 (1,890,000원)</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=ppomppu&amp;no=3</link></item>
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
        legion = next(d for d in deals if 'XPS' in d['title'])
        self.assertIn('병행', legion['as_line'])
        book = next(d for d in deals if '갤럭시북' in d['title'])
        self.assertEqual(book['price_krw'], 1790000)
        self.assertIn('국내 A/S', book['as_line'])
        self.assertEqual(hotdeal.new_laptop_deals(items, seen), [])

    def test_no_false_gram(self):
        self.assertFalse(hotdeal.is_laptop('[인스탁스샵] 인스타그램 팔로우 이벤트'))
        self.assertFalse(hotdeal.is_laptop('[스팀] 프로그램 할인'))
        self.assertTrue(hotdeal.is_laptop('[네이버] LG그램 프로 17Z90TR'))

    def test_major_brands_only(self):
        for title in ['[11번가] 한성컴퓨터 TFG5076XG 32GB', '[쿠팡] 15.6인치 RTX4050 게이밍 32GB (1,190,000원)',
                      '[G마켓] 레드미북 프로 16', '[네이버] 게이밍 노트북 특가']:
            self.assertFalse(hotdeal.is_laptop(title), title)
        for title in ['[네이버] LG그램 프로 16', '[쿠팡] 삼성 갤럭시북5 프로', '[G마켓] MSI 크리에이터 M14', '[11번가] HP 오멘 16']:
            self.assertTrue(hotdeal.is_laptop(title), title)

    def test_lenovo_needs_genuine(self):
        b = hotdeal.DEFAULT_BRANDS + ('레노버',)
        g = ('레노버',)
        self.assertFalse(hotdeal.is_laptop('[네이버] 레노버 리전 5 노트북', b, g))
        self.assertTrue(hotdeal.is_laptop('[네이버] 레노버 리전 5 국내정품 노트북', b, g))
        self.assertTrue(hotdeal.is_laptop('[11번가] 레노버 요가 프로 7i 83E2002GKR', b, g))
        self.assertFalse(hotdeal.is_laptop('[G마켓] 레노버 리전 5 정품 병행수입', b, g))
        self.assertFalse(hotdeal.is_laptop('[G마켓] 레노버 리전 5', hotdeal.DEFAULT_BRANDS))

    def test_message(self):
        d = hotdeal.new_laptop_deals(hotdeal.parse_rss(RSS, '뽐뿌'), [])[0]
        m = hotdeal.message(d)
        self.assertIn('공식 A/S', m)
        self.assertIn('판매처: 네이버', m)


    def test_return_deal_with_reference(self):
        ref = hotdeal.build_reference([
            {'model': 'LG전자 2026 그램 프로16 16ZD90U-GX59K WIN11', 'name': 'LG 그램 프로16 16ZD90U-GX59K', 'price_krw': 2612370},
            {'model': '삼성전자 갤럭시북6 프로 NT940XJG-K71A', 'name': '갤럭시북6 프로 NT940XJG-K71A', 'price_krw': 2900000}])
        items = hotdeal.parse_rss('''<rss><channel>
<item><title>[쿠팡] 반품마켓 LG 그램 프로16 16ZD90U-GX59K 최상 (1,990,000원)</title><link>https://a/1</link></item>
<item><title>[네이버] 갤럭시북6 프로 NT940XJG-K72A (3,040,000원)</title><link>https://a/2</link></item>
</channel></rss>''', '뽐뿌')
        deals = hotdeal.new_laptop_deals(items, [], reference=ref)
        self.assertTrue(deals[0]['is_return'])
        self.assertEqual(deals[0]['reference']['match'], '같은 모델')
        m = hotdeal.message(deals[0])
        self.assertTrue(m.startswith('[반품 노트북]'))
        self.assertIn('622,370원(23.8%) 낮음', m)
        self.assertIn('반품 상품', m)
        book = deals[1]
        self.assertFalse(book['is_return'])
        self.assertEqual(book['reference']['match'], '같은 시리즈(옵션 다를 수 있음)')
        self.assertNotIn('낮음', hotdeal.message(book))

    def test_model_codes_ignore_gpu_and_sizes(self):
        self.assertEqual(hotdeal.model_codes('ASUS TUF A14 RTX4060 32GB 1TB'), [])
        self.assertIn('83E2002GKR', hotdeal.model_codes('레노버 요가 83E2002GKR'))


    def test_body_specs(self):
        page = ('<div class="sidebar">RTX 4090 64GB 다른 딜</div><div class="view_content autolink">'
                '<p>갤럭시북6 프로 (NT940XJG-K72A)</p><p>GPU : 인텔 Arc B390</p><p>RAM : LPDDR5X 32GB</p>'
                '<p>SSD 512GB 무게 약 1.24kg</p></div><div class="comment_wrapper">RTX 5090 128GB</div>')
        self.assertEqual(hotdeal.extract_specs(hotdeal.body_text(page)),
                         {'ram_gb': 32, 'gpu': 'Arc B390', 'weight_kg': 1.24, 'model': 'NT940XJG-K72A'})
        items = [{'feed': '루리웹', 'id': 'b1', 'title': '[네이버] 갤럭시북6 프로 쿠폰 (304만)', 'link': 'https://a/b1'}]
        d = hotdeal.new_laptop_deals(items, [], fetch_body=lambda u: page)[0]
        self.assertEqual(set(d['fit']), {'32GB+', '외장/고성능 GPU'})
        self.assertIn('본문 사양: RAM 32GB · Arc B390 · 1.24kg', hotdeal.message(d))
        bad = hotdeal.new_laptop_deals([{**items[0], 'id': 'b2'}], [], fetch_body=lambda u: 1 / 0)[0]
        self.assertIn('조건 정보 부족(제목 기준)', hotdeal.message(bad))


if __name__ == '__main__':
    unittest.main()
