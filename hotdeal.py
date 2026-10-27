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


def is_laptop(title, brands=DEFAULT_BRANDS):
    """노트북 본체 글이면서 제목에 허용된 메이저 제조사 브랜드가 반드시 있어야 한다."""
    import as_service
    return bool(LAPTOP.search(title)) and not ACCESSORY.search(title) and as_service.brand({'name': title}) in brands


def analyze(item, budget=(1500000, 3000000), policy=None):
    import as_service
    t = item['title']
    prices = prices_krw(t)
    price = min(prices) if prices else None
    fit = []
    if RAM_32.search(t):
        fit.append('32GB+')
    if GPU_STRONG.search(t):
        fit.append('외장/고성능 GPU')
    in_budget = price is not None and budget[0] <= price <= budget[1]
    if in_budget:
        fit.append('예산 내')
    a = as_service.assess({'name': t}, policy=policy)
    official = bool(OFFICIAL.search(t)) and not UNOFFICIAL.search(t)
    if UNOFFICIAL.search(t):
        as_line = '병행·리퍼·중고 의심 (공식 A/S 불확실)'
    elif a['domestic_brand']:
        as_line = a['brand'] + ' 국내 A/S' + (' · 공식 판매처 표기' if official else '')
    elif official:
        as_line = a['brand'] + ' · 공식/정품 판매처 표기 (미검증)'
    else:
        as_line = a['brand'] + ' · 공식 판매처 표기 없음 → 정품·보증 확인 필요'
    level = len(fit) + (1 if (official or a['domestic_brand']) and not UNOFFICIAL.search(t) else 0)
    return {**item, 'price_krw': price, 'fit': fit, 'level': level, 'brand': a['brand'],
            'official_seller': official, 'as_line': as_line, 'as_warranty': a.get('as_warranty')}


def message(d):
    shop = re.match(r'\s*\[([^\]]+)\]', d['title'])
    lines = ['[핫딜 노트북] ' + ('조건 근접: ' + ', '.join(d['fit']) if d['fit'] else '조건 정보 부족(제목 기준)'),
             d['title'],
             '판매처: ' + (shop[1] if shop else '제목 미표기') + ' · 출처: ' + d['feed'],
             '공식 A/S: ' + d['as_line']]
    if d.get('as_warranty'):
        lines.append('  보증: ' + d['as_warranty'])
    lines += ['커뮤니티 제목 기준이며 가격·쿠폰·재고·사양은 미확인입니다.', d['link']]
    return '\n'.join(lines)


def new_laptop_deals(items, seen, budget=(1500000, 3000000), policy=None, brands=DEFAULT_BRANDS):
    """Unseen laptop posts, best condition match first. Updates `seen` (list of ids, newest kept)."""
    out = []
    known = set(seen)
    for it in items:
        if it['id'] in known:
            continue
        known.add(it['id'])
        seen.append(it['id'])
        if is_laptop(it['title'], brands):
            out.append(analyze(it, budget, policy))
    del seen[:-800]
    return sorted(out, key=lambda d: -d['level'])
