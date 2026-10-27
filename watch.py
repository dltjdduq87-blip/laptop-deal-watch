"""Conservative public-page watcher. No login, checkout claims or CAPTCHA bypass."""
import argparse, hashlib, html, json, math, os, re, smtplib, ssl, time
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from urllib import request, error, parse, robotparser

UA='LaptopDealWatch/1.0 (personal public-price monitor)'
ALLOWED={'www.lge.co.kr','www.samsung.com','www.11st.co.kr','prod.danawa.com','www.enuri.com','enuri.com','price.enuri.com','m.enuri.com','www.gmarket.co.kr','item.gmarket.co.kr','www.auction.co.kr','itempage3.auction.co.kr','www.ssg.com','www.e-himart.co.kr','www.asus.com','www.hp.com','shopping.naver.com','search.shopping.naver.com','www.coupang.com','www.ppomppu.co.kr','bbs.ruliweb.com'}
CHANNELS=['KB국민 신용','우리 신용','KB국민 체크','하나 카카오페이 체크','하나 트래블로그 체크','카카오뱅크 체크','토스뱅크 체크','네이버페이','카카오페이']
ROBOTS={}
DELIVERY_VERSION='2026-10-24-coupon-watch-v1'
DELIVERY_AUDIT=[]

def coupon_evidence(raw):
 """Public text evidence only; never treats advertising as an eligible discount."""
 doc=Document();doc.feed(raw)
 snippets=sorted(set(re.sub(r'\s+',' ',s).strip()[:500] for s in doc.parts
                     if re.search(r'쿠폰|선착순|coupon',s,re.I)))[:30]
 return {'snippets':snippets,'fingerprint':hashlib.sha256(json.dumps(snippets,ensure_ascii=False).encode()).hexdigest(),
         'eligibility':'미확인','stacking_verified':False,'deadline_verified':False}

def notification_reason(p,previous):
 if not qualifies_candidate(p):return None
 if should_notify(p,previous):return '신규 후보 또는 광고 후보가 하락'
 old=(previous or {}).get('last_observation',{})
 if old.get('in_stock') is False:return '재입고 확인'
 if old.get('price_krw') and p['price_krw']<old['price_krw']:return '공개 표시가 하락'
 return None

def enabled_channels():
 channels=['telegram']  # Existing Telegram delivery is required; missing secrets are an error.
 if all(os.environ.get(x) for x in ['SMTP_HOST','SMTP_USER','SMTP_PASSWORD','EMAIL_TO']):channels.append('email')
 return channels

def deliver(state,report,key,message):
 delivery_event(state,key,message)
 sent=state.get('sent',{}).get(key,[])
 pending=[c for c in enabled_channels() if c not in sent]
 report['deliveries'].append({'event':key,'sent_channels':list(sent),'pending_channels':pending})
 if pending:report['errors'].append({'source':'notifications','code':'DELIVERY_FAILED:'+','.join(pending)})
 return not pending

def write_json(path,value):
 path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
 temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
class Document(HTMLParser):
 def __init__(self):
  super().__init__();self.hidden=0;self.ld=False;self.buffer=[];self.scripts=[];self.parts=[];self.links=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='a' and a.get('href'):self.links.append(a['href'])
  if tag in ('script','style'):
   self.hidden+=1
   if tag=='script' and a.get('type','').lower()=='application/ld+json':self.ld=True;self.buffer=[]
 def handle_endtag(self,tag):
  if tag in ('script','style'):
   self.hidden=max(0,self.hidden-1)
   if tag=='script' and self.ld:self.scripts.append(''.join(self.buffer));self.ld=False
 def handle_data(self,data):
  if self.ld:self.buffer.append(data)
  if not self.hidden and data.strip():self.parts.append(data.strip())
 @property
 def text(self):return ' '.join(self.parts)

def nodes(value):
 if isinstance(value,list):
  for x in value:yield from nodes(x)
 elif isinstance(value,dict):
  yield value
  for key in ('@graph','hasVariant','itemListElement','item','mainEntity'):
   if key in value:yield from nodes(value[key])

def integer(value):
 if isinstance(value,bool):raise ValueError('INVALID_AMOUNT')
 try:n=Decimal(str(value).replace(',',''))
 except (InvalidOperation,ValueError):raise ValueError('INVALID_AMOUNT') from None
 if not n.is_finite() or n<=0 or n!=n.to_integral_value():raise ValueError('INVALID_AMOUNT')
 return int(n)

def parse_product(raw,source):
 doc=Document();doc.feed(raw);products=[]
 for script in doc.scripts:
  try:
   for p in nodes(json.loads(script)):
    typ=p.get('@type',[]);typ=[typ] if isinstance(typ,str) else typ
    if 'Product' in typ:products.append(p)
  except (ValueError,TypeError):continue
 exact=[]
 for p in products:
  if source.get('model'):
   if str(p.get('model') or p.get('sku') or '').upper()!=source['model'].upper():continue
  elif source.get('product_id'):
   if str(p.get('productID',''))!=source['product_id']:continue
  else:continue
  exact.append(p)
 if len(exact)!=1:raise ValueError('MODEL_MISMATCH_OR_NO_PRODUCT')
 p=exact[0];category=str(p.get('category',''))
 if '노트북' not in category and 'laptop' not in category.lower():
  if not (source['site']=='삼성' and re.search(r'갤럭시\s*북',p.get('name',''))):raise ValueError('NOT_A_LAPTOP')
 offers=p.get('offers',[]);offers=[offers] if isinstance(offers,dict) else offers
 good=[]
 for o in offers:
  if not isinstance(o,dict) or o.get('@type')!='Offer' or o.get('priceCurrency')!='KRW':continue
  if o.get('itemCondition') and not o['itemCondition'].endswith('/NewCondition'):continue
  try:good.append((integer(o.get('price')),o))
  except ValueError:continue
 if len(good)!=1:raise ValueError('NO_EXACT_OFFER')
 price,o=good[0];props={x.get('name'):str(x.get('value','')) for x in p.get('additionalProperty',[]) if isinstance(x,dict)}
 ram=None;weight=None
 if source['site']=='LG':
  r=re.search(r'메모리 용량\s*\(GB\)\s*(\d+)\b',doc.text)
  if r:ram=int(r[1])
  w=re.search(r'(\d[\d,]*(?:\.\d+)?)',props.get('무게 (g)',''))
  if w:weight=float(w[1].replace(',',''))/1000
 else:
  r=re.search(r'\b(\d+)\s*GB\b',str(p.get('name','')),re.I)
  if r:ram=int(r[1])
 max_benefit=None
 if source['site']=='LG':
  b=re.search(r'최대혜택가(?:\s+상세 내용 열기)?\s+([\d,]+)\s*원',doc.text)
  if b:max_benefit=integer(b[1])
 return dict(source_id=source['id'],site=source['site'],model=source.get('model') or source.get('product_id'),name=str(p.get('name','')),url=source['url'],price_krw=price,price_type='공개 표시가 (회원할인가 표기 포함, 적용 자격 미확인)',checkout_verified_krw=None,ram_gb=ram,weight_kg=weight,in_stock=str(o.get('availability','')).endswith('/InStock'),cpu=props.get('CPU'),spec_source_url=source['url'],observed_at=datetime.now(timezone.utc).isoformat(),html_sha256=hashlib.sha256(raw.encode()).hexdigest(),advertised_max_benefit_unverified=max_benefit,payment_methods=[{'method':c,'eligibility':'미확인','verified_discount_krw':None} for c in CHANNELS],seller='제조사 공식몰' if source['site'] in ('LG','삼성') else '판매자/국내 AS 검증 전',shipping_verified_krw=None,discounts_verified=False)

def qualifies(p):
 return (isinstance(p.get('ram_gb'),int) and p['ram_gb']>=32 and isinstance(p.get('weight_kg'),(float,int)) and math.isfinite(p['weight_kg']) and 0<p['weight_kg']<=1.6 and 1500000<=p['price_krw']<=3000000 and p.get('in_stock') and p.get('seller')=='제조사 공식몰')

def candidate_price(p):
 values=[p['price_krw']]
 value=p.get('advertised_max_benefit_unverified')
 if isinstance(value,int) and 0<value<=p['price_krw']:values.append(value)
 return min(values)

def qualifies_candidate(p):
 # Advertising can nominate a candidate, never verify personal eligibility.
 return qualifies({**p,'price_krw':candidate_price(p)})

def score(p):
 # Policy scores are not benchmark measurements. Do not invent absent AI/game data.
 return {'price_policy':round(40*max(0,min(1,(3000000-candidate_price(p))/1500000)),2),'portability_policy':round(20*max(0,min(1,(1.6-p['weight_kg'])/.6)),2) if p.get('weight_kg') else None,'ai_development':None,'gaming':None,'total':None,'status':'성능 벤치마크 미검증, 총점/종합순위 미산출','weights':{'value':40,'ai_development':30,'portability':20,'gaming':10}}

def should_notify(p,previous):
 return qualifies_candidate(p) and (not previous or previous.get('last_notified_candidate_price') is None or candidate_price(p)<previous['last_notified_candidate_price'])

class SafeRedirect(request.HTTPRedirectHandler):
 def __init__(self,check_robots=True):self.check_robots=check_robots
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  validate_url(newurl)
  if self.check_robots:ensure_robot_access(newurl)
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def validate_url(url):
 u=parse.urlsplit(url)
 if u.scheme!='https' or u.hostname not in ALLOWED or u.username or u.password or u.port not in (None,443):raise ValueError('UNAPPROVED_URL')

def ensure_robot_access(url):
 host=parse.urlsplit(url).netloc
 if host not in ROBOTS:
  parser=robotparser.RobotFileParser()
  try:parser.parse(fetch('https://'+host+'/robots.txt',False).splitlines())
  except Exception:raise ValueError('ROBOTS_UNAVAILABLE') from None
  ROBOTS[host]=parser
 if not ROBOTS[host].can_fetch(UA,url):raise ValueError('ROBOTS_DISALLOWED')

def fetch(url,robots=True):
 validate_url(url)
 if robots:ensure_robot_access(url)
 req=request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,text/plain,application/rss+xml,application/xml'})
 try:
  with request.build_opener(SafeRedirect(robots)).open(req,timeout=12) as r:
   validate_url(r.url)
   data=r.read(12000001)
   if len(data)>12000000:raise ValueError('PAGE_TOO_LARGE')
   return data.decode(r.headers.get_content_charset() or 'utf8','replace')
 except error.HTTPError as e:raise ValueError('HTTP_'+str(e.code)) from None
 except (error.URLError,TimeoutError):raise ValueError('NETWORK_ERROR') from None

def telegram(text):
 token=os.environ.get('TELEGRAM_BOT_TOKEN','');chat=os.environ.get('TELEGRAM_CHAT_ID','')
 if not token or not chat:return False
 try:
  # The token is used only inside this HTTPS request, never printed.
  def call(method,payload):
   req=request.Request('https://api.telegram.org/bot'+token+'/'+method,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
   with request.urlopen(req,timeout=20) as r:
    d=json.load(r)
    if not d.get('ok'):raise ValueError()
    return d['result']
  info=call('getChat',{'chat_id':chat})
  if info.get('type')!='private' or info.get('username','').lower()!='kahn777':return False
  receipt=call('sendMessage',{'chat_id':chat,'text':text[:4000]})
  DELIVERY_AUDIT.append({'channel':'telegram','status':'api_accepted','message_id':receipt.get('message_id')})
  return True
 except Exception:return False

def email(text):
 host=os.environ.get('SMTP_HOST','');sender=os.environ.get('SMTP_USER','');password=os.environ.get('SMTP_PASSWORD','');recipient=os.environ.get('EMAIL_TO','')
 if not all((host,sender,password,recipient)):return False
 try:
  msg=EmailMessage();msg['Subject']='노트북 할인 감시';msg['From']=sender;msg['To']=recipient;msg.set_content(text)
  with smtplib.SMTP_SSL(host,int(os.environ.get('SMTP_PORT','465')),context=ssl.create_default_context(),timeout=20) as s:
   s.login(sender,password);s.send_message(msg)
  return True
 except Exception:return False

def delivery_event(state,key,text):
 sent=state.setdefault('sent',{}).setdefault(key,[]);success=False
 for channel,fn in [('telegram',telegram),('email',email)]:
  if channel in sent:success=True;continue
  if fn(text):sent.append(channel);success=True
 if not sent:state['sent'].pop(key,None)
 return success


REPORT_URL='https://github.com/dltjdduq87-blip/laptop-deal-watch/blob/watch-state/report.json'

def coverage_reason(row):
 code=row.get('code','')
 if code=='ELEVENST_API_KEY_MISSING':return '공식 API 인증키 연결 필요'
 if code=='ROBOTS_DISALLOWED':return '사이트 수집 정책상 현재 경로 사용 불가'
 if code=='ROBOTS_UNAVAILABLE':return '수집 허용 정책 확인 실패'
 if code.startswith('HTTP_'):return '자동 수집 요청 거부 ('+code[5:]+')'
 if row['status']=='no_parseable_products':return '상품별 가격 데이터 추출 미완료'
 return '수집 실패, 상세 보고서 확인 필요'

def health_signature(report):
 # Counts and product ordering change normally; only health transitions alert.
 payload={'coverage':sorted((r['site'],r['status'],r.get('code','')) for r in report.get('coverage',[])),
          'errors':sorted((e['source'],e['code']) for e in report['errors'] if e['source']!='notifications')}
 return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:16]

def status_summary(report):
 rows=report.get('coverage',[])
 good=[r['site'] for r in rows if r['status']=='collected']
 indirect=[r['site'] for r in rows if r['status']=='via_comparison']
 pending=[r for r in rows if r['status'] not in ('collected','via_comparison')]
 stamp=datetime.fromisoformat(report['observed_at']).astimezone(timezone(timedelta(hours=9))).strftime('%m/%d %H:%M')
 lines=['노트북 감시 현황 · '+stamp+' 한국시간']
 if rows:
  lines+=['가격 수집 '+str(len(good)+len(indirect))+'/'+str(len(rows))+'곳'+(' · 일부 미완료' if pending else ''),
          '수집 확인: '+', '.join(good)]
  if indirect:lines+=['다나와·에누리 판매처 가격으로 확인: '+', '.join(indirect)]
  if pending:
   lines+=['미완료 (아래 판매처의 할인은 놓칠 수 있습니다):']
   lines+=['• '+r['site']+': '+coverage_reason(r) for r in pending]
 else:lines+=['정확한 모델 가격 관측 '+str(len(report['products']))+'건']
 lines+=['가격비교·목록 관측 '+str(len(report.get('market_products',[])))+'건 / 개별 모델 관측 '+str(len(report['products']))+'건 (중복 가능)']
 candidates=report.get('review_candidates',[])
 models={model_key(p) for p in candidates}
 makers=sorted({k.split()[0] for k in models})
 lines+=['조건 충족 '+str(len(models))+'개 모델 / '+str(len(candidates))+'개 옵션 (예상가 기준)',
         '제조사: '+(', '.join(makers) if makers else '없음')]
 for band in BANDS:
  lines.append(band+': '+str(len({model_key(p) for p in candidates if p['price_band']==band}))+'개 모델')
 if report.get('top_by_band') is not None:
  lines+=['AI·게임 최적 기준: 외장 GPU(RTX 등) 우선 → 같은 등급은 예상가 낮은 순 · 병행수입·해외구매 의심 상품 제외','A/S 표시: 국내AS(삼성·LG) / 정품표기·정품미확인(해외 제조사, 판매처 문구 기준)']
 for band,band_rows in (report.get('top_by_band') or {}).items():
  if band_rows:
   lines+=['['+band+'] TOP '+str(len(band_rows))+':']
   lines+=['  '+str(p['band_rank'])+'. ['+p['ai_game_tier']+(('·'+__import__('as_service').tag(p)) if p.get('as_status') else '')+'] '+won(p['effective_price_krw'])+' '+p['model_key'][:38]+' ('+str(p['weight_kg'])+'kg)' for p in band_rows]
  else:lines+=['['+band+'] AI·게임 기준 충족 모델 없음']
 if report.get('as_pending'):
  lines+=['정식 A/S 확인 대기 (해외 제조사·국내 정품 신호 없음 → 알림 보류):']
  lines+=['  ['+p['ai_game_tier']+'] '+won(p['effective_price_krw'])+' '+p['model_key'][:38] for p in report['as_pending'][:5]]
 sweep_row=next((r for r in rows if r.get('method')),None)
 if sweep_row and not report.get('sweep_complete',True):
  lines+=['에누리 전체 목록 1회차 수집 중 ('+str(sweep_row['products'])+'/'+str(sweep_row.get('models_in_filter') or '?')+') · 완료 후 후보 알림 시작']
 # Raw diagnostics stay in report.json. Do not hide non-catalog failures.
 indirect=[r for r in report.get('shop_summary',[]) if r['indirect_offers'] and r['site'] not in ('다나와','에누리')]
 if report.get('offer_details') is not None:
  lines+=['판매처별 간접 가격 (다나와·에누리 상세 '+str(len(report['offer_details']))+'개 모델): '+(', '.join(r['site']+' '+str(r['indirect_offers'])+'건' for r in indirect) or '대상 쇼핑몰 행 없음'),
          '간접 가격은 비교사이트 표시값이며 해당 쇼핑몰 로그인·쿠폰 확인이 아닙니다.']
 catalog_sources={r['site']+' 목록' for r in rows}
 extra=[e for e in report['errors'] if e['source'] not in catalog_sources]
 if extra:lines+=['추가 점검 필요: '+', '.join(sorted({e['source'] for e in extra}))]
 lines+=['회원 쿠폰·카드 중복·배송비·국내 AS는 미확인입니다.', '상세 오류·근거: '+REPORT_URL]
 return '\n'.join(lines)

def won(v):return format(v,',')+'원'

def estimate_line(p):
 e=p.get('buyer_estimate')
 if not e:return ''
 if e['basis']=='보유 결제수단 조건가':
  return '내 결제수단 예상가 '+won(e['estimated_krw'])+' ('+e['seller']+')\n  조건: '+e['condition']+'\n'
 line='보유 카드 할인 표시 없음 → 최저 판매처 '+e['seller']+' '+won(e['estimated_krw'])
 return line+(' (배송비 미확인)' if not e['shipping_known'] else ' (배송비 포함)')+'\n'

TOP_KEY_VERSION=2
BANDS=('150~190만원','190~230만원','230~300만원')

def model_key(p):
 return re.sub(r'\s+',' ',str(p.get('model_key') or p.get('model') or p['name'].split(' / ')[0])).strip().upper()

OS_RAM=re.compile(r'\b(WIN\s?1[01]\w*|W1[01]\w*|FREE\s?DOS|DOS|OS\s?미포함|\d+\s?GB\s?램|램\s?\d+\s?GB)\b',re.I)

def perf_key(p):
 """Same-performance group: same maker + CPU + GPU + RAM (OS·SSD·color variants merge).
 Without CPU text, falls back to the model name minus OS/RAM tags."""
 name=model_key(p);brand=name.split(' ')[0]
 cpu=re.sub(r'\([\d.]+\s*G?Hz\)','',str(p.get('cpu') or '')).strip()
 if cpu:
  gpu=re.sub(r'\s+',' ',str(p.get('gpu') or '')).strip()
  return re.sub(r'\s+',' ',' | '.join([brand,cpu,gpu,str(p.get('ram_gb') or '')])).upper()
 return re.sub(r'\s+',' ',OS_RAM.sub(' ',name)).strip().upper()

def drop_lines(before,now):
 diff=before-now
 return '이전가 '+won(before)+' → 현재가 '+won(now)+'\n▼ '+won(diff)+' ('+format(diff/before*100,'.1f')+'% 할인)\n'

def rank_by_band(candidates,n=3,min_tier='A',brands=None,require_genuine=()):
 """Best option per model (lowest effective price), then per band: AI/game tier first, then price."""
 import ai_game, as_service
 best={}
 for p in candidates:
  if not ai_game.allowed(p,min_tier):continue
  if 'as_status' in p and not as_service.allowed(p):continue
  if not as_service.brand_ok(p,brands,require_genuine):continue
  p={**p,'ai_game_tier':ai_game.tier(p),'ai_game_desc':ai_game.describe(p)}
  k=perf_key(p);cur=best.get(k)
  if cur is None or p['effective_price_krw']<cur['effective_price_krw']:
   best[k]={**p,'model_key':model_key(p),'perf_key':k,'options_seen':(cur or {}).get('options_seen',0)+1}
  else:cur['options_seen']+=1
 ranked={b:[] for b in BANDS}
 for p in sorted(best.values(),key=lambda p:(ai_game.TIER_ORDER[p['ai_game_tier']],p['effective_price_krw'])):
  if p['price_band'] in ranked and len(ranked[p['price_band']])<n:
   ranked[p['price_band']].append({**p,'band_rank':len(ranked[p['price_band']])+1})
 return ranked

def spec_line(p):
 parts=[x for x in [p.get('cpu'),p.get('gpu'),p.get('screen'),p.get('os')] if x]
 return ('사양: '+' · '.join(parts)+'\n') if parts else ''

def candidate_message(report,p):
 rank=(p['price_band']+' '+str(p['band_rank'])+'위 · ') if p.get('band_rank') else ''
 return ('노트북 후보 알림 (구매 확정 추천 아님)\n'+rank+'예상가 '+won(p['effective_price_krw'])+'\n'+p['name']+'\n'
         +'공개 비교가 '+won(p['price_krw'])+' ('+p['site']+')\n'
         +estimate_line(p)
         +'RAM '+str(p['ram_gb'])+'GB / '+str(p['weight_kg'])+'kg\n'
         +('AI·게임 등급: '+p['ai_game_desc']+' (사양 기준, FPS·벤치마크 아님)\n' if p.get('ai_game_desc') else '')
         +spec_line(p)
         +(__import__('as_service').message_lines(p) if p.get('as_status') else '')
         +offer_lines(report,p)
         +'예상가는 공개 정보 계산값입니다. T멤버십(VIP)·쇼핑몰 쿠폰·카드 실적/한도·재고·국내 AS는 구매 전 앱에서 확인하세요.\n'+p['url'])

def offer_lines(report,p):
 rows=[o for o in report.get('offer_observations',[]) if o.get('list_source_id')==p.get('source_id') and o['price_condition'].startswith('일반 판매가') and not o.get('is_ad') and not o.get('is_overseas')]
 if not rows:return ''
 rows=sorted(rows,key=lambda o:o['price_krw'])[:4]
 return '판매처별(간접): '+', '.join(o['seller_name']+' '+format(o['price_krw'],',')+'원' for o in rows)+'\n'

def notify_status(state,report,now,config=None):
 """No routine status chatter: one daily summary (optional) and a total-outage alert at most once a day.

 Site status changes are recorded silently and shown in the next daily summary."""
 config=config or {}
 kst=now.astimezone(timezone(timedelta(hours=9)))
 day=kst.date().isoformat()
 state['health_signature']=health_signature(report);state.pop('pending_health',None)
 if report.get('status')=='error' and not report.get('market_products'):
  key='outage:'+day
  if any(c not in state.get('sent',{}).get(key,[]) for c in enabled_channels()):
   deliver(state,report,key,'노트북 감시 수집 전체 실패 · 오늘 감시가 멈춘 상태입니다.\n'+status_summary(report))
  return
 hour=config.get('daily_summary_hour_kst',10)
 if hour is None:return
 daily_key='daily:'+day
 if kst.hour>=hour and any(c not in state.get('sent',{}).get(daily_key,[]) for c in enabled_channels()):
  deliver(state,report,daily_key,status_summary(report))


def main():
 args=argparse.ArgumentParser();args.add_argument('--dry-run',action='store_true');args.add_argument('--config',default='config.json');a=args.parse_args()
 config=json.loads(Path(a.config).read_text());state_path=Path('state.json')
 state=json.loads(state_path.read_text()) if state_path.exists() else {'products':{},'sent':{}}
 now=datetime.now(timezone.utc);day=now.astimezone(timezone(timedelta(hours=9))).date().isoformat()
 state.setdefault('products',{});state.setdefault('sent',{})
 report={'observed_at':now.isoformat(),'status':'partial','deliveries':[],'delivery_receipts':DELIVERY_AUDIT,'scope':config['scope'],'products':[],'errors':[],'unsupported':config['unsupported'],'email_configured':all(os.environ.get(x) for x in ['SMTP_HOST','SMTP_USER','SMTP_PASSWORD','EMAIL_TO'])}
 from catalog import scan, review_candidate, price_band
 sweep_cfg=config.get('enuri_sweep')
 sweep_sites={x['site'] for x in config.get('catalogs',[]) if x.get('adapter')=='enuri_sweep'}
 coverage,market_products=scan({**config,'catalogs':[x for x in config.get('catalogs',[]) if x.get('adapter')!='enuri_sweep']},fetch)
 if sweep_cfg and sweep_sites:
  from sweep import sweep
  row,found=sweep(fetch,state,sweep_cfg)
  order=[x['site'] for x in config.get('catalogs',[])]
  coverage.append(row);coverage.sort(key=lambda r:order.index(r['site']) if r['site'] in order else 99)
  market_products.extend(found)
  report['sweep_complete']=bool(state.get('enuri_sweep',{}).get('sweeps_completed'))
 report['coverage']=coverage;report['market_products']=market_products
 # Indirect seller-level prices from comparison-site detail pages; never a shop login/coupon check.
 from offers import collect_offers, enrich_specs, shop_summary, apply_spec_cache, update_spec_cache
 spec_cache=state.setdefault('detail_specs',{})
 apply_spec_cache(market_products,spec_cache)
 details,offer_obs,offer_errors=collect_offers(market_products,fetch,limit_per_site=config.get('offer_detail_limit',8),delay=config.get('offer_detail_delay',1.0))
 enrich_specs(market_products,details);update_spec_cache(spec_cache,details)
 report['offer_details']=details;report['offer_observations']=offer_obs;report['offer_errors']=offer_errors
 for agg in ('다나와','에누리'):
  tried=[e for e in offer_errors if e['source']==agg+' 상세']
  if tried and not any(d['aggregator']==agg for d in details):report['errors'].append({'source':agg+' 상세','code':tried[0]['code']})
 from offers import attach_estimates, effective_price
 attach_estimates(market_products,offer_obs)
 report['review_candidates']=[{**p,'effective_price_krw':effective_price(p),'price_band':price_band(effective_price(p)),'recommendation':'판매자·재고·국내 AS·결제조건 확인 전 검토 후보'} for p in market_products if review_candidate({**p,'price_krw':effective_price(p)})]
 import release
 report['too_old_excluded']=[{'name':p['name'],'basis':release.estimate(p)['basis']} for p in report['review_candidates'] if release.too_old(p,now,config.get('max_release_age_months',36))]
 report['review_candidates']=[p for p in report['review_candidates'] if not release.too_old(p,now,config.get('max_release_age_months',36))]
 import as_service
 by_src={}
 for o in offer_obs:by_src.setdefault(o.get('list_source_id'),[]).append(o)
 report['review_candidates']=[{**p,**as_service.assess(p,by_src.get(p.get('source_id'),[]),config.get('as_policy'))} for p in report['review_candidates']]
 report['ai_game_min_tier']=config.get('min_ai_game_tier','A')
 report['top_by_band']=rank_by_band(report['review_candidates'],config.get('top_per_band',3),report['ai_game_min_tier'],config.get('allowed_brands'),tuple(config.get('brands_require_genuine') or ()))
 report['top_by_band_flat']=[p for band in report['top_by_band'].values() for p in band]
 # 해외 제조사 중 정식 A/S(국내 정품) 신호가 없는 후보: 알림 대신 일일 요약의 '확인 대기'로
 if config.get('brands_require_genuine'):
  pend=rank_by_band(report['review_candidates'],config.get('top_per_band',3),report['ai_game_min_tier'],config.get('allowed_brands'))
  report['as_pending']=[p for band in pend.values() for p in band if not as_service.brand_ok(p,None,tuple(config['brands_require_genuine']))]
 report['ignored_links']=config.get('ignored_links',[])
 catalog_state=state.setdefault('catalog_prices',{})
 if not a.dry_run and config.get('catalog_review_notifications'):
  # Alert only models entering a price band's top list or getting cheaper there; bounded per run.
  # v2: alerts are keyed by same-performance group. On upgrade, record the current list silently
  # so already-known models are not re-sent as "new" just because the key format changed.
  if state.get('top_key_version')!=TOP_KEY_VERSION and report.get('sweep_complete',True):
   if state.get('top_alerts'):
    state['top_alerts']={p['perf_key']:p['effective_price_krw'] for p in report['top_by_band_flat']}
    state['top_alert_names']={p['perf_key']:p['name'] for p in report['top_by_band_flat']}
   state['top_key_version']=TOP_KEY_VERSION
  top_state=state.setdefault('top_alerts',{});names=state.setdefault('top_alert_names',{})
  # Wait for the first full rotation so the top list is not built from a partial sweep.
  due=[] if not report.get('sweep_complete',True) else [p for p in report['top_by_band_flat'] if top_state.get(p['perf_key']) is None or p['effective_price_krw']<top_state[p['perf_key']]]
  for p in sorted(due,key=lambda p:p['effective_price_krw'])[:config.get('max_alerts_per_run',3)]:
   k=p['perf_key'];key='top:'+k+':'+str(p['effective_price_krw'])
   before=top_state.get(k)
   reason='조건 충족 새 후보' if before is None else '같은 성능 가격 하락'
   if (p.get('buyer_estimate') or {}).get('basis')=='보유 결제수단 조건가':reason+=' · 보유 카드 혜택 적용'
   head='['+reason+']\n'
   if before is not None:
    head+=drop_lines(before,p['effective_price_krw'])
    if names.get(k) and names[k]!=p['name']:head+='(이전가는 같은 성능 다른 구성: '+names[k]+')\n'
   if deliver(state,report,key,head+candidate_message(report,p)):top_state[k]=p['effective_price_krw'];names[k]=p['name']
 if not a.dry_run and config.get('events'):
  from events import due_alerts
  top_lines=[('['+p['ai_game_tier']+'] '+won(p['effective_price_krw'])+' '+p['model_key'][:38]) for p in report['top_by_band_flat'][:5]]
  for key,message in due_alerts(config['events'],now,top_lines):
   if any(c not in state['sent'].get(key,[]) for c in enabled_channels()):deliver(state,report,key,message)
 if config.get('hotdeal_feeds'):
  import hotdeal
  hd=report.setdefault('hotdeal',{'feeds':[],'deals':[]})
  first=state.get('hotdeal_seen') is None
  seen=state.setdefault('hotdeal_seen',[])
  items=[]
  for f in config['hotdeal_feeds']:
   try:
    got=hotdeal.parse_rss(fetch(f['url']),f['name']);items+=got;hd['feeds'].append({'name':f['name'],'status':'collected','items':len(got)})
   except Exception as e:hd['feeds'].append({'name':f['name'],'status':'error','code':str(e) if isinstance(e,ValueError) else type(e).__name__})
  band=(config['enuri_sweep'].get('start_price',1500000),config['enuri_sweep'].get('end_price',3000000)) if config.get('enuri_sweep') else (1500000,3000000)
  deals=hotdeal.new_laptop_deals(items,seen,band,config.get('as_policy'),tuple(config.get('allowed_brands') or hotdeal.DEFAULT_BRANDS),tuple(config.get('brands_require_genuine') or ()))
  hd['deals']=[{k:d[k] for k in ('title','link','feed','fit','as_line','price_krw')} for d in deals]
  if not a.dry_run and not first:
   for d in deals[:config.get('hotdeal_max_alerts_per_run',5)]:deliver(state,report,'hotdeal:'+d['id'],hotdeal.message(d))
 if not a.dry_run:
  deliver(state,report,'verification:'+DELIVERY_VERSION,'노트북 감시 개선 검증 알림\n공개 쿠폰 문구 변경 감지·가격 하락·재입고·전송 상태 검증을 적용했습니다.\n이 메시지는 연결 테스트이며 할인 확정 알림이 아닙니다.')
 api_sites={x['site'] for x in config.get('catalogs',[]) if x.get('adapter') in ('elevenst_api','via_comparison')}
 # API replaces the same site's disallowed HTML route; retain config for audit.
 sources=[x for x in config['sources'] if x['site'] not in api_sites]
 report['superseded_sources']=[{'source':x['id'],'reason':'직접 수집 불가(사이트 정책) · 공식 API 또는 가격비교 판매처 경로로 대체'} for x in config['sources'] if x['site'] in api_sites]
 for discovery in config.get('discovery',[]):
  try:
   doc=Document();doc.feed(fetch(discovery['url']))
   models=sorted(set(re.findall(r'/notebook/(\d{2}z[a-z0-9]+-[a-z0-9]+)(?=[?"/\s]|$)',' '.join(doc.links),re.I)))
   for model in models[:config.get('max_discovered_products',8)]:
    url='https://www.lge.co.kr/product/notebook/'+model.lower()
    if not any(s['url']==url for s in sources):sources.append({'id':'lg-'+model.lower(),'site':'LG','url':url,'model':model.upper()})
  except Exception as e:report['errors'].append({'source':'LG 목록','code':str(e) if isinstance(e,ValueError) else type(e).__name__})
 for source in sources:
  try:
   raw=fetch(source['url']);p=parse_product(raw,source);p['coupon_evidence']=coupon_evidence(raw);p['matches_public_price_filter']=qualifies(p);p['matches_advertised_budget_filter']=qualifies_candidate(p);p['assessment']=score(p);report['products'].append(p)
   prev=state['products'].get(source['id'],{})
   key='price:'+source['id']+':'+str(candidate_price(p))+':'+str(p['price_krw'])
   reason=notification_reason(p,prev)
   pending=prev.get('pending_price_event','')
   if pending.startswith(key+':'):
    key=pending
   elif reason in ('재입고 확인','공개 표시가 하락'):
    key+=':'+p['observed_at']
   retry_delivery=key in state['sent'] and any(c not in state['sent'][key] for c in enabled_channels())
   pending_price=prev.get('pending_price_event')
   retry_delivery=retry_delivery or pending_price==key
   if not a.dry_run and qualifies_candidate(p) and (reason or retry_delivery):
    old_price=prev.get('last_observation',{}).get('price_krw')
    message=((reason or '알림 재전송')+'\n'+(drop_lines(old_price,p['price_krw']) if old_price and p['price_krw']<old_price else '')+'최대혜택 기준 예산 후보 (본인 적용·실결제가 미확인)\n'+p['name']+' / '+p['model']+'\n표시가 '+format(p['price_krw'],',')+'원\n광고 최대혜택 후보가 '+format(candidate_price(p),',')+'원 (카드/간편결제 적용 미확인)\nRAM '+str(p['ram_gb'])+'GB / '+str(p['weight_kg'])+'kg\n쿠폰·카드·배송비 적용 및 실결제 미확인\n'+p['url']+'\n확인(UTC): '+p['observed_at'])
    prev['pending_price_event']=key
    if deliver(state,report,key,message):
     prev['last_notified_candidate_price']=candidate_price(p);prev.pop('pending_price_event',None)
   evidence=p['coupon_evidence'];old_evidence=prev.get('last_observation',{}).get('coupon_evidence')
   if old_evidence and evidence['fingerprint']!=old_evidence['fingerprint']:
    prev['pending_coupon_event']=evidence['fingerprint']
   if not a.dry_run and qualifies_candidate(p) and prev.get('pending_coupon_event')==evidence['fingerprint']:
    coupon_key='coupon:'+source['id']+':'+evidence['fingerprint']
    coupon_message=('공개 쿠폰 문구 변경 (개인 적용·발급 가능·기한 미확인)\n'+p['name']+' / '+p['model']+'\n'+(('\n'.join(evidence['snippets'])[:2800]) or '이전 쿠폰 문구가 현재 페이지에서 확인되지 않습니다.')+'\n'+p['url'])
    if deliver(state,report,coupon_key,coupon_message):prev.pop('pending_coupon_event',None)
   prev['last_observation']=p;state['products'][source['id']]=prev
  except Exception as e:
   report['errors'].append({'source':source['id'],'code':str(e) if isinstance(e,ValueError) else type(e).__name__})
  time.sleep(.25)
 if not report['products']:report['status']='error'
 # Legacy exact-SKU observations may supply a catalog whose listing lacks JSON-LD.
 for row in coverage:
  exact=[p for p in report['products'] if p['site']==row['site']]
  row['exact_sku_observations']=len(exact)
  if exact and not row['products']:row['status']='collected';row['products']=len(exact);row['next_action']=None
 report['coverage_complete']=bool(coverage) and all(row['status']=='collected' for row in coverage)
 report['shop_summary']=shop_summary(offer_obs,coverage)
 for row in coverage:
  if row['status'] not in ('collected','via_comparison'):report['errors'].append({'source':row['site']+' 목록','code':row.get('code','NO_PARSEABLE_PRODUCTS')})
 if not a.dry_run:notify_status(state,report,now,config)
 # A bounded state file is the checkpoint. Daily event keys older than seven days are discarded.
 cutoff=(now-timedelta(days=7)).date().isoformat()
 state['sent']={k:v for k,v in state['sent'].items() if not k.startswith(('error:','daily:','health:','outage:')) or (k.split(':')[2][:10]>=cutoff if k.startswith('health:') else k.split(':')[1]>=cutoff)}
 # Keep only the latest delivered key per alerted model so the checkpoint stays bounded.
 latest={'top:'+m+':'+str(v) for m,v in state.get('top_alerts',{}).items()}
 state['top_alert_names']={k:v for k,v in state.get('top_alert_names',{}).items() if k in state.get('top_alerts',{})}
 state['sent']={k:v for k,v in state['sent'].items() if not k.startswith('top:') or k in latest or any(c not in v for c in enabled_channels())}
 report['status']='error' if not report['products'] and not market_products else ('partial' if report['errors'] else 'ok')
 report['notification_status']='dry_run' if a.dry_run else ('failed' if any(d['pending_channels'] for d in report['deliveries']) else 'ok')
 write_json('report.json',report)
 if not a.dry_run:write_json(state_path,state)
 print(json.dumps({'status':report['status'],'observations':len(report['products']),'market_observations':len(market_products),'coverage_complete':report['coverage_complete'],'errors':report['errors'],'email_configured':report['email_configured']},ensure_ascii=False))
 summary_path=os.environ.get('GITHUB_STEP_SUMMARY')
 if summary_path:
  with open(summary_path,'a') as f:
   f.write('## 노트북 쇼핑몰 감시 결과\n'+config['scope']+'\n\n정확한 모델 관측: '+str(len(report['products']))+'건 / 다중몰 가격 관측: '+str(len(market_products))+'건 / 오류: '+str(len(report['errors']))+'건\n\n')
   if coverage:
    f.write('| 쇼핑몰 | 결과 | 상품 관측 |\n|---|---|---:|\n')
    labels={'collected':'수집됨','blocked':'접근 제한','no_parseable_products':'파싱 미지원','error':'오류'}
    for row in coverage:f.write('| '+row['site']+' | '+labels.get(row['status'],row['status'])+' | '+str(row['products'])+' |\n')
   f.write('\n| 쇼핑몰 | 직접 수집 | 간접 가격(비교사이트) | 간접 일반가 최저 | 회원혜택 검증 |\n|---|---|---:|---:|---|\n')
   for row in report.get('shop_summary',[]):f.write('| '+row['site']+' | '+row['direct_status']+' | '+str(row['indirect_offers'])+' | '+(format(row['indirect_lowest_plain_krw'],',') if row['indirect_lowest_plain_krw'] else '-')+' | 미검증 |\n')
   f.write('\n개인별 결제액·쿠폰 발급·선착순 잔량·국내 AS는 별도 검증 전입니다. 접근 제한과 미구현을 정상 수집으로 간주하지 않습니다.\n')
 return 1 if (not report['products'] and not market_products) or report['notification_status']=='failed' else 0
if __name__=='__main__':raise SystemExit(main())

