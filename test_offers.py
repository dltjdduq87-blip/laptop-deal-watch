import json
import unittest

import offers as O

LD = ('<script type="application/ld+json">{"@type":"Product","name":"삼성전자 갤럭시북5 프로 NT960XHA-K52A (SSD 256GB)",'
      '"description":"AI노트북 / 16인치 / 1.56kg / [구성] / 32GB / 용량: 256GB","offers":{"@type":"AggregateOffer","offerCount":"60","lowPrice":"2688980"}}</script>')

DANAWA = LD + '''<div id="lowPriceCompanyArea"><ul class="list__mall-price">
<li class="list-item"><div class="box__logo"><img alt="원더풀" class="image"></div>
 <div class="box__price lowest"><span class="badge__lowest">최저가</span><div class="sell-price" data-base-price="2688980" data-delivery-price="0"><span class="text__num">2,688,980</span></div></div>
 <div class="box__delivery">무료배송</div>
 <a class="link__full-cover" href="https://prod.danawa.com/bridge/loadingBridge.html?pcode=73691981&cmpnyc=PY905&link_pcode=73691981"></a></li>
<li class="list-item"><div class="box__logo"><img alt="11번가"></div>
 <div class="box__price"><div class="sell-price"><span class="text__num">2,798,880</span></div></div>
 <div class="box__delivery"><div class="layer-prod-pdb1">빠른배송 안내</div>배송비 3,000원</div>
 <a class="link__full-cover" href="https://prod.danawa.com/bridge/loadingBridge.html?cmpnyc=TH201&link_pcode=7915013234"></a></li>
<li class="list-item"><div class="box__logo"><span aria-label="옐로우트리" class="text__logo">옐로우트리</span><span class="icon__npay"><span class="blind">네이버페이</span></span></div>
 <div class="box__price"><div class="sell-price"><span class="text__num">2,799,000</span></div></div><div class="box__delivery">무료배송</div></li>
<li class="list-item"><div class="box__logo"><img alt="착한컴"></div>
 <div class="box__price"><span class="badge__cash">현금</span><div class="sell-price"><span class="text__num">2,340,000</span></div></div><div class="box__delivery">무료배송</div></li>
</ul></div>'''


def enuri_page(rows):
    state = json.dumps({'state': {'data': {'total': 173, 'data': {'priceList': rows}}}}, ensure_ascii=False)
    header = json.dumps({'priceList': [{'shopName': '롯데홈쇼핑', 'price': 3305870, 'type': 'cardLowest'}]}, ensure_ascii=False)
    push = lambda s: '<script>self.__next_f.push([1,' + json.dumps(s, ensure_ascii=False) + '])</script>'
    return LD.replace('1.56kg', '1.19kg') + push(header[:-1] + ',') + push(state[:40]) + push(state[40:] + '}')


ENURI_ROWS = [
    {'plno': 1, 'price': 3383710, 'productName': '그램 프로', 'shopCode': 4027, 'shopName': '옥션', 'deliveryPrice': 0,
     'deliveryText': '무료배송', 'isAd': False, 'isOverseas': False, 'rewardInfo': {'type': 'emoney', 'amount': 27060}},
    {'plno': 2, 'price': 3383710, 'productName': '그램 프로', 'shopCode': 536, 'shopName': 'G마켓', 'deliveryPrice': 0,
     'cardPrice': 3382210, 'cardName': '하나카드', 'cardInfo': [{'price': 3382210, 'name': '하나카드'}], 'isAd': False, 'isOverseas': False},
    {'plno': 3, 'price': 3000000, 'productName': '그램 프로', 'shopCode': 9, 'shopName': '해외구매몰', 'deliveryPrice': 0, 'isAd': False, 'isOverseas': True},
    {'plno': 4, 'price': 3100000, 'productName': '그램 프로', 'shopCode': 6665, 'shopName': 'SSG.COM', 'deliveryPrice': 2500, 'isAd': True, 'isOverseas': False},
]


class DanawaTest(unittest.TestCase):
    def setUp(self):
        self.meta, self.offers = O.parse_danawa_offers(DANAWA, 'https://prod.danawa.com/info/?pcode=73691981')

    def test_rows_and_meta(self):
        self.assertEqual(self.meta['ram_gb'], 32)
        self.assertEqual(self.meta['weight_kg'], 1.56)
        self.assertEqual(self.meta['offer_count'], 60)
        self.assertEqual([o['seller_name'] for o in self.offers], ['원더풀', '11번가', '옐로우트리', '착한컴'])

    def test_shipping_and_mapping(self):
        by = {o['seller_name']: o for o in self.offers}
        self.assertEqual(by['11번가']['target_shop'], '11번가')
        self.assertEqual(by['11번가']['shipping_krw'], 3000)
        self.assertEqual(by['11번가']['seller_code'], 'TH201')
        self.assertEqual(by['원더풀']['shipping_krw'], 0)
        self.assertIsNone(by['원더풀']['target_shop'])

    def test_naver_pay_icon_is_not_naver_shopping(self):
        o = [x for x in self.offers if x['seller_name'] == '옐로우트리'][0]
        self.assertTrue(o['naver_pay_badge'])
        self.assertIsNone(o['target_shop'])

    def test_cash_price_is_not_baseline(self):
        cash = [x for x in self.offers if x['seller_name'] == '착한컴'][0]
        self.assertTrue(cash['price_condition'].startswith('현금가'))
        self.assertEqual(O.baseline_offer(self.offers)['price_krw'], 2688980)

    def test_never_claims_verification(self):
        for o in self.offers:
            self.assertEqual(o['evidence_type'], 'indirect_comparison_site')
            self.assertFalse(o['shop_login_verified'] or o['coupon_verified'] or o['stock_verified'])
            self.assertIsNone(o['checkout_verified_krw'])


class EnuriTest(unittest.TestCase):
    def setUp(self):
        self.meta, self.offers = O.parse_enuri_offers(enuri_page(ENURI_ROWS), 'https://price.enuri.com/catalog/141368574')

    def test_reads_seller_table_not_header_widget(self):
        self.assertEqual(len(self.offers), 4)
        self.assertNotIn('롯데홈쇼핑', [o['seller_name'] for o in self.offers])
        self.assertEqual(self.meta['weight_kg'], 1.19)

    def test_card_price_is_conditional_and_hana_is_check_only(self):
        g = [o for o in self.offers if o['seller_name'] == 'G마켓'][0]
        self.assertEqual(g['price_krw'], 3383710)
        self.assertEqual(g['conditional_prices'][0]['price_krw'], 3382210)
        self.assertIn('체크카드뿐', g['conditional_prices'][0]['buyer_applicability'])

    def test_reward_kept_separate(self):
        a = [o for o in self.offers if o['seller_name'] == '옥션'][0]
        self.assertEqual(a['reward_separate']['amount'], 27060)
        self.assertEqual(a['price_krw'], 3383710)

    def test_baseline_skips_ads_and_overseas(self):
        self.assertEqual(O.baseline_offer(self.offers)['price_krw'], 3383710)
        self.assertEqual([o['target_shop'] for o in self.offers if o['seller_name'] == 'SSG.COM'], ['SSG'])


class HelpersTest(unittest.TestCase):
    def test_card_applicability(self):
        self.assertIn('KB국민/우리', O.card_applicability('롯데/신한/우리/현대/KB카드'))
        self.assertEqual(O.card_applicability('신한카드'), '보유 결제수단 아님')
        self.assertIn('간편결제', O.card_applicability('네이버페이'))

    def test_detail_url(self):
        self.assertEqual(O.detail_url({'site': '에누리', 'url': 'https://www.enuri.com/detail.jsp?modelno=141368574'}),
                         'https://price.enuri.com/catalog/141368574')
        self.assertEqual(O.detail_url({'site': '다나와', 'url': 'https://prod.danawa.com/info/?pcode=73691981&cate=112758'}),
                         'https://prod.danawa.com/info/?pcode=73691981&cate=112758')
        self.assertIsNone(O.detail_url({'site': '다나와', 'url': 'https://prod.danawa.com/info/ajax/?pcode=1'}))
        self.assertIsNone(O.detail_url({'site': 'G마켓', 'url': 'https://item.gmarket.co.kr/x'}))

    def test_selection_bounds_and_spec_filter(self):
        rows = [{'site': '에누리', 'source_id': str(i), 'price_krw': 1600000 + i, 'ram_gb': None, 'weight_kg': None,
                 'url': 'https://www.enuri.com/detail.jsp?modelno=' + str(100 + i)} for i in range(12)]
        rows.append({'site': '다나와', 'source_id': 'x', 'price_krw': 2000000, 'ram_gb': 16, 'weight_kg': 1.2,
                     'url': 'https://prod.danawa.com/info/?pcode=5'})
        rows.append({'site': '에누리', 'source_id': 'y', 'price_krw': 900000, 'url': 'https://www.enuri.com/detail.jsp?modelno=7'})
        picked = O.select_details(rows, limit_per_site=8)
        self.assertEqual(len(picked), 8)
        self.assertTrue(all(p['site'] == '에누리' and p['price_krw'] >= 1500000 for p, _ in picked))

    def test_collect_and_enrich(self):
        market = [{'site': '에누리', 'source_id': 'e1', 'price_krw': 2900000, 'ram_gb': None, 'weight_kg': None,
                   'url': 'https://www.enuri.com/detail.jsp?modelno=141368574'},
                  {'site': '다나와', 'source_id': 'd1', 'price_krw': 2688980, 'ram_gb': 32, 'weight_kg': 1.56,
                   'url': 'https://prod.danawa.com/info/?pcode=73691981'}]
        pages = {'https://price.enuri.com/catalog/141368574': enuri_page(ENURI_ROWS)}

        def fetch(url):
            if url in pages:
                return pages[url]
            raise ValueError('HTTP_403')
        details, offers, errors = O.collect_offers(market, fetch, sleep=lambda s: None)
        self.assertEqual(len(details), 1)
        self.assertEqual(errors[0]['code'], 'HTTP_403')
        O.enrich_specs(market, details)
        self.assertEqual((market[0]['ram_gb'], market[0]['weight_kg']), (32, 1.19))
        self.assertEqual(market[0]['spec_source_url'], 'https://price.enuri.com/catalog/141368574')
        summary = {r['site']: r for r in O.shop_summary(offers, [{'site': '옥션', 'status': 'blocked', 'products': 0}])}
        self.assertEqual(summary['옥션']['direct_status'], 'blocked')
        self.assertEqual(summary['옥션']['indirect_offers'], 1)
        self.assertFalse(summary['옥션']['member_benefit_verified'])


class SpecCacheTest(unittest.TestCase):
    def test_known_16gb_models_are_skipped_next_run(self):
        cache = {}
        O.update_spec_cache(cache, [{'detail_url': 'https://price.enuri.com/catalog/1', 'detail_ram_gb': 16, 'detail_weight_kg': 1.29}])
        rows = [{'site': '에누리', 'source_id': 'a', 'price_krw': 1600000, 'ram_gb': None, 'weight_kg': None,
                 'url': 'https://www.enuri.com/detail.jsp?modelno=1'},
                {'site': '에누리', 'source_id': 'b', 'price_krw': 1700000, 'ram_gb': None, 'weight_kg': None,
                 'url': 'https://www.enuri.com/detail.jsp?modelno=2'}]
        O.apply_spec_cache(rows, cache)
        self.assertEqual(rows[0]['ram_gb'], 16)
        self.assertEqual([p['source_id'] for p, _ in O.select_details(rows)], ['b'])

    def test_cache_is_bounded(self):
        cache = {str(i): {'ram_gb': 16, 'observed_at': '2026-01-%02d' % (i + 1)} for i in range(5)}
        O.update_spec_cache(cache, [], keep=3)
        self.assertEqual(sorted(cache), ['2', '3', '4'])


class BuyerEstimateTest(unittest.TestCase):
    def offer(self, seller, price, cards=(), shipping=0, condition='일반 판매가', **kw):
        return O.offer_record('에누리', 'u', seller=seller, price=price, catalog_name='c', shipping_krw=shipping,
                              price_condition=condition, conditional_prices=[
                                  {'label': l, 'price_krw': p, 'buyer_applicability': O.card_applicability(l)} for l, p in cards], **kw)

    def test_matching_credit_card_price_lowers_estimate(self):
        est = O.buyer_estimate([self.offer('옥션', 3000000), self.offer('G마켓', 3010000, cards=[('KB국민카드', 2900000)])])
        self.assertEqual(est['estimated_krw'], 2900000)
        self.assertEqual(est['basis'], '보유 결제수단 조건가')
        self.assertIn('KB국민', est['condition'])
        self.assertEqual(est['base_krw'], 3000000)
        self.assertFalse(est['verified'])

    def test_hana_check_card_and_cash_are_not_used(self):
        est = O.buyer_estimate([self.offer('옥션', 3000000), self.offer('G마켓', 3000000, cards=[('하나카드', 2800000)]),
                                self.offer('착한컴', 2500000, condition='현금가 (결제수단 조건부)')])
        self.assertEqual(est['estimated_krw'], 3000000)
        self.assertEqual(est['basis'], '공개 최저 판매가')

    def test_shipping_added_and_ads_ignored(self):
        est = O.buyer_estimate([self.offer('A', 2000000, shipping=5000), self.offer('B', 1000000, cards=[('우리카드', 900000)], is_ad=True)])
        self.assertEqual(est['estimated_krw'], 2005000)

    def test_effective_price(self):
        self.assertEqual(O.effective_price({'price_krw': 3100000, 'buyer_estimate': {'estimated_krw': 2950000}}), 2950000)
        self.assertEqual(O.effective_price({'price_krw': 3100000}), 3100000)


class CandidateAlertTest(unittest.TestCase):
    def run_watch(self, market, state):
        import os, sys, tempfile
        from pathlib import Path
        from unittest.mock import patch
        import watch
        config = {'scope': 'x', 'sources': [], 'unsupported': [], 'catalogs': [], 'catalog_review_notifications': True,
                  'top_per_band': 3, 'max_alerts_per_run': 3}
        sent, previous = [], os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                Path('config.json').write_text(json.dumps(config)); Path('state.json').write_text(json.dumps(state))
                with patch.object(sys, 'argv', ['watch.py']), patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': ''}), \
                        patch('catalog.scan', return_value=([], market)), patch('offers.collect_offers', return_value=([], [], [])), \
                        patch('watch.telegram', side_effect=lambda t: sent.append(t) or True), patch('watch.email', return_value=False):
                    watch.main()
                self.sent_all = sent
                return [t for t in sent if '노트북 후보 알림' in t and '조건 충족 최저가' not in t], json.loads(Path('state.json').read_text()), \
                    json.loads(Path('report.json').read_text())
            finally:
                os.chdir(previous)

    def item(self, name, price, option='SSD 512GB'):
        return {'site': '에누리', 'source_id': name + option, 'model_key': name, 'name': name + ' / ' + option,
                'price_krw': price, 'ram_gb': 32, 'weight_kg': 1.2, 'url': 'https://price.enuri.com/catalog/1',
                'gpu': '외장그래픽 RTX4060 VRAM: 8GB'}

    def test_top_per_band_new_or_cheaper_only_and_capped(self):
        market = [self.item('노트북 %d' % i, 2000000 + i * 10000) for i in range(5)]
        market.append(self.item('노트북 0', 2100000, 'SSD 1TB'))  # another option of the same model
        market += [self.item('고가 %d' % i, 2400000 + i * 10000) for i in range(3)]
        state = {'products': {}, 'sent': {}, 'top_alerts': {'노트북 0': 2000000, '노트북 1': 2050000}, 'top_key_version': 2}
        alerts, saved, report = self.run_watch(market, state)
        self.assertEqual(len(alerts), 3)
        joined = '\n'.join(alerts)
        self.assertIn('노트북 1', joined); self.assertIn('노트북 2', joined); self.assertIn('고가 0', joined)
        self.assertNotIn('노트북 0', joined); self.assertNotIn('노트북 3', joined)
        self.assertIn('190~230만원 2위', joined)
        top = report['top_by_band']['190~230만원']
        self.assertEqual([p['model_key'] for p in top], ['노트북 0', '노트북 1', '노트북 2'])
        self.assertEqual(top[0]['options_seen'], 2)
        self.assertEqual(saved['top_alerts']['노트북 1'], 2010000)

    def test_same_performance_variants_merge_and_drop_shows_diff(self):
        base = dict(site='에누리', ram_gb=32, weight_kg=1.2, url='u', cpu='인텔 코어 울트라7(S3) 356H (4.7GHz)',
                    gpu='외장그래픽 RTX4060 VRAM: 8GB')
        market = [dict(base, source_id='a', model_key='LG전자 2026 그램16 16Z90U-AAA', name='LG전자 2026 그램16 16Z90U-AAA / SSD 512GB', price_krw=2200000),
                  dict(base, source_id='b', model_key='LG전자 2026 그램16 16Z90U-AAA WIN11', name='LG전자 2026 그램16 16Z90U-AAA WIN11 / SSD 1TB', price_krw=2000000)]
        key = 'LG전자 | 인텔 코어 울트라7(S3) 356H | 외장그래픽 RTX4060 VRAM: 8GB | 32'.upper()
        state = {'products': {}, 'sent': {}, 'top_key_version': 2, 'top_alerts': {key: 2100000},
                 'top_alert_names': {key: 'LG전자 2026 그램16 16Z90U-AAA / SSD 512GB'}}
        alerts, saved, _ = self.run_watch(market, state)
        self.assertEqual(len(alerts), 1)
        self.assertIn('이전가 2,100,000원 → 현재가 2,000,000원', alerts[0])
        self.assertIn('▼ 100,000원 (4.8% 할인)', alerts[0])
        self.assertIn('같은 성능 다른 구성', alerts[0])
        self.assertEqual(saved['top_alerts'][key], 2000000)

    def test_key_upgrade_is_silent_and_old_models_excluded(self):
        old = self.item('LG전자 2023 그램16 16ZD90R-EX7VK', 2100000); old['cpu'] = '인텔 코어i7-13세대 i7-1360P (2.2GHz)'
        new = self.item('신형 노트북', 2200000)
        alerts, saved, report = self.run_watch([old, new], {'products': {}, 'sent': {}, 'top_alerts': {'구 키': 1}})
        self.assertEqual(alerts, [])
        self.assertEqual(saved['top_key_version'], 2)
        self.assertNotIn('구 키', saved['top_alerts'])
        self.assertEqual([p['name'] for p in report['too_old_excluded']], [old['name']])

    def test_overall_cheapest_alert_with_drop(self):
        market = [self.item('A 노트북', 2500000), self.item('B 노트북', 1800000)]
        state = {'products': {}, 'sent': {}, 'top_key_version': 2, 'top_alerts': {'A 노트북': 2500000, 'B 노트북': 1800000},
                 'cheapest_alert': {'price': 1900000, 'name': 'B 노트북 / SSD 1TB', 'perf_key': 'B 노트북'}}
        alerts, saved, report = self.run_watch(market, state)
        self.assertEqual(saved['cheapest_alert']['price'], 1800000)
        msg = [t for t in self.sent_all if '조건 충족 최저가 갱신' in t][0]
        self.assertIn('이전가 1,900,000원 → 현재가 1,800,000원', msg)
        self.assertIn('▼ 100,000원 (5.3% 할인)', msg)
        self.assertEqual(report['cheapest_qualifying']['name'], 'B 노트북 / SSD 512GB')

    def test_no_alerts_until_first_full_sweep(self):
        import os, sys, tempfile
        from pathlib import Path
        from unittest.mock import patch
        import watch
        config = {'scope': 'x', 'sources': [], 'unsupported': [], 'catalog_review_notifications': True,
                  'catalogs': [{'site': '에누리', 'adapter': 'enuri_sweep'}], 'enuri_sweep': {'spec_codes': ['1']}}
        sent, previous = [], os.getcwd()
        row = {'site': '에누리', 'status': 'collected', 'products': 1, 'method': 'x', 'models_in_filter': 9}
        with tempfile.TemporaryDirectory() as d:
            try:
                os.chdir(d)
                Path('config.json').write_text(json.dumps(config))
                with patch.object(sys, 'argv', ['watch.py']), patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': ''}), \
                        patch('catalog.scan', return_value=([], [])), patch('sweep.sweep', return_value=(row, [self.item('A', 2000000)])), \
                        patch('offers.collect_offers', return_value=([], [], [])), \
                        patch('watch.telegram', side_effect=lambda t: sent.append(t) or True), patch('watch.email', return_value=False):
                    watch.main()
            finally:
                os.chdir(previous)
        self.assertFalse([t for t in sent if '노트북 후보 알림' in t])

    def test_list_card_price_feeds_estimate(self):
        p = self.item('카드모델', 2300000)
        p['list_card_prices'] = [{'label': 'KB국민카드', 'price_krw': 2250000}]
        alerts, _, report = self.run_watch([p], {'products': {}, 'sent': {}})
        self.assertEqual(report['top_by_band']['190~230만원'][0]['effective_price_krw'], 2250000)
        self.assertIn('KB국민', alerts[0])


if __name__ == '__main__':
    unittest.main()
