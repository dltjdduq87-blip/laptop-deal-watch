import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from watch import parse_product, qualifies, should_notify, score, CHANNELS, delivery_event, qualifies_candidate, candidate_price
from core import calculate, Quote, Coupon

PAGE='''<script type="application/ld+json">{"@type":"Product","name":"LG 그램","model":"16Z90TP-KD7WK","category":"노트북","offers":{"@type":"Offer","price":"2000000","priceCurrency":"KRW","availability":"https://schema.org/InStock"},"additionalProperty":[{"name":"무게 (g)","value":"약 1,199"},{"name":"CPU","value":"255H"}]}</script><div>메모리 용량 (GB) 32 메모리 종류 LPDDR5x 최대혜택가 1,500,000 원</div>'''
SOURCE={'id':'lg','site':'LG','url':'https://www.lge.co.kr/product/notebook/16z90tp-kd7wk','model':'16Z90TP-KD7WK'}
class WatchTests(unittest.TestCase):
 def test_exact_sku_specs_and_unverified_benefit(self):
  p=parse_product(PAGE,SOURCE);self.assertEqual(p['price_krw'],2000000);self.assertEqual(p['ram_gb'],32);self.assertEqual(p['weight_kg'],1.199);self.assertIsNone(p['checkout_verified_krw']);self.assertTrue(qualifies(p));self.assertEqual(len(p['payment_methods']),9)
 def test_other_model_cannot_match(self):
  with self.assertRaisesRegex(ValueError,'MODEL_MISMATCH'):parse_product(PAGE,{**SOURCE,'model':'OTHER'})
 def test_currency_no_guess(self):
  with self.assertRaisesRegex(ValueError,'NO_EXACT_OFFER'):parse_product(PAGE.replace('KRW','USD'),SOURCE)
 def test_missing_weight_fails_closed(self):
  p=parse_product(PAGE.replace('무게 (g)','unknown'),SOURCE);self.assertFalse(qualifies(p))
 def test_subscription_not_total_price(self):
  p=parse_product(PAGE.replace('2000000','99000'),SOURCE);self.assertFalse(qualifies(p))
 def test_stock_required(self):
  p=parse_product(PAGE.replace('InStock','OutOfStock'),SOURCE);self.assertFalse(qualifies(p))
 def test_duplicate_and_drop(self):
  p=parse_product(PAGE,SOURCE);self.assertTrue(should_notify(p,None));self.assertFalse(should_notify(p,{'last_notified_candidate_price':1500000}));self.assertTrue(should_notify(p,{'last_notified_candidate_price':1600000}));self.assertFalse(should_notify(p,{'last_notified_candidate_price':1400000}))
 def test_no_fabricated_performance_total(self):
  p=parse_product(PAGE,SOURCE);self.assertIsNone(score(p)['total']);self.assertIsNone(score(p)['ai_development']);self.assertIsNone(score(p)['gaming'])
 def test_unverified_discount_excluded(self):
  q=Quote(listed_price=2000000,coupon=Coupon(amount=500000,eligible=False),immediate_card_discount=100000,card_verified=False)
  self.assertEqual(calculate(q)['checkout_simulated'],2000000)
 def test_delivery_failed_does_not_mark_sent(self):
  state={}
  with patch('watch.telegram',return_value=False),patch('watch.email',return_value=False):self.assertFalse(delivery_event(state,'x','message'))
  self.assertNotIn('x',state.get('sent',{}))
 def test_delivery_tracks_channels_independently(self):
  state={}
  with patch('watch.telegram',return_value=True),patch('watch.email',return_value=False):self.assertTrue(delivery_event(state,'x','message'))
  self.assertEqual(state['sent']['x'],['telegram'])
 def test_advertised_max_keeps_above_budget_product(self):
  p=parse_product(PAGE,SOURCE);p['price_krw']=3140000;p['advertised_max_benefit_unverified']=2920200
  self.assertFalse(qualifies(p));self.assertTrue(qualifies_candidate(p));self.assertIsNone(p['checkout_verified_krw']);self.assertEqual(candidate_price(p),2920200)
 def test_unverified_max_does_not_bypass_specs(self):
  p=parse_product(PAGE,SOURCE);p['ram_gb']=16;self.assertFalse(qualifies_candidate(p))


class ImprovementsTests(unittest.TestCase):
 def test_coupon_whitespace_and_script_noise(self):
  from watch import coupon_evidence
  a=coupon_evidence('<p>선착순  쿠폰 10%</p><script>coupon_secret</script>')
  b=coupon_evidence('<p>선착순 쿠폰 10%</p>')
  self.assertEqual(a['fingerprint'],b['fingerprint'])
  self.assertFalse(a['stacking_verified']);self.assertEqual(a['eligibility'],'미확인')
 def test_coupon_change_and_removal(self):
  from watch import coupon_evidence
  self.assertNotEqual(coupon_evidence('<p>쿠폰 10%</p>')['fingerprint'],coupon_evidence('<p>쿠폰 20%</p>')['fingerprint'])
  self.assertEqual(coupon_evidence('<p>일반 상품</p>')['snippets'],[])
 def test_price_drop_even_advertised_price_stays(self):
  from watch import notification_reason
  p=parse_product(PAGE,SOURCE)
  prev={'last_notified_candidate_price':1500000,'last_observation':{**p,'price_krw':2100000}}
  self.assertEqual(notification_reason(p,prev),'공개 표시가 하락')
 def test_restock(self):
  from watch import notification_reason
  p=parse_product(PAGE,SOURCE)
  self.assertEqual(notification_reason(p,{'last_notified_candidate_price':1500000,'last_observation':{**p,'in_stock':False}}),'재입고 확인')
 def test_email_success_cannot_hide_telegram_failure(self):
  from watch import deliver
  state={};report={'deliveries':[],'errors':[]}
  with patch('watch.telegram',return_value=False),patch('watch.email',return_value=True):
   self.assertFalse(deliver(state,report,'x','message'))
  self.assertIn('telegram',report['deliveries'][0]['pending_channels'])
 def run_monitor(self,dry=False,page=PAGE,send=True):
  import watch,json,os
  Path('config.json').write_text(json.dumps({'scope':'fixture','sources':[SOURCE],'unsupported':[]}))
  with patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':''}),patch.object(sys,'argv',['watch.py']+(['--dry-run'] if dry else [])),patch('watch.fetch',return_value=page),patch('watch.time.sleep'),patch('watch.telegram',return_value=send),patch('watch.email',return_value=False):
   result=watch.main()
  return result,json.loads(Path('report.json').read_text())
 def test_main_baseline_change_retry_and_no_duplicate(self):
  import tempfile,os,json
  previous=os.getcwd()
  with tempfile.TemporaryDirectory() as d:
   try:
    os.chdir(d)
    with patch.dict(os.environ,{},clear=True):
     rc,r=self.run_monitor(page=PAGE+'<p>쿠폰 10%</p>');self.assertEqual(rc,0)
     self.assertFalse(any(x['event'].startswith('coupon:') for x in r['deliveries']))
     rc,r=self.run_monitor(page=PAGE+'<p>쿠폰 20%</p>',send=False);self.assertEqual(rc,1)
     self.assertEqual(r['notification_status'],'failed')
     rc,r=self.run_monitor(page=PAGE+'<p>쿠폰 20%</p>');self.assertEqual(rc,0)
     self.assertTrue(any(x['event'].startswith('coupon:') for x in r['deliveries']))
     rc,r=self.run_monitor(page=PAGE+'<p>쿠폰 20%</p>')
     self.assertFalse(any(x['event'].startswith('coupon:') for x in r['deliveries']))
   finally:os.chdir(previous)
 def test_dry_run_does_not_write_checkpoint_or_send(self):
  import tempfile,os
  previous=os.getcwd()
  with tempfile.TemporaryDirectory() as d:
   try:
    os.chdir(d)
    rc,r=self.run_monitor(dry=True)
    self.assertEqual(rc,0);self.assertEqual(r['notification_status'],'dry_run')
    self.assertFalse(Path('state.json').exists());self.assertEqual(r['deliveries'],[])
   finally:os.chdir(previous)
 def test_missing_telegram_secret_fails_delivery(self):
  from watch import telegram
  import os
  with patch.dict(os.environ,{},clear=True):self.assertFalse(telegram('test'))

if __name__=='__main__':unittest.main()
