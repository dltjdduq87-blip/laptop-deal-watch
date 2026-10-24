"""Indirect seller-level prices from price-comparison detail pages (Danawa, Enuri).

These are *indirect* observations: the comparison site's display of a seller's price.
They never prove a shop login, a coupon issue, stock, seller trust or a checkout amount.
Only robots-allowed detail pages are read; Danawa /info/ajax/ and Enuri /api/ are not used.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs

from bs4 import BeautifulSoup

# Comparison-site seller names mapped to the 13 watched targets. Exact names only:
# a Naver Pay icon or "네이버페이" text never makes a seller 네이버쇼핑.
SHOP_ALIASES = {
    '11번가': '11번가', 'G마켓': 'G마켓', '지마켓': 'G마켓', '옥션': '옥션',
    'SSG.COM': 'SSG', 'SSG': 'SSG', '쓱닷컴': 'SSG', '쿠팡': '쿠팡',
    '롯데하이마트': '롯데하이마트', '하이마트': '롯데하이마트',
    '삼성전자': '삼성', '삼성닷컴': '삼성', '삼성전자 공식': '삼성',
    'LG전자': 'LG', 'LG전자 공식': 'LG', 'HP': 'HP', 'HP 공식': 'HP',
    'ASUS': 'ASUS', '에이수스': 'ASUS', '네이버쇼핑': '네이버쇼핑',
}
TARGETS = ['네이버쇼핑', '쿠팡', '11번가', 'G마켓', '옥션', 'SSG', '롯데하이마트', '삼성', 'LG', 'ASUS', 'HP', '다나와', '에누리']

CREDIT_ISSUERS = {'KB국민', '우리'}
CHECK_ONLY_ISSUERS = {'하나', '카카오뱅크', '토스뱅크'}  # KB국민 also has a check card
EASY_PAY = {'네이버페이', '카카오페이'}
ISSUER_PATTERNS = [('KB국민', r'KB|국민'), ('우리', r'우리'), ('하나', r'하나'), ('카카오뱅크', r'카카오뱅크'),
                   ('토스뱅크', r'토스뱅크'), ('네이버페이', r'네이버\s*페이|N\s*pay'), ('카카오페이', r'카카오\s*페이')]


def map_shop(name):
    name = re.sub(r'\s+', ' ', (name or '')).strip()
    return SHOP_ALIASES.get(name)


def card_applicability(label):
    """Classify a card-conditional price against the buyer's wallet. Never verifies it."""
    found = {issuer for issuer, pattern in ISSUER_PATTERNS if re.search(pattern, label or '')}
    if found & CREDIT_ISSUERS:
        return '보유 신용카드사(KB국민/우리) 포함 가능 · 대상카드·실적·한도 미확인'
    if '하나' in found or found & {'카카오뱅크', '토스뱅크'}:
        return '보유 카드는 체크카드뿐 · 신용카드 행사면 해당 없음 · 미확인'
    if found & EASY_PAY:
        return '보유 간편결제 조건 · 적용 미확인'
    return '보유 결제수단 아님'


def offer_record(aggregator, detail_url, *, seller, price, catalog_name, shipping_krw=None, shipping_text='',
                 price_condition='일반 판매가', conditional_prices=(), listing_id=None, product_title=None,
                 naver_pay_badge=False, is_ad=None, is_overseas=None, reward=None, seller_code=None):
    key = '|'.join([aggregator, detail_url, str(seller_code or seller), str(listing_id or ''), str(price), price_condition])
    return dict(
        offer_id=aggregator + ':' + hashlib.sha256(key.encode()).hexdigest()[:16],
        evidence_type='indirect_comparison_site', aggregator=aggregator, detail_url=detail_url,
        catalog_name=catalog_name, seller_name=seller, target_shop=map_shop(seller), seller_code=seller_code,
        listing_id=listing_id, product_title=product_title, price_krw=price, price_condition=price_condition,
        conditional_prices=list(conditional_prices), shipping_krw=shipping_krw, shipping_text=shipping_text,
        naver_pay_badge=naver_pay_badge, is_ad=is_ad, is_overseas=is_overseas, reward_separate=reward,
        observed_at=datetime.now(timezone.utc).isoformat(),
        shop_login_verified=False, coupon_verified=False, stock_verified=False,
        seller_verified=False, domestic_as_verified=False, checkout_verified_krw=None)


def _int(value):
    try:
        text = str(value).replace(',', '').strip()
        n = int(text)
        return n if n > 0 and str(n) == text else None
    except (TypeError, ValueError):
        return None


def _shipping(text, data_value=None):
    if data_value not in (None, ''):
        v = str(data_value).strip()
        if v == '0':
            return 0
        return _int(v)
    if re.search(r'무료\s*배송', text or ''):
        return 0
    m = re.search(r'배송비\s*([\d,]+)\s*원', text or '')
    return _int(m[1]) if m else None


def detail_specs(soup):
    """Specs from the detail page's own Product JSON-LD description. Missing stays None."""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict) and node.get('@type') == 'Product':
                desc = str(node.get('description', ''))
                ram = re.search(r'\[구성\]\s*[/:|]?\s*(\d+)\s*GB', desc, re.I)
                weight = re.search(r'(?<![\d.])(\d+(?:\.\d+)?)\s*kg\b', desc, re.I)
                offers = node.get('offers') if isinstance(node.get('offers'), dict) else {}
                return dict(name=str(node.get('name', '')), ram_gb=int(ram[1]) if ram else None,
                            weight_kg=float(weight[1]) if weight else None,
                            offer_count=_int(offers.get('offerCount')), low_price=_int(offers.get('lowPrice')))
    return dict(name='', ram_gb=None, weight_kg=None, offer_count=None, low_price=None)


def parse_danawa_offers(raw, url):
    soup = BeautifulSoup(raw, 'html.parser')
    meta = detail_specs(soup)
    result = []
    for li in soup.select('#lowPriceCompanyArea ul.list__mall-price > li.list-item'):
        logo = li.select_one('.box__logo')
        if not logo:
            continue
        img = logo.select_one('img[alt]')
        text_logo = logo.select_one('.text__logo')
        seller = (img.get('alt') if img else None) or (text_logo.get('aria-label') or text_logo.get_text(strip=True) if text_logo else '')
        seller = (seller or '').strip()
        box = li.select_one('.box__price')
        sell = li.select_one('.sell-price')
        if not seller or not box or not sell:
            continue
        price = _int(sell.get('data-base-price')) or _int((sell.select_one('.text__num') or sell).get_text(strip=True))
        if not price:
            continue
        badges = [b.get_text(strip=True) for b in box.select('[class*="badge__"]') if 'badge__lowest' not in b.get('class', [])]
        condition = '일반 판매가'
        conditional = []
        if any('현금' in b for b in badges):
            condition = '현금가 (결제수단 조건부)'
        elif any('카드' in b for b in badges):
            condition = '카드할인가 (조건부)'
            conditional.append({'label': ' '.join(badges), 'price_krw': price, 'buyer_applicability': card_applicability(' '.join(badges))})
        elif badges:
            condition = '조건부 표시가 (' + ' '.join(badges) + ')'
        delivery = li.select_one('.box__delivery')
        for layer in (delivery.select('.layer-prod-pdb1') if delivery else []):
            layer.extract()
        shipping_text = re.sub(r'\s+', ' ', delivery.get_text(' ', strip=True)) if delivery else ''
        link = li.select_one('a.link__full-cover[href]')
        q = parse_qs(urlsplit(link['href']).query) if link else {}
        result.append(offer_record('다나와', url, seller=seller, price=price, catalog_name=meta['name'],
            shipping_krw=_shipping(shipping_text, sell.get('data-delivery-price')), shipping_text=shipping_text,
            price_condition=condition, conditional_prices=conditional,
            listing_id=(q.get('link_pcode') or [None])[0], seller_code=(q.get('cmpnyc') or [None])[0],
            naver_pay_badge=bool(logo.select_one('.icon__npay'))))
    return meta, dedupe(result)


def _flight_text(raw):
    chunks = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', raw):
        try:
            chunks.append(json.loads(m.group(1)))
        except ValueError:
            continue
    return ''.join(chunks)


def parse_enuri_offers(raw, url):
    soup = BeautifulSoup(raw, 'html.parser')
    meta = detail_specs(soup)
    flight = _flight_text(raw)
    decoder = json.JSONDecoder()
    rows = []
    for m in re.finditer(r'"priceList"\s*:\s*\[', flight):
        try:
            arr, _ = decoder.raw_decode(flight, m.end() - 1)  # starts at '['
        except ValueError:
            continue
        # The seller table carries productName per listing; the header widget does not.
        if arr and all(isinstance(x, dict) and 'productName' in x for x in arr):
            rows = arr
            break
    result = []
    for x in rows:
        price = _int(x.get('price'))
        seller = str(x.get('shopName') or '').strip()
        if not price or not seller:
            continue
        conditional = []
        cards = x.get('cardInfo') if isinstance(x.get('cardInfo'), list) else []
        if not cards and x.get('cardPrice'):
            cards = [{'price': x.get('cardPrice'), 'name': x.get('cardName')}]
        for c in cards:
            if isinstance(c, dict) and _int(c.get('price')):
                conditional.append({'label': str(c.get('name') or '카드'), 'price_krw': _int(c.get('price')),
                                    'buyer_applicability': card_applicability(str(c.get('name') or ''))})
        reward = x.get('rewardInfo') if isinstance(x.get('rewardInfo'), dict) and x['rewardInfo'].get('amount') else None
        shipping = x.get('deliveryPrice')
        result.append(offer_record('에누리', url, seller=seller, price=price, catalog_name=meta['name'],
            shipping_krw=shipping if isinstance(shipping, int) and shipping >= 0 else _shipping(x.get('deliveryText')),
            shipping_text=str(x.get('deliveryText') or ''),
            price_condition='일반 판매가' if not x.get('isDeliveryCash') else '일반 판매가 (배송비 현장/착불 표시)',
            conditional_prices=conditional, listing_id=str(x.get('plno') or '') or None,
            product_title=str(x.get('productName') or '')[:200], is_ad=bool(x.get('isAd')),
            is_overseas=bool(x.get('isOverseas')), reward=reward, seller_code=str(x.get('shopCode') or '') or None))
    return meta, dedupe(result)


def dedupe(offers):
    seen = {}
    for o in offers:
        seen.setdefault((o['aggregator'], o['seller_code'] or o['seller_name'], o['listing_id'], o['price_krw'], o['price_condition']), o)
    return list(seen.values())


def detail_url(product):
    """Robots-allowed detail page for a list observation, or None."""
    parts = urlsplit(product.get('url', ''))
    q = parse_qs(parts.query)
    if product.get('site') == '다나와' and parts.hostname == 'prod.danawa.com' and parts.path == '/info/' and q.get('pcode'):
        pcode = q['pcode'][0]
        if pcode.isdigit():
            return 'https://prod.danawa.com/info/?pcode=' + pcode + ('&cate=' + q['cate'][0] if q.get('cate', [''])[0].isdigit() else '')
    if product.get('site') == '에누리':
        m = re.fullmatch(r'/catalog/(\d+)', parts.path or '')
        model = m[1] if m and parts.hostname == 'price.enuri.com' else (q.get('modelno') or [''])[0]
        if model.isdigit():
            return 'https://price.enuri.com/catalog/' + model
    return None


def baseline_offer(offers):
    """Lowest unconditional, domestic, non-ad listing price. Not a checkout amount."""
    plain = [o for o in offers if o['price_condition'].startswith('일반 판매가') and not o.get('is_ad') and not o.get('is_overseas')]
    return min(plain, key=lambda o: o['price_krw']) if plain else None


def apply_spec_cache(market_products, cache):
    """Reuse specs read from a detail page in an earlier run (state checkpoint)."""
    for p in market_products:
        c = cache.get(detail_url(p) or '')
        if not c:
            continue
        if p.get('ram_gb') is None and c.get('ram_gb'):
            p['ram_gb'] = c['ram_gb']; p['spec_source_url'] = detail_url(p); p['spec_cached_at'] = c.get('observed_at')
        if p.get('weight_kg') is None and c.get('weight_kg'):
            p['weight_kg'] = c['weight_kg']; p['spec_source_url'] = detail_url(p); p['spec_cached_at'] = c.get('observed_at')


def update_spec_cache(cache, details, keep=300):
    for d in details:
        if d.get('detail_ram_gb') or d.get('detail_weight_kg'):
            cache[d['detail_url']] = {'ram_gb': d.get('detail_ram_gb'), 'weight_kg': d.get('detail_weight_kg'),
                                      'observed_at': datetime.now(timezone.utc).isoformat()}
    if len(cache) > keep:
        for key in sorted(cache, key=lambda k: cache[k].get('observed_at', ''))[:len(cache) - keep]:
            cache.pop(key, None)
    return cache


APPLICABLE_PREFIXES = ('보유 신용카드사', '보유 간편결제')


def buyer_estimate(offers):
    """Lowest price this buyer could plausibly pay, from public data only.

    Uses the lowest plain listing (+ known shipping) and card/easy-pay prices whose issuer matches
    the buyer's wallet (KB국민/우리 credit, Naver/Kakao Pay). Never verified: issuer match does not
    prove the specific card, monthly spend, limit or period. Cash-only prices are excluded.
    """
    base = baseline_offer(offers)
    best = None
    if base:
        best = dict(estimated_krw=base['price_krw'] + (base['shipping_krw'] or 0), basis='공개 최저 판매가',
                    seller=base['seller_name'], condition=None)
    for o in offers:
        if o.get('is_ad') or o.get('is_overseas'):
            continue
        for c in o.get('conditional_prices', []):
            if not str(c.get('buyer_applicability', '')).startswith(APPLICABLE_PREFIXES):
                continue
            total = c['price_krw'] + (o['shipping_krw'] or 0)
            if best is None or total < best['estimated_krw']:
                best = dict(estimated_krw=total, basis='보유 결제수단 조건가', seller=o['seller_name'],
                            condition=c['label'] + ' · ' + c['buyer_applicability'])
    if best is None:
        return None
    best.update(base_krw=base['price_krw'] if base else None, base_seller=base['seller_name'] if base else None,
                shipping_known=bool(base and base['shipping_krw'] is not None), verified=False,
                note='공개 정보 기반 예상가 · 쿠폰·멤버십·카드 실적/한도·재고 미확인')
    return best


def attach_estimates(market_products, offers):
    by_list = {}
    for o in offers:
        by_list.setdefault(o.get('list_source_id'), []).append(o)
    for p in market_products:
        est = buyer_estimate(by_list.get(p.get('source_id'), []))
        if est:
            p['buyer_estimate'] = est


def effective_price(p):
    """Price used for budget/alerts: the lower of the list price and the public-data estimate."""
    est = (p.get('buyer_estimate') or {}).get('estimated_krw')
    return min(p['price_krw'], est) if isinstance(est, int) and est > 0 else p['price_krw']


def select_details(market_products, budget=(1500000, 3000000), limit_per_site=8):
    picked = []
    for site in ('다나와', '에누리'):
        rows = []
        for p in market_products:
            if p.get('site') != site or not (budget[0] <= p.get('price_krw', 0) <= budget[1]):
                continue
            # Known disqualifying specs are skipped; unknown specs get a detail visit to fill them.
            if isinstance(p.get('ram_gb'), int) and p['ram_gb'] < 32:
                continue
            if isinstance(p.get('weight_kg'), (int, float)) and p['weight_kg'] > 1.6:
                continue
            url = detail_url(p)
            if url and url not in {u for _, u in rows}:
                rows.append((p, url))
        rows.sort(key=lambda r: r[0]['price_krw'])
        picked.extend(rows[:limit_per_site])
    return picked


def collect_offers(market_products, fetch, *, limit_per_site=8, delay=1.0, sleep=time.sleep):
    """Visit a bounded number of detail pages. Returns (details, offers, errors)."""
    details, offers, errors = [], [], []
    for product, url in select_details(market_products, limit_per_site=limit_per_site):
        try:
            raw = fetch(url)
            parser = parse_danawa_offers if product['site'] == '다나와' else parse_enuri_offers
            meta, found = parser(raw, url)
            for o in found:
                o['list_source_id'] = product['source_id']
            base = baseline_offer(found)
            details.append(dict(list_source_id=product['source_id'], aggregator=product['site'], detail_url=url,
                catalog_name=meta['name'] or product.get('name'), detail_ram_gb=meta['ram_gb'], detail_weight_kg=meta['weight_kg'],
                site_offer_count=meta['offer_count'], offers_read=len(found),
                baseline_price_krw=base['price_krw'] if base else None, baseline_seller=base['seller_name'] if base else None,
                status='collected' if found else 'no_seller_rows',
                note='초기 페이지에 표시된 판매처만 읽음 (전체 ' + str(meta['offer_count'] or '?') + '곳 중 일부)'))
            offers.extend(found)
        except Exception as e:
            errors.append({'source': product['site'] + ' 상세', 'url': url, 'code': str(e) if isinstance(e, ValueError) else type(e).__name__})
        sleep(delay)
    return details, offers, errors


def enrich_specs(market_products, details):
    """Fill missing RAM/weight on list observations from the matching detail page's own spec text."""
    by_id = {d['list_source_id']: d for d in details}
    for p in market_products:
        d = by_id.get(p.get('source_id'))
        if not d:
            continue
        if p.get('ram_gb') is None and d.get('detail_ram_gb'):
            p['ram_gb'] = d['detail_ram_gb']; p['spec_source_url'] = d['detail_url']
        if p.get('weight_kg') is None and d.get('detail_weight_kg'):
            p['weight_kg'] = d['detail_weight_kg']; p['spec_source_url'] = d['detail_url']
        if d.get('baseline_price_krw'):
            p['seller_baseline_price_krw'] = d['baseline_price_krw']
            p['seller_baseline_name'] = d['baseline_seller']


def shop_summary(offers, coverage):
    """Per-target view separating direct collection, indirect comparison-site prices and member checks."""
    direct = {r['site']: r for r in coverage}
    rows = []
    for shop in TARGETS:
        mine = [o for o in offers if o['target_shop'] == shop]
        plain = [o for o in mine if o['price_condition'].startswith('일반 판매가')]
        d = direct.get(shop, {})
        rows.append(dict(site=shop, direct_status=d.get('status', 'not_configured'), direct_products=d.get('products', 0),
            indirect_offers=len(mine), indirect_models=len({o['detail_url'] for o in mine}),
            indirect_lowest_plain_krw=min((o['price_krw'] for o in plain), default=None),
            member_benefit_verified=False))
    return rows
