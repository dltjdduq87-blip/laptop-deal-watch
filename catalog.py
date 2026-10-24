"""Bounded multi-shop catalog collection. No credential, proxy or block bypass."""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urljoin, parse_qs
from bs4 import BeautifulSoup

LAPTOP = re.compile(r'노트북|laptop|notebook|갤럭시\s*북|그램|zenbook|vivobook|thinkpad|yoga|omnibook|swift|prestige|Z북|ZBook|엘리트북|Elitebook',re.I)
ACCESSORY = re.compile(r'중고|리퍼|렌탈|수납|리빙박스|노트북용\s*(?:램|메모리)|SO.?DIMM|노트북\s*(?:파우치|가방|거치대)|DDR[345]-',re.I)


def notebook_name(name):
    return bool(LAPTOP.search(name)) and not ACCESSORY.search(name)


def walk(value):
    if isinstance(value,dict):
        yield value
        for key in ('@graph','hasVariant','itemListElement','item','mainEntity'):
            if key in value:yield from walk(value[key])
    elif isinstance(value,list):
        for item in value:yield from walk(item)


def ld_products(soup):
    result=[]
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            for p in walk(json.loads(script.string or script.get_text())):
                typ=p.get('@type',[])
                if typ=='Product' or isinstance(typ,list) and 'Product' in typ:result.append(p)
        except (ValueError,TypeError):continue
    return result


def specs(text):
    # Only explicit RAM labels or the catalog's [구성] section, never SSD/VRAM.
    ram=re.search(r'(?:\[구성\]|(?<![A-Za-z])RAM|메모리\s*용량|램)\s*[:|]?\s*(\d+)\s*GB',text,re.I)
    weight=re.search(r'(?<![\d.])(\d+(?:\.\d+)?)\s*kg\b',text,re.I)
    cpu=re.search(r'\[CPU\]\s*(.*?)(?=\[그래픽\]|$)',text)
    gpu=re.search(r'\[그래픽\]\s*(.*?)(?=\[구성\]|$)',text)
    return dict(ram_gb=int(ram[1]) if ram else None,weight_kg=float(weight[1]) if weight else None,
                cpu=cpu[1].strip(' /') if cpu else None,gpu=gpu[1].strip(' /') if gpu else None)


def base_record(site,source_url,raw,*,name,model,url,price,spec_text='',stock=None):
    return dict(source_id=site+':'+hashlib.sha256(url.encode()).hexdigest()[:16],site=site,
        model=model,name=name,url=url,price_krw=price,price_type='가격비교 사이트 공개가 (판매처 직접 확인 전)' if site in ('다나와','에누리') else '공개 표시가',
        checkout_verified_krw=None,advertised_max_benefit_unverified=None,
        observed_at=datetime.now(timezone.utc).isoformat(),html_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        spec_source_url=source_url,collection_source_url=source_url,in_stock=stock,
        seller='판매자/국내 AS 검증 전',seller_verified=False,domestic_as_verified=False,
        shipping_verified_krw=None,discounts_verified=False,**specs(spec_text))


def parse_catalog(raw,site,url):
    soup=BeautifulSoup(raw,'html.parser');result=[]
    if site=='HP':
        for card in soup.select('li.product-item'):
            link=card.select_one('.product-item-name .product-item-link')
            info=card.select_one('.product-item-info[data-price-amount]')
            sku=card.select_one('[data-sku]')
            if not link or not info or not sku:continue
            if 'laptops' not in info.get('data-category','').lower():continue
            try:
                amount=float(info['data-price-amount'])
                if amount<=0 or amount!=int(amount):continue
            except (TypeError,ValueError):continue
            record=base_record(site,url,raw,name=link.get_text(' ',strip=True),model=sku['data-sku'],
                url=urljoin(url,link['href']),price=int(amount))
            record['seller']='제조사 공식몰';record['seller_verified']=True
            result.append(record)
    if site in ('G마켓','옥션'):
        script=soup.select_one('#__NEXT_DATA__')
        if script:
            def items(value):
                if isinstance(value,dict):
                    if 'itemNo' in value and ('commonItemInfo' in value or 'item' in value):yield value
                    for v in value.values():yield from items(v)
                elif isinstance(value,list):
                    for v in value:yield from items(v)
            try:
                for p in items(json.loads(script.string or script.get_text())):
                    info=p.get('commonItemInfo',p);item=info.get('item',{});name=item.get('text','')
                    if not notebook_name(name):continue
                    text=info.get('price',{}).get('binPrice','')
                    if not re.fullmatch(r'[\d,]+',str(text)):continue
                    target=item.get('link','');parts=urlsplit(target)
                    if parts.hostname not in ('item.gmarket.co.kr','itempage3.auction.co.kr'):continue
                    # Keep only the observed product identifier; discard ad/session tracking.
                    q=parse_qs(parts.query);wanted='goodscode' if site=='G마켓' else 'itemno'
                    ids=[v[0] for k,v in q.items() if k.lower()==wanted]
                    if len(ids)!=1:continue
                    target='https://'+parts.netloc+parts.path+'?'+wanted+'='+ids[0]
                    record=base_record(site,url,raw,name=name,model=info.get('modelName') or None,url=target,
                                       price=int(str(text).replace(',','')),spec_text=name)
                    record['product_id']=str(p['itemNo']);record['seller_name']=info.get('seller',{}).get('text')
                    result.append(record)
            except (ValueError,TypeError):pass
    if site=='다나와':
        for card in soup.select('[data-testid="ProductListItem"]'):
            title=card.select_one('[data-testid="ProductListTitle"] a')
            detail=card.select_one('[data-testid="ProductListSpecs"]')
            if not title or not detail:continue
            name=title.get_text(' ',strip=True)
            if not notebook_name(name):continue
            spec_text=detail.get_text(' ',strip=True)
            # Bind each price to its own storage-option URL, not a global minimum.
            for anchor in card.select('a[aria-label][href]'):
                label=anchor.get('aria-label','');m=re.search(r'([\d,]+)\s*원$',label)
                if not m or 'pcode=' not in anchor['href']:continue
                price=int(m[1].replace(',',''))
                result.append(base_record(site,url,raw,name=name+' / '+label[:m.start()].strip(),
                    model=name,url=urljoin(url,anchor['href']),price=price,spec_text=spec_text))
    for p in ld_products(soup):
        name=p.get('name','')
        enuri_notebook_list=site=='에누리' and parse_qs(urlsplit(url).query).get('cate')==['0404']
        if not notebook_name(name) and not (enuri_notebook_list and not ACCESSORY.search(name)):continue
        model=str(p.get('model') or p.get('sku') or p.get('productID') or '')
        if not model:continue
        offers=p.get('offers',[]);offers=[offers] if isinstance(offers,dict) else offers
        good=[o for o in offers if isinstance(o,dict) and o.get('@type') in ('Offer','AggregateOffer') and o.get('priceCurrency')=='KRW']
        if len(good)!=1:continue
        offer=good[0]
        try:
            value=str(offer['lowPrice'] if offer.get('@type')=='AggregateOffer' else offer['price']).replace(',','');price=int(value)
            if price<=0 or str(price)!=value:continue
        except (KeyError,ValueError,TypeError):continue
        target=urljoin(url,offer.get('url') or p.get('url') or '')
        enuri_hosts={'www.enuri.com','enuri.com','m.enuri.com','price.enuri.com'}
        same_shop=urlsplit(target).hostname==urlsplit(url).hostname or (site=='에누리' and urlsplit(target).hostname in enuri_hosts)
        if urlsplit(target).scheme!='https' or not same_shop:continue
        # A shared catalog URL cannot identify several distinct SKU offers.
        if not offer.get('url') and not p.get('url'):continue
        props=p.get('additionalProperty',[]);props=[props] if isinstance(props,dict) else props
        prop_text=' '.join(str(x.get('name',''))+' '+str(x.get('value','')) for x in props if isinstance(x,dict))
        record=base_record(site,url,raw,name=name,model=model,url=target,price=price,spec_text=prop_text,
            stock=str(offer.get('availability','')).endswith('/InStock') if offer.get('availability') else None)
        if offer.get('@type')=='AggregateOffer':
            record['price_type']='가격비교 사이트 집계 최저가 (판매처 직접 확인 전)';record['in_stock']=None
        if site=='삼성':
            ram=re.search(r'\|(\d+)GB\|',name)
            if ram:record['ram_gb']=int(ram[1])
            record['seller']='제조사 공식몰'
            record['seller_verified']=True
        elif site in ('HP','ASUS'):record['seller']='제조사 공식몰';record['seller_verified']=True
        weight=p.get('weight',{})
        if isinstance(weight,dict):
            try:
                w=float(weight.get('value'))
                if weight.get('unitCode')=='KGM':record['weight_kg']=w
                elif weight.get('unitCode')=='GRM':record['weight_kg']=w/1000
            except (TypeError,ValueError):pass
        result.append(record)
    return list({(p['site'],p['url'],p['model']):p for p in result}.values())


def review_candidate(p):
    return (isinstance(p.get('ram_gb'),int) and p['ram_gb']>=32 and
        isinstance(p.get('weight_kg'),(float,int)) and 0<p['weight_kg']<=1.6 and
        1500000<=p['price_krw']<=3000000)


def price_band(value):
    if 1500000<=value<1900000:return '150~190만원'
    if 1900000<=value<2300000:return '190~230만원'
    if 2300000<=value<=3000000:return '230~300만원'
    return '예산 밖'


def scan(config,fetch):
    from concurrent.futures import ThreadPoolExecutor
    def collect(shop):
        row={'site':shop['site'],'url':shop['url'],'status':'pending','products':0,'coupon_verified':False,
             'personal_checkout_verified':False,'observed_at':datetime.now(timezone.utc).isoformat()}
        try:
            raw=fetch(shop['url']);products=parse_catalog(raw,shop['site'],shop['url'])
            row['products']=len(products);row['status']='collected' if products else 'no_parseable_products'
            row['next_action']=None if products else '상품별 구조화 데이터 또는 허용된 상품 피드 연동 필요'
            return row,products
        except Exception as e:
            row['status']='blocked' if str(e).startswith(('ROBOTS','HTTP_403','HTTP_405')) else 'error'
            row['code']=str(e) if isinstance(e,ValueError) else type(e).__name__
            row['next_action']=shop.get('access_requirement','공개 상품 피드 또는 공식 API 연결 필요')
            return row,[]
    rows=[];products=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for row,found in pool.map(collect,config.get('catalogs',[])):
            rows.append(row);products.extend(found)
    return rows,products
