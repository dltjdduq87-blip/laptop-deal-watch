"""국내 A/S 점검. 공개 표시 문구만 읽으며 정품·보증을 확정하지 않는다.

- 국내 제조사(삼성·LG): 국내 서비스망 기준, 판매처 정품 문구 검사 생략.
- 해외 제조사: 상품명·판매처 목록 문구에서 '병행수입/해외구매' 신호를 찾으면 TOP·알림에서 제외,
  '정품/정식수입' 표기가 있으면 '정품 표기 확인', 아무 표기도 없으면 '정품 미확인'으로 표시하고
  구매 전 확인할 항목(유통사·제조일·보증기간)을 알림에 붙인다.
"""
import re

DOMESTIC = {'삼성', 'LG'}
BRAND_ALIASES = [
    ('삼성', r'삼성|SAMSUNG|갤럭시북|GALAXY\s*BOOK|NT\d{3}'),
    ('LG', r'\bLG\b|LG전자|그램|GRAM|\d{2}Z[D]?\d{2}'),
    ('ASUS', r'ASUS|에이수스|아수스|\bROG\b|\bTUF\b|ZENBOOK|VIVOBOOK|PROART'),
    ('레노버', r'레노버|LENOVO|LEGION|리전|THINKPAD|씽크패드|IDEAPAD|YOGA|요가'),
    ('HP', r'\bHP\b|OMEN|오멘|VICTUS|빅터스|OMNIBOOK|옴니북|ENVY|ELITEBOOK'),
    ('DELL', r'DELL|(?<![가-힣])델(?![가-힣])|ALIENWARE|에일리언웨어|XPS|INSPIRON|LATITUDE'),
    ('MSI', r'\bMSI\b|엠에스아이'),
    ('에이서', r'ACER|에이서|PREDATOR|프레데터|NITRO|SWIFT'),
    ('기가바이트', r'GIGABYTE|기가바이트|AORUS|어로스|AERO'),
    ('레이저', r'RAZER|레이저|\bBLADE\b'),
    ('애플', r'APPLE|애플|MACBOOK|맥북'),
]
PARALLEL = re.compile(r'병행\s*수입|병행|해외\s*구매|해외\s*직구|직구|해외판|글로벌\s*판|수입\s*대행|구매\s*대행|해외\s*배송|US\s*버전|미국\s*판', re.I)
GENUINE = re.compile(r'국내\s*정품|정품|정식\s*(수입|유통)|공식\s*(인증|대리|판매|스토어|몰)', re.I)
DISQUALIFY_OTHER = re.compile(r'리퍼|refurb|중고|전시\s*상품|개봉', re.I)

STATUS_ORDER = {'국내 제조사': 0, '정품 표기 확인': 1, '정품 미확인': 2, '병행수입 의심': 3}
FOREIGN_CHECKS = '판매자에게 국내 정식 유통사·제조일·무상보증 기간을 문의해 답을 캡처하고, 영수증을 보관하세요'


def brand(p):
    text = ' '.join(str(p.get(k) or '') for k in ('model_key', 'name', 'model'))
    for name, pattern in BRAND_ALIASES:
        if re.search(pattern, text, re.I):
            return name
    return '미확인'


def _texts(p, offers):
    yield str(p.get('name') or '')
    for o in offers:
        yield ' '.join(str(o.get(k) or '') for k in ('seller_name', 'product_title', 'catalog_name'))


def assess(p, offers=(), policy=None):
    """Return A/S status for a candidate from its own name and its comparison-site seller rows."""
    b = brand(p)
    info = (policy or {}).get(b, {})
    rows = [o for o in offers if not o.get('is_ad')]
    texts = list(_texts(p, rows))
    if any(o.get('is_overseas') for o in rows) and all(o.get('is_overseas') for o in rows):
        status = '병행수입 의심'
    elif any(PARALLEL.search(t) or DISQUALIFY_OTHER.search(t) for t in texts[:1]):
        status = '병행수입 의심'  # the product itself is described as parallel/refurbished
    elif b in DOMESTIC:
        status = '국내 제조사'
    elif any(GENUINE.search(t) and not PARALLEL.search(t) for t in texts):
        status = '정품 표기 확인'
    else:
        status = '정품 미확인'
    return {'brand': b, 'domestic_brand': b in DOMESTIC, 'as_status': status,
            'as_note': info.get('note'), 'as_warranty': info.get('warranty'),
            'as_checks': info.get('checks') or (None if b in DOMESTIC else FOREIGN_CHECKS)}


def allowed(a):
    return a['as_status'] != '병행수입 의심'


def tag(a):
    return {'국내 제조사': '국내AS', '정품 표기 확인': '정품표기', '정품 미확인': '정품미확인', '병행수입 의심': '병행의심'}[a['as_status']]


def message_lines(a):
    lines = ['A/S: ' + a['brand'] + ' · ' + a['as_status'] + (' (판매처 문구 기준, 미검증)' if not a['domestic_brand'] else '')]
    if a.get('as_warranty'):
        lines.append('  보증: ' + a['as_warranty'])
    if a.get('as_note'):
        lines.append('  서비스: ' + a['as_note'])
    if a.get('as_checks'):
        lines.append('  구매 전: ' + a['as_checks'])
    return '\n'.join(lines) + '\n'
