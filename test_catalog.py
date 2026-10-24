import json
import unittest
from catalog import parse_catalog, review_candidate, specs, price_band, notebook_name, scan
from watch import parse_product, qualifies, validate_url

URL='https://prod.danawa.com/list/?cate=112758'
CARD='''<div data-testid="ProductListItem"><div data-testid="ProductListTitle"><a>삼성전자 갤럭시북5 NT960XHA-K52A</a></div><div data-testid="ProductListSpecs">노트북 / 1.56kg / [그래픽] Arc 130V / [구성] 32GB / 용량: 256GB</div><a aria-label="SSD 256GB 2,688,980원" href="https://prod.danawa.com/info/?pcode=1">가격</a><a aria-label="SSD 512GB 2,789,000원" href="https://prod.danawa.com/info/?pcode=2">가격</a></div>'''
VARIANT={'@type':'Product','sku':'NT960XJG-KC71S','name':'갤럭시 북6 프로|실버|Windows 11 Home|16GB|512GB|40.6 cm','offers':{'@type':'Offer','priceCurrency':'KRW','price':'3360000','availability':'https://schema.org/InStock','url':'https://www.samsung.com/sec/galaxybook/galaxy-book6-series/buy/?modelCode=NT960XJG-KC71S'}}

def page(value):return '<script type="application/ld+json">'+json.dumps(value)+'</script>'

class CatalogTests(unittest.TestCase):
 def test_exact_samsung_variant_group(self):
  raw=page({'@type':'ProductGroup','hasVariant':[VARIANT]})
  p=parse_product(raw,{'id':'s','site':'삼성','model':'NT960XJG-KC71S','url':'https://www.samsung.com/sec/galaxybook/galaxy-book6-series/buy/'})
  self.assertEqual(p['price_krw'],3360000);self.assertEqual(p['ram_gb'],16);self.assertFalse(qualifies(p))
 def test_samsung_variants_do_not_cross_match(self):
  raw=page({'@type':'ProductGroup','hasVariant':[VARIANT,{**VARIANT,'sku':'OTHER','name':VARIANT['name'].replace('16GB','32GB')}]})
  ps=parse_catalog(raw,'삼성','https://www.samsung.com/')
  self.assertEqual({p['model']:p['ram_gb'] for p in ps},{'NT960XJG-KC71S':16,'OTHER':32})
 def test_storage_options_have_own_price(self):
  ps=parse_catalog(CARD,'다나와',URL)
  self.assertEqual([p['price_krw'] for p in ps],[2688980,2789000]);self.assertNotEqual(ps[0]['source_id'],ps[1]['source_id'])
  self.assertTrue(review_candidate(ps[0]));self.assertIsNone(ps[0]['in_stock']);self.assertFalse(ps[0]['domestic_as_verified'])
 def test_ssd_is_not_ram(self):
  self.assertIsNone(specs('노트북 1.2kg SSD 32GB')['ram_gb'])
  self.assertEqual(specs('[그래픽] VRAM: 32GB / [구성] 16GB')['ram_gb'],16)
 def test_non_laptop_link_is_excluded(self):
  self.assertFalse(notebook_name('Kipnos 폴딩 대용량 리빙박스 수납장'))
  self.assertFalse(notebook_name('삼성 노트북용 메모리 DDR5-5600 32GB'))
 def test_missing_weight_is_review_failure(self):
  ps=parse_catalog(CARD.replace('1.56kg',''),'다나와',URL)
  self.assertFalse(review_candidate(ps[0]))
 def test_price_band_boundaries(self):
  self.assertEqual(price_band(1900000),'190~230만원');self.assertEqual(price_band(2300000),'230~300만원');self.assertEqual(price_band(3000001),'예산 밖')
 def test_blocked_site_cannot_be_collected(self):
  def blocked(url):raise ValueError('ROBOTS_DISALLOWED')
  rows,ps=scan({'catalogs':[{'site':'11번가','url':'https://www.11st.co.kr/products/1'}]},blocked)
  self.assertEqual(rows[0]['status'],'blocked');self.assertEqual(ps,[])
 def test_empty_catalog_is_not_healthy(self):
  rows,ps=scan({'catalogs':[{'site':'HP','url':'https://www.hp.com/kr-ko/shop/'}]},lambda u:'<p>홈</p>')
  self.assertEqual(rows[0]['status'],'no_parseable_products')
 def test_allowed_hosts_exact_match(self):
  validate_url('https://prod.danawa.com/list/?cate=112758')
  with self.assertRaises(ValueError):validate_url('https://prod.danawa.com.evil.test/')
  with self.assertRaises(ValueError):validate_url('https://127.0.0.1/')

class MoreCatalogTests(unittest.TestCase):
 def test_marketplace_uses_sale_price_not_advertised_coupon(self):
  value={'itemNo':'42','commonItemInfo':{'item':{'text':'갤럭시북 노트북 RAM 32GB','link':'https://item.gmarket.co.kr/Item?goodscode=42&tracking=secret'},'price':{'binPrice':'2,000,000','couponPrice':'1,500,000'}}}
  raw='<script id="__NEXT_DATA__" type="application/json">'+json.dumps(value)+'</script>'
  p=parse_catalog(raw,'G마켓','https://www.gmarket.co.kr/')[0]
  self.assertEqual(p['price_krw'],2000000);self.assertEqual(p['ram_gb'],32)
  self.assertNotIn('tracking',p['url']);self.assertIsNone(p['in_stock']);self.assertIsNone(p['checkout_verified_krw'])
 def test_aggregate_low_price_is_not_direct_stock(self):
  p={**VARIANT,'name':'LG 그램 노트북','offers':{'@type':'AggregateOffer','priceCurrency':'KRW','lowPrice':1800000,'availability':'https://schema.org/InStock'},'url':'https://m.enuri.com/m/vip.jsp?modelno=1'}
  found=parse_catalog(page({'@type':'ItemList','itemListElement':[{'@type':'ListItem','item':p}]}),'에누리','https://m.enuri.com/')[0]
  self.assertIsNone(found['in_stock']);self.assertIn('집계',found['price_type'])
 def test_redirect_checks_target_robots(self):
  from watch import SafeRedirect
  from unittest.mock import patch
  from urllib.request import Request
  with patch('watch.ensure_robot_access',side_effect=ValueError('ROBOTS_DISALLOWED')):
   with self.assertRaisesRegex(ValueError,'ROBOTS_DISALLOWED'):
    SafeRedirect().redirect_request(Request('https://www.enuri.com/'),None,302,'',{},'https://m.enuri.com/m/list.jsp?cate=0404')

if __name__=='__main__':unittest.main()
