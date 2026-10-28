"""핫딜 커뮤니티 RSS 감시 (뽐뿌·루리웹). 네이버·쿠팡 쇼핑몰 안에서만 보이는 딜을 5분 안에 잡는 용도.

모델 키워드는 한정하지 않되, 제목에 메이저 제조사 브랜드(중국 기업 제외, config allowed_brands)가 반드시 있어야 한다. 각 글에 조건 근접도(32GB·외장/고성능 GPU·예산)와
공식 A/S 신호(공식 판매처 문구 + 제조사 국내 A/S 정보)를 붙인다. 글 내용·가격·쿠폰은 확인하지 않은 커뮤니티 제목 기준.
"""
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

LAPTOP = re.compile(
    r'노트북|랩탑|laptop|갤럭시\s*북|galaxy\s*book|(?<![가-힣])그램|\bgram\b|맥북|macbook|\bTUF\b|\bROG\b|젠북|zenbook|비보북|vivobook|'
    r'프로아트|레기온|리전|legion|씽크패드|thinkpad|씽크북|아이디어패드|ideapad|요가\s*(프로|슬림|\d)|yoga|오멘|omen|빅터스|victus|'
    r'옴니북|omnibook|파빌리온|에일리언웨어|alienware|\bXPS\b|인스피론|inspiron|프레데터|predator|니트로\s*v?\d|스위프트|swift\s*go|'
    r'아스파이어|aspire|크리에이터\s*M?\d|프레스티지\s*\d|스텔스\s*\d|레이더\s*\d|사이보그|cyborg|\bthin\s*15|에어로\s*\d|어로스|aorus|'
    r'레이저\s*블레이드|razer\s*blade|서피스\s*(랩탑|프로)', re.I)
ACCESSORY = re.compile(
    r'파우치|가방|백팩|거치대|스탠드|쿨러|쿨링|키보드|마우스|어댑터|충전기|보호\s*필름|필름|스킨|케이스|허브|도킹|독\b|모니터암|램\s*단품|'
    r'SSD\s*단품|메모리\s*단품|스티커|커버|리퍼\s*부품|교체용', re.I)
OFFICIAL = re.compile(r'공식|브랜드\s*스토어|공식\s*인증|인증점|공식\s*파트너|삼성닷컴|LG\s*전자\s*(공식|베스트샵)|베스트샵|정품|공식\s*몰', re.I)
UNOFFICIAL = re.compile(r'병행|해외\s*직구|직구|해외판|글로벌\s*버전|구매\s*대행|리퍼|중고|미개봉\s*중고|전시', re.I)
GPU_STRONG = re.compile(r'RTX\s*-?\s*\d{4}|Radeon\s*RX|Arc\s*B390|8060S|8050S', re.I)
RAM_32 = re.compile(r'(32|48|64|96|128)\s*(GB|G)\b', re.I)
# 쿠팡 반품마켓 등 반품 상품: 같은 성능 새 제품보다 싸게 나오는 경우가 많아 따로 표시·우선 알림
RETURN = re.compile(r'반품\s*마켓|반품\s*상품|반품\s*\(?\s*(최상|상급|상|중|S급|A급)|와우\s*반품|\(\s*반품\s*\)|\[\s*반품\s*\]|반품\s*특가|반품\s*노트북|노트북.{0,20}반품', re.I)
MODEL_CODE = re.compile(r'\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{2,}(?:-[A-Z0-9]{2,})?\b')


def model_codes(text):
    """제목/모델명에서 제조사 모델 코드 후보(NT940XJG-K72A, 16ZD90U-GX59K, 83E2002GKR 등)."""
    out = []
    for m in MODEL_CODE.finditer((text or '').upper()):
        c = m[0]
        if len(c.replace('-', '')) >= 7 and not re.fullmatch(r'\d+[A-Z]{0,3}', c.replace('-', '')) and not re.fullmatch(r'(RTX|GTX|RX)\d+', c):
            out.append(c)
    return out


BODY_START = ('class="view_content', 'class="board-contents', 'id="board-contents', 'class="board_contents')
BODY_END = ('class="comment', 'id="comment', 'class="row_comment', 'class="recommend', 'class="source_url')
RAM_BODY = re.compile(r'(?:RAM|램|메모리|LPDDR\w*|DDR\d\w*)\s*[:：]?\s*(?:LPDDR\w*|DDR\d\w*)?\s*(\d{1,3})\s*GB', re.I)
WEIGHT = re.compile(r'(\d\.\d{1,3})\s*kg', re.I)


def body_text(html_text):
    """커뮤니티 글 페이지 HTML -> 본문 텍스트만 (사이드바·댓글의 다른 딜 제외). 본문 영역을 못 찾으면 ''."""
    import html as _html
    h = html_text or ''
    starts = [h.find(m) for m in BODY_START if h.find(m) >= 0]
    if not starts:
        return ''
    seg = h[min(starts):min(starts) + 60000]
    ends = [seg.find(m, 50) for m in BODY_END if seg.find(m, 50) > 0]
    if ends:
        seg = seg[:min(ends)]
    seg = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', seg, flags=re.S | re.I)
    t = _html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', seg)))
    t = re.split(r'\s#[^\s#]+\s#', t)[0]  # 끝의 해시태그 묶음 제거
    return t[:6000].strip()


def extract_specs(text):
    """본문에서 RAM·GPU·무게·모델 코드. 확인 못 한 항목은 None."""
    t = text or ''
    ram = [int(m[1]) for m in RAM_BODY.finditer(t) if 8 <= int(m[1]) <= 128]
    gpu = GPU_STRONG.search(t)
    w = [float(m[1]) for m in WEIGHT.finditer(t) if 0.6 <= float(m[1]) <= 4]
    codes = model_codes(t)
    return {'ram_gb': max(ram) if ram else None, 'gpu': re.sub(r'\s+', ' ', gpu[0]) if gpu else None,
            'weight_kg': min(w) if w else None, 'model': codes[0] if codes else None}


def build_reference(items):
    """가격비교 수집 결과 -> {모델코드: (최저가, 이름)}. 정확한 코드와 하이픈 앞 기본 코드 둘 다 등록."""
    ref = {}
    for it in items or []:
        price = it.get('price_krw')
        if not price:
            continue
        for c in model_codes(it.get('model') or it.get('name')):
            for key in (c, 'BASE:' + c.split('-')[0]):
                if key not in ref or price < ref[key][0]:
                    ref[key] = (price, it.get('name') or it.get('model'))
    return ref


def reference_for(title, ref):
    for c in model_codes(title):
        if c in ref:
            return {'price': ref[c][0], 'name': ref[c][1], 'match': '같은 모델'}
    for c in model_codes(title):
        k = 'BASE:' + c.split('-')[0]
        if k in ref:
            return {'price': ref[k][0], 'name': ref[k][1], 'match': '같은 시리즈(옵션 다를 수 있음)'}
    return None


def parse_rss(xml_text, feed_name):
    root = ET.fromstring(xml_text.encode('utf-8') if isinstance(xml_text, str) else xml_text)
    items = []
    for it in root.iter('item'):
        title = (it.findtext('title') or '').strip()
        link = (it.findtext('link') or '').strip().replace('http://', 'https://', 1)
        guid = (it.findtext('guid') or link).strip()
        pub = it.findtext('pubDate')
        try:
            pub_iso = parsedate_to_datetime(pub).isoformat() if pub else None
        except Exception:
            pub_iso = None
        if title and link:
            items.append({'feed': feed_name, 'id': feed_name + ':' + guid, 'title': title, 'link': link, 'published': pub_iso})
    return items


def prices_krw(title):
    found = []
    for m in re.finditer(r'(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원', title):
        found.append(int(m[1].replace(',', '')))
    for m in re.finditer(r'(\d{2,3}(?:\.\d+)?)\s*만\s*(?:원|원대)?', title):
        found.append(int(float(m[1]) * 10000))
    return [p for p in found if 300000 <= p <= 10000000]


DEFAULT_BRANDS = ('삼성', 'LG', '애플', 'ASUS', 'HP', 'DELL', 'MSI', '에이서', '기가바이트', '레이저', '마이크로소프트')


def is_laptop(title, brands=DEFAULT_BRANDS, require_genuine=()):
    """노트북 본체 글이면서 제목에 허용된 메이저 제조사 브랜드가 반드시 있어야 한다."""
    import as_service
    if not LAPTOP.search(title) or ACCESSORY.search(title):
        return False
    p = {'name': title}
    if as_service.brand(p) in require_genuine:
        # 정품 확인 필수 브랜드: 제목에 정품/공식 표기나 국내 모델 코드(...KR)가 있고 병행·직구 표기가 없어야 함
        return as_service.brand(p) in brands and not UNOFFICIAL.search(title) and (bool(OFFICIAL.search(title)) or as_service.genuine_confirmed(p))
    return as_service.brand(p) in brands


def analyze(item, budget=(1500000, 3000000), policy=None, reference=None):
    import as_service
    t = item['title']
    is_return = bool(RETURN.search(t))
    prices = prices_krw(t)
    price = min(prices) if prices else None
    specs = extract_specs(item.get('body')) if item.get('body') else None
    fit = []
    if RAM_32.search(t) or (specs and (specs['ram_gb'] or 0) >= 32):
        fit.append('32GB+')
    if GPU_STRONG.search(t) or (specs and specs['gpu']):
        fit.append('외장/고성능 GPU')
    in_budget = price is not None and budget[0] <= price <= budget[1]
    if in_budget:
        fit.append('예산 내')
    a = as_service.assess({'name': t}, policy=policy)
    official = bool(OFFICIAL.search(t)) and not UNOFFICIAL.search(t)
    if is_return and not UNOFFICIAL.search(t):
        as_line = a['brand'] + (' 국내 A/S' if a['domestic_brand'] else '') + ' · 반품 상품 → 제조사 보증 적용 여부·등급·구성품은 상품 페이지 확인 필요'
    elif UNOFFICIAL.search(t):
        as_line = '병행·리퍼·중고 의심 (공식 A/S 불확실)'
    elif a['domestic_brand']:
        as_line = a['brand'] + ' 국내 A/S' + (' · 공식 판매처 표기' if official else '')
    elif official:
        as_line = a['brand'] + ' · 공식/정품 판매처 표기 (미검증)'
    else:
        as_line = a['brand'] + ' · 공식 판매처 표기 없음 → 정품·보증 확인 필요'
    level = len(fit) + (1 if (official or a['domestic_brand']) and not UNOFFICIAL.search(t) else 0)
    ref = (reference_for(t + ' ' + ((specs or {}).get('model') or ''), reference) if reference else None)
    if is_return:
        level += 2
    if ref and price and price < ref['price']:
        level += 1
    return {**item, 'price_krw': price, 'fit': fit, 'level': level, 'brand': a['brand'],
            'official_seller': official, 'as_line': as_line, 'as_warranty': a.get('as_warranty'),
            'is_return': is_return, 'reference': ref, 'specs': specs}


def message(d):
    shop = re.match(r'\s*\[([^\]]+)\]', d['title'])
    head = '[반품 노트북] ' if d.get('is_return') else '[핫딜 노트북] '
    specs = d.get('specs')
    basis = '본문' if specs else '제목'
    lines = [head + ('조건 근접: ' + ', '.join(d['fit']) if d['fit'] else '조건 정보 부족(' + basis + ' 기준)'),
             d['title'],
             '판매처: ' + (shop[1] if shop else '제목 미표기') + ' · 출처: ' + d['feed']]
    if specs and any(specs.values()):
        parts = []
        if specs['ram_gb']:
            parts.append('RAM ' + str(specs['ram_gb']) + 'GB' + ('' if specs['ram_gb'] >= 32 else ' (32GB 미만)'))
        if specs['gpu']:
            parts.append(specs['gpu'])
        if specs['weight_kg']:
            parts.append(str(specs['weight_kg']) + 'kg' + ('' if specs['weight_kg'] <= 1.6 else ' (1.6kg 초과)'))
        if specs['model']:
            parts.append(specs['model'])
        lines.append('본문 사양: ' + ' · '.join(parts))
    elif specs is not None:
        lines.append('본문 사양: 확인 못 함 → 직접 확인 필요')
    ref = d.get('reference')
    if ref:
        line = '새 제품 최저가(' + ref['match'] + '): ' + format(ref['price'], ',') + '원 · ' + str(ref['name'])[:40]
        if d.get('price_krw') and d['price_krw'] < ref['price']:
            diff = ref['price'] - d['price_krw']
            line += '\n  → 이 글 ' + format(d['price_krw'], ',') + '원, ' + format(diff, ',') + '원(' + str(round(diff * 100 / ref['price'], 1)) + '%) 낮음'
        lines.append(line)
    lines.append('공식 A/S: ' + d['as_line'])
    if d.get('as_warranty'):
        lines.append('  보증: ' + d['as_warranty'])
    lines += ['커뮤니티 글 기준이며 가격·쿠폰·재고·사양은 판매 페이지에서 최종 확인하세요.', d['link']]
    return '\n'.join(lines)


def new_laptop_deals(items, seen, budget=(1500000, 3000000), policy=None, brands=DEFAULT_BRANDS, require_genuine=(), reference=None, fetch_body=None, max_bodies=8):
    """Unseen laptop posts, best condition match first. Updates `seen` (list of ids, newest kept)."""
    out = []
    known = set(seen)
    for it in items:
        if it['id'] in known:
            continue
        known.add(it['id'])
        seen.append(it['id'])
        if is_laptop(it['title'], brands, require_genuine):
            if fetch_body and max_bodies > 0:
                max_bodies -= 1
                try:
                    it = {**it, 'body': body_text(fetch_body(it['link']))}
                except Exception:
                    it = {**it, 'body': ''}
            out.append(analyze(it, budget, policy, reference))
    del seen[:-800]
    return sorted(out, key=lambda d: -d['level'])
