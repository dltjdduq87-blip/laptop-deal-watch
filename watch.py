"""Conservative public-page watcher. No login, checkout claims or CAPTCHA bypass."""
import argparse, hashlib, html, json, math, os, re, smtplib, ssl, time
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from urllib import request, error, parse, robotparser

UA='LaptopDealWatch/1.0 (personal public-price monitor)'
ALLOWED={'www.lge.co.kr','www.samsung.com','www.11st.co.kr'}
CHANNELS=['KB국민 신용','우리 신용','KB국민 체크','하나 카카오페이 체크','하나 트래블로그 체크','카카오뱅크 체크','토스뱅크 체크','네이버페이','카카오페이']
ROBOTS={}
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
  if '@graph' in value:yield from nodes(value['@graph'])

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
   if str(p.get('model','')).upper()!=source['model'].upper():continue
  elif source.get('product_id'):
   if str(p.get('productID',''))!=source['product_id']:continue
  else:continue
  exact.append(p)
 if len(exact)!=1:raise ValueError('MODEL_MISMATCH_OR_NO_PRODUCT')
 p=exact[0];category=str(p.get('category',''))
 if '노트북' not in category and 'laptop' not in category.lower():raise ValueError('NOT_A_LAPTOP')
 offers=p.get('offers',[]);offers=[offers] if isinstance(offers,dict) else offers
 good=[]
 for o in offers:
  if o.get('@type')!='Offer' or o.get('priceCurrency')!='KRW':continue
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
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  validate_url(newurl)
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def validate_url(url):
 u=parse.urlsplit(url)
 if u.scheme!='https' or u.hostname not in ALLOWED or u.username or u.password or u.port not in (None,443):raise ValueError('UNAPPROVED_URL')

def fetch(url,robots=True):
 validate_url(url);host=parse.urlsplit(url).netloc
 if robots:
  if host not in ROBOTS:
   parser=robotparser.RobotFileParser()
   try:parser.parse(fetch('https://'+host+'/robots.txt',False).splitlines())
   except Exception:raise ValueError('ROBOTS_UNAVAILABLE') from None
   ROBOTS[host]=parser
  if not ROBOTS[host].can_fetch(UA,url):raise ValueError('ROBOTS_DISALLOWED')
 req=request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,text/plain'})
 try:
  with request.build_opener(SafeRedirect()).open(req,timeout=12) as r:
   validate_url(r.url)
   data=r.read(4000001)
   if len(data)>4000000:raise ValueError('PAGE_TOO_LARGE')
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
  call('sendMessage',{'chat_id':chat,'text':text[:4000]})
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

def main():
 args=argparse.ArgumentParser();args.add_argument('--dry-run',action='store_true');args.add_argument('--config',default='config.json');a=args.parse_args()
 config=json.loads(Path(a.config).read_text());state_path=Path('state.json')
 state=json.loads(state_path.read_text()) if state_path.exists() else {'products':{},'sent':{}}
 now=datetime.now(timezone.utc);day=now.astimezone(timezone(timedelta(hours=9))).date().isoformat()
 state.setdefault('products',{});state.setdefault('sent',{})
 report={'observed_at':now.isoformat(),'status':'partial','scope':config['scope'],'products':[],'errors':[],'unsupported':config['unsupported'],'email_configured':all(os.environ.get(x) for x in ['SMTP_HOST','SMTP_USER','SMTP_PASSWORD','EMAIL_TO'])}
 sources=list(config['sources'])
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
   raw=fetch(source['url']);p=parse_product(raw,source);p['matches_public_price_filter']=qualifies(p);p['matches_advertised_budget_filter']=qualifies_candidate(p);p['assessment']=score(p);report['products'].append(p)
   prev=state['products'].get(source['id'],{})
   key='price:'+source['id']+':'+str(candidate_price(p))+':'+str(p['price_krw'])
   retry_email = report['email_configured'] and key in state['sent'] and 'email' not in state['sent'][key]
   if not a.dry_run and qualifies_candidate(p) and (should_notify(p,prev) or retry_email):
    key='price:'+source['id']+':'+str(candidate_price(p))+':'+str(p['price_krw'])
    message=('최대혜택 기준 예산 후보 (본인 적용·실결제가 미확인)\n'+p['name']+' / '+p['model']+'\n표시가 '+format(p['price_krw'],',')+'원\n광고 최대혜택 후보가 '+format(candidate_price(p),',')+'원 (카드/간편결제 적용 미확인)\nRAM '+str(p['ram_gb'])+'GB / '+str(p['weight_kg'])+'kg\n쿠폰·카드·배송비 적용 및 실결제 미확인\n'+p['url']+'\n확인(UTC): '+p['observed_at'])
    if delivery_event(state,key,message):prev['last_notified_candidate_price']=candidate_price(p)
    else:report['errors'].append({'source':'notifications','code':'DELIVERY_FAILED'})
   prev['last_observation']=p;state['products'][source['id']]=prev
  except Exception as e:
   report['errors'].append({'source':source['id'],'code':str(e) if isinstance(e,ValueError) else type(e).__name__})
  time.sleep(.25)
 if not report['products']:report['status']='error'
 if not a.dry_run:
  error_names=', '.join(x['source']+':'+x['code'] for x in report['errors']) or '없음'
  summary=('노트북 감시 상태\n공개 가격 관측 '+str(len(report['products']))+'개 / 조건 일치 후보 '+str(sum(qualifies_candidate(p) for p in report['products']))+'개\n수집 오류: '+error_names+'\n가동 범위: '+config['scope']+'\n이메일: '+('설정됨' if report['email_configured'] else '미연결')+'\n미지원: '+', '.join(x['site'] for x in config['unsupported'])+'\n확정 실구매가·쿠폰/카드 개인 적용·AI/게임 성능 총점은 미검증입니다.')
  if not state.get('boot_sent'):
   if delivery_event(state,'boot',summary):state['boot_sent']=True
  if report['errors']:
   fingerprint=hashlib.sha256(json.dumps(report['errors'],sort_keys=True).encode()).hexdigest()[:16]
   delivery_event(state,'error:'+day+':'+fingerprint,'감시 오류 알림\n'+summary)
  kst=now.astimezone(timezone(timedelta(hours=9)))
  if kst.hour>=10:delivery_event(state,'daily:'+day,summary)
 # A bounded state file is the checkpoint. Daily event keys older than seven days are discarded.
 cutoff=(now-timedelta(days=7)).date().isoformat()
 state['sent']={k:v for k,v in state['sent'].items() if not k.startswith(('error:','daily:')) or k.split(':')[1]>=cutoff}
 Path('report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 if not a.dry_run:state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2))
 print(json.dumps({'status':report['status'],'observations':len(report['products']),'errors':report['errors'],'email_configured':report['email_configured']},ensure_ascii=False))
 summary_path=os.environ.get('GITHUB_STEP_SUMMARY')
 if summary_path:
  with open(summary_path,'a') as f:
   f.write('## Public-price monitor\nScope: '+config['scope']+'\n\nObservations: '+str(len(report['products']))+'; errors: '+str(len(report['errors']))+'\n\nPersonal checkout price, card/coupon eligibility, AI/game benchmark ranking and unsupported shops are NOT verified. See watch-state branch report.json.\n')
 return 1 if not report['products'] else 0
if __name__=='__main__':raise SystemExit(main())
