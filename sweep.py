"""All-manufacturer sweep of Enuri's filtered laptop list (robots-allowed /list page).

Enuri's own list filters narrow the 9,000+ laptop catalog to the buyer's conditions
(RAM 32GB+, weight under 1.7kg, price band, used/rental excluded). Pages are read in rotation
(a few per run) and cached in the state checkpoint so each run stays light for the site.
Values are comparison-site displays: not a shop login, coupon, stock or checkout verification.
"""
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

LIST = 'https://price.enuri.com/list'


def filter_url(cfg, page):
    params = {'category': cfg.get('category', '0404'), 'spec': ','.join(cfg['spec_codes']),
              'startPrice': cfg['start_price'], 'endPrice': cfg['end_price'],
              'activeOption': 'excludeUsedAndRental'}
    if page > 1:
        params['page'] = page
    return LIST + '?' + urlencode(params, safe=',')


def _flight(raw):
    out = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', raw):
        try:
            out.append(json.loads(m.group(1)))
        except ValueError:
            continue
    return ''.join(out)


def parse_list(raw):
    flight = _flight(raw)
    i = flight.find('"initProductList"')
    if i < 0:
        raise ValueError('NO_PARSEABLE_PRODUCTS')
    data, _ = json.JSONDecoder().raw_decode(flight, flight.find('{', i))
    return dict(current_page=int(data.get('currentPage') or 1), total_pages=int(data.get('totalPages') or 1),
                total=(data.get('listCount') or {}).get('catalog'), items=[x for x in data.get('items', []) if isinstance(x, dict)])


def _spec_groups(specs):
    plain, groups = [], {}
    for s in specs or []:
        if not isinstance(s, dict):
            continue
        if 'groupName' in s:
            vals = []
            for v in s.get('values', []):
                if isinstance(v, dict) and 'raw' in v:
                    vals.append(str(v['raw']))
                elif isinstance(v, dict):
                    vals += [str(x.get('raw')) for x in v.get('values', []) if isinstance(x, dict) and 'raw' in x]
            groups[s['groupName']] = vals
        else:
            plain += [str(v.get('raw')) for v in s.get('values', []) if isinstance(v, dict) and 'raw' in v]
    return plain, groups


def item_record(item, observed_at):
    model_id = str(item.get('id') or (item.get('logIds') or {}).get('modelNo') or '')
    price = (item.get('priceInfo') or {}).get('price')
    if not model_id.isdigit() or not isinstance(price, int) or price <= 0:
        return None
    plain, groups = _spec_groups(item.get('specs'))
    weight = next((float(m[1]) for v in plain for m in [re.fullmatch(r'(\d+(?:\.\d+)?)\s*kg', v.strip())] if m), None)
    ram = None
    for v in groups.get('구성', []):
        m = re.fullmatch(r'(\d+)\s*GB', v.strip())
        if m:
            ram = int(m[1])
            break
    screen = next((v for v in plain if '인치' in v), None)
    os_name = next((v for v in plain if re.search(r'윈도우|미포함|FreeDos|macOS|크롬OS|리눅스', v, re.I)), None)
    cards = []
    for c in item.get('cardPriceInfo') or []:
        if isinstance(c, dict) and isinstance(c.get('cardPrice'), int):
            cards.append({'label': str(c.get('cardName') or '카드'), 'price_krw': c['cardPrice']})
    name = str(item.get('name', '')).strip()
    option = str(item.get('condiName') or '').strip()
    url = 'https://price.enuri.com/catalog/' + model_id
    return dict(
        source_id='에누리:' + hashlib.sha256(url.encode()).hexdigest()[:16], site='에누리', model=name, model_key=name,
        name=name + (' / ' + option if option else ''), option=option, url=url, price_krw=price,
        price_type='가격비교 사이트 목록 최저가 (판매처 직접 확인 전)', ram_gb=ram, weight_kg=weight,
        cpu=' '.join(groups.get('CPU', [])) or None, gpu=' '.join(groups.get('그래픽', [])) or None,
        screen=screen, os=os_name, list_card_prices=cards, mall_count=item.get('mallCount'),
        in_stock=None if not item.get('isSoldOut') else False, is_rental=bool(item.get('isRental')),
        observed_at=observed_at, spec_source_url=url, collection_source_url=LIST,
        checkout_verified_krw=None, seller='판매자/국내 AS 검증 전', seller_verified=False,
        domestic_as_verified=False, shipping_verified_krw=None, discounts_verified=False,
        advertised_max_benefit_unverified=None)


def sweep(fetch, state, cfg, now=None, sleep=None):
    """Read `pages_per_run` pages in rotation, merge into the cached sweep, return (row, products)."""
    import time
    sleep = sleep or time.sleep
    now = now or datetime.now(timezone.utc)
    cache = state.setdefault('enuri_sweep', {})
    items = cache.setdefault('items', {})
    total_pages = int(cache.get('total_pages') or 1)
    cursor = int(cache.get('cursor') or 1)
    row = {'site': '에누리', 'url': filter_url(cfg, 1), 'status': 'pending', 'products': 0, 'coupon_verified': False,
           'personal_checkout_verified': False, 'observed_at': now.isoformat(), 'method': '조건 필터 목록 순환 수집'}
    fetched, errors = [], []
    for n in range(int(cfg.get('pages_per_run', 4))):
        page = (cursor - 1 + n) % max(total_pages, 1) + 1
        try:
            parsed = parse_list(fetch(filter_url(cfg, page)))
            total_pages = max(1, parsed['total_pages'])
            cache['total_models'] = parsed['total']
            for it in parsed['items']:
                rec = item_record(it, now.isoformat())
                if rec:
                    items[rec['url'].rsplit('/', 1)[1]] = rec
            fetched.append(page)
        except Exception as e:
            errors.append({'page': page, 'code': str(e) if isinstance(e, ValueError) else type(e).__name__})
        sleep(cfg.get('delay', 1.0))
    cache['total_pages'] = total_pages
    per_run = int(cfg.get('pages_per_run', 4))
    seen = set(cache.get('pages_this_sweep', [])) | set(fetched)
    if len(seen) >= total_pages:
        cache['sweeps_completed'] = int(cache.get('sweeps_completed', 0)) + 1
        seen = set()
    cache['pages_this_sweep'] = sorted(seen)
    cache['cursor'] = (cursor - 1 + per_run) % total_pages + 1
    if fetched:
        cache['last_success'] = now.isoformat()
    # Drop listings not re-seen recently (sold out, delisted or left the filter).
    cutoff = (now - timedelta(hours=float(cfg.get('max_age_hours', 24)))).isoformat()
    for key in [k for k, v in items.items() if v.get('observed_at', '') < cutoff]:
        items.pop(key)
    products = [dict(v) for v in items.values()]
    row.update(products=len(products), pages_read=fetched, page_errors=errors, total_pages=total_pages,
               models_in_filter=cache.get('total_models'), next_page=cache['cursor'])
    if products and fetched:
        row['status'] = 'collected'
        row['next_action'] = None
    elif products:
        row['status'] = 'collected'
        row['note'] = '이번 실행 페이지 수집 실패 · 이전 관측(최대 ' + str(cfg.get('max_age_hours', 24)) + '시간) 사용'
    else:
        row['status'] = 'blocked' if errors and str(errors[0]['code']).startswith(('ROBOTS', 'HTTP_403')) else 'error'
        row['code'] = errors[0]['code'] if errors else 'NO_PARSEABLE_PRODUCTS'
        row['next_action'] = '에누리 목록 구조 확인 필요'
    return row, products
