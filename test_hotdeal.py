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


    def test_reviewer_regressions(self):
        for t in ['[네이버] 삼성 갤럭시북5 노트북 189만원 (무료배송/30일 무료반품)', '[11번가] HP 노트북 교환/반품 불가 특가',
                  '삼성 노트북 반품 후기']:
            self.assertFalse(hotdeal.is_return_deal(t), t)
        for t in ['[쿠팡] 반품 HP 옴니북 울트라 14 (최상) 259만', '[쿠팡] 반품마켓 LG 그램 프로', '[쿠팡] 갤럭시북6 프로 반품 (상) 240만']:
            self.assertTrue(hotdeal.is_return_deal(t), t)
        self.assertEqual(hotdeal.model_codes('i7-13620H LPDDR5X DDR5-5600 2560x1600 HP 14-ep1234TU'), ['14-EP1234TU'])
        ref = hotdeal.build_reference([{'model': 'HP 옴니북 울트라 14-kd0071TU', 'name': '옴니북', 'price_krw': 3290000}])
        self.assertIsNone(hotdeal.reference_for('HP 14-ep1234TU 69만원', ref))
        self.assertEqual(hotdeal.extract_specs('RTX 4060 VRAM 8GB')['ram_gb'], None)
        self.assertEqual(hotdeal.extract_specs('램 16GB (최대 메모리 32GB 업그레이드)')['ram_gb'], 16)
        self.assertEqual(hotdeal.extract_specs('LPDDR5X 메모리')['model'], None)
        self.assertEqual(hotdeal.prices_krw('ASUS TUF 1,890,000원 (쿠폰 30만원)'), [1890000])


    def test_second_review_regressions(self):
        for t in ['쿠팡 30일 반품마켓 그램', '[쿠팡] 11일 반품마켓 특가 그램', '무료 반품마켓 그램', 'LG 그램 노트북 쿠팡 반품 150만']:
            self.assertTrue(hotdeal.is_return_deal(t), t)
        self.assertEqual(hotdeal.prices_krw('[쿠팡] 그램 쿠폰 50만원 할인 249만원'), [2490000])
        for t, want in [('카드할인 249만원', 2490000), ('[11번가] LG 그램 16 추가할인 199만원', 1990000),
                        ('쿠폰할인 1,890,000원', 1890000), ('LG그램 (카드 249만원)', 2490000), ('(304만/무배)', 3040000),
                        ('갤럭시북 10만원 할인 289만', 2890000)]:
            self.assertEqual(min(hotdeal.prices_krw(t)), want, t)
        self.assertEqual(hotdeal.model_codes('RYZEN7-8845HS AI9-HX370 R9-HX370 GRAM16-ZD90'), [])
        for c in ['NT940XJG-K72A', '16ZD90U-GX59K', '83E2002GKR', '14-KD0071TU', '17Z90SP-ED7HK', 'FA401UV', 'UX8407AA-SN430W']:
            self.assertEqual(hotdeal.model_codes(c), [c], c)
        self.assertIsNone(hotdeal.extract_specs('그래픽 메모리 8GB')['ram_gb'])
        self.assertEqual(hotdeal.extract_specs('그래픽 메모리 8GB 램 16GB')['ram_gb'], 16)
        self.assertEqual(hotdeal.extract_specs('공유 메모리 16GB RAM 32GB')['ram_gb'], 32)
        self.assertEqual(hotdeal.extract_specs('LPDDR5X-8533 32GB')['ram_gb'], 32)
        self.assertEqual(hotdeal.extract_specs('✔ GPU : 인텔 Arc B390 그래픽 ✔ RAM : LPDDR5X 32GB')['ram_gb'], 32)


    def test_third_review_regressions(self):
        for t, want in [('30만원 카드할인 229만', 2290000), ('30만원 즉시 할인 229만', 2290000), ('할인 30만원 229만', 2290000),
                        ('할인 30만원 → 199만원', 1990000), ('ASUS 30만원 다운 229만', 2290000), ('신세계상품권 30만원 LG그램 249만', 2490000),
                        ('-30만 199만', 1990000), ('그램 199~229만', 1990000), ('289만→259만', 2590000), ('할인 249만원', 2490000)]:
            self.assertEqual(min(hotdeal.prices_krw(t)), want, t)
        for t in ['쿠팡 반품비 무료 LG 노트북', '[쿠팡] 쿠팡 반품 시 배송비 무료', '14일 무료반품 노트북', '30일 무료반품 노트북 LG그램',
                  '단순변심 반품 가능 그램']:
            self.assertFalse(hotdeal.is_return_deal(t), t)
        for t in ['[쿠팡] 그램 16 (반품-최상) 189만', '갤럭시북 반품 상태 최상 210만']:
            self.assertTrue(hotdeal.is_return_deal(t), t)
        self.assertEqual(hotdeal.model_codes('THUNDERBOLT4 OFFICE2024 GALAXYBOOK5 ZENBOOK14 ARC140V'), [])
        self.assertEqual(hotdeal.model_codes('에이서 SFG14-73-71ZX'), ['SFG14-73-71ZX'])
        self.assertEqual(hotdeal.extract_specs('RAM: 16GB x2 (32GB)')['ram_gb'], 32)
        self.assertEqual(hotdeal.extract_specs('램 16GBx2')['ram_gb'], 32)


if __name__ == '__main__':
    unittest.main()
