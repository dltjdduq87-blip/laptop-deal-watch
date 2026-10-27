import unittest

import as_service
import watch


class AsServiceTest(unittest.TestCase):
    def test_brand(self):
        self.assertEqual(as_service.brand({'model_key': 'ASUS TUF GAMING A14 FA401UV-RG025'}), 'ASUS')
        self.assertEqual(as_service.brand({'name': '삼성전자 갤럭시북5 프로 NT940XHA'}), '삼성')
        self.assertEqual(as_service.brand({'name': 'LG전자 그램 프로 16Z90TP'}), 'LG')
        self.assertEqual(as_service.brand({'name': 'MSI 크리에이터 M14 A13VF'}), 'MSI')
        self.assertEqual(as_service.brand({'name': '레노버 리전 5'}), '레노버')

    def test_status(self):
        asus = {'name': 'ASUS TUF A14'}
        self.assertEqual(as_service.assess({'name': 'LG 그램'})['as_status'], '국내 제조사')
        self.assertEqual(as_service.assess(asus)['as_status'], '정품 미확인')
        self.assertEqual(as_service.assess(asus, [{'seller_name': 'G마켓', 'product_title': 'ASUS TUF A14 국내정품'}])['as_status'], '정품 표기 확인')
        self.assertEqual(as_service.assess({'name': 'ASUS TUF A14 병행수입'})['as_status'], '병행수입 의심')
        self.assertEqual(as_service.assess(asus, [{'seller_name': 'x', 'is_overseas': True}])['as_status'], '병행수입 의심')
        self.assertIsNone(as_service.assess({'name': '삼성 갤럭시북'})['as_checks'])
        self.assertTrue(as_service.assess(asus)['as_checks'])

    def test_policy_notes_in_message(self):
        a = as_service.assess({'name': 'ASUS TUF'}, policy={'ASUS': {'warranty': '본체 라벨 기간', 'note': '서울 센터'}})
        msg = as_service.message_lines(a)
        self.assertIn('본체 라벨 기간', msg)
        self.assertIn('미검증', msg)

    def test_ranking_excludes_parallel(self):
        base = {'ram_gb': 32, 'weight_kg': 1.4, 'price_band': '230~300만원', 'site': '에누리', 'url': 'u', 'gpu': 'RTX4060 VRAM: 8GB'}
        cands = [dict(base, name='ASUS 병행', model_key='ASUS 병행', effective_price_krw=2300000, price_krw=2300000),
                 dict(base, name='ASUS 정상', model_key='ASUS 정상', effective_price_krw=2400000, price_krw=2400000)]
        cands = [{**p, **as_service.assess(p)} for p in cands]
        top = watch.rank_by_band(cands, 3, 'A')['230~300만원']
        self.assertEqual([p['model_key'] for p in top], ['ASUS 정상'])


if __name__ == '__main__':
    unittest.main()
