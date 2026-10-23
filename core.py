"""노트북 *수동* 가격 시뮬레이션 엔진. 외부 사이트 연결 없음."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import sqlite3
from pathlib import Path

SITES = ('쿠팡','네이버쇼핑','11번가','G마켓','옥션','SSG','하이마트','삼성닷컴','LG전자','ASUS','HP','다나와','에누리')


def won(value):
    if isinstance(value, bool):
        raise ValueError('금액은 숫자여야 합니다.')
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('금액은 숫자여야 합니다.') from None
    if not d.is_finite() or d < 0 or d != d.to_integral_value():
        raise ValueError('금액은 0 이상의 정수 원 단위여야 합니다.')
    return int(d)


@dataclass(frozen=True)
class Coupon:
    amount: int = 0
    rate_pct: int = 0
    minimum_spend: int = 0
    maximum_discount: int | None = None
    eligible: bool = False  # 쿠폰 실제 사용 가능 여부는 별도 확인


@dataclass(frozen=True)
class Quote:
    listed_price: int
    member_price: int | None = None
    coupon: Coupon = Coupon()
    immediate_card_discount: int = 0
    shipping_fee: int = 0
    statement_card_discount: int = 0
    cashback: int = 0
    points: int = 0
    member_verified: bool = False
    card_verified: bool = False
    coupon_stack_verified: bool = False


def calculate(q: Quote) -> dict:
    """시뮬레이션. 쿠폰은 회원가/정가에 적용, 즉시할인 다음 배송비 가산.

    실제 사이트의 우선순위와 스택 규정은 다를 수 있음. 이 함수는 확인된 약관을 대신하지 않음.
    """
    listed = won(q.listed_price)
    member = won(q.member_price) if q.member_price is not None else None
    base = member if (member is not None and q.member_verified) else listed
    c = q.coupon
    for a in (c.amount,c.rate_pct,c.minimum_spend,q.immediate_card_discount,q.shipping_fee,
              q.statement_card_discount,q.cashback,q.points):
        won(a)
    if c.rate_pct > 100:
        raise ValueError('할인율은 100% 이하')
    maximum = won(c.maximum_discount) if c.maximum_discount is not None else None
    # 회원가가 미확인이면 할인 조건 계산에 미검증 회원가를 절대 사용하지 않음
    coupon_allowed = c.eligible and q.coupon_stack_verified and base >= c.minimum_spend
    if coupon_allowed:
        pct = (base * c.rate_pct) // 100
        coupon_amount = c.amount + pct
        if maximum is not None:
            coupon_amount = min(coupon_amount, maximum)
        coupon_amount = min(base, coupon_amount)
    else:
        coupon_amount = 0
    after_coupon = base - coupon_amount
    immediate = min(after_coupon, q.immediate_card_discount) if q.card_verified else 0
    checkout = after_coupon - immediate + q.shipping_fee
    deferred = min(checkout, q.statement_card_discount) if q.card_verified else 0
    # 캐시백과 포인트는 결제창 실제 지불금액과 별도. 캐시백의 확정성은 검증 안 됨.
    return {
        'base': base,
        'coupon_discount': coupon_amount,
        'immediate_discount': immediate,
        'checkout_simulated': checkout,
        'statement_discount_later': deferred,
        'cashback_if_eligible': q.cashback,
        'points_if_eligible': q.points,
        'net_after_statement_simulated': checkout - deferred,
        'member_checkout_verified': False,  # 결제 직전 스크린과 직접 대조 검증 전 항상 False
        'status': '회원 실결제가 미확인',
        'notes': '쿠폰+카드 중복·배송비·할인 순서/적용 자격이 실제 결제창과 다를 수 있음',
    }


def init_db(path: str | Path):
    conn = sqlite3.connect(path)
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS observations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_utc TEXT NOT NULL,
          site TEXT NOT NULL, model_code TEXT NOT NULL, product_name TEXT NOT NULL,
          ram_gb INTEGER NOT NULL, weight_kg REAL NOT NULL, price_krw INTEGER NOT NULL,
          url TEXT NOT NULL, verification TEXT NOT NULL, notes TEXT NOT NULL
        )''')
        conn.commit()
    finally:
        conn.close()


def add_observation(path, *, site, model_code, product_name, ram_gb, weight_kg,
                    price_krw, url='', verification='수동 입력/미검증', notes=''):
    if site not in SITES:
        raise ValueError('지원 목록에 없는 사이트')
    if not model_code.strip() or not product_name.strip():
        raise ValueError('정확한 모델코드와 상품명 필요')
    if not isinstance(ram_gb,int) or isinstance(ram_gb,bool) or ram_gb <= 0:
        raise ValueError('RAM 입력 오류')
    if weight_kg <= 0 or weight_kg > 10:
        raise ValueError('무게 입력 오류')
    value=won(price_krw)
    if url and not url.startswith(('https://','http://')):
        raise ValueError('링크는 http(s) URL이어야 합니다')
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute('''INSERT INTO observations
         (observed_at_utc,site,model_code,product_name,ram_gb,weight_kg,price_krw,url,verification,notes)
         VALUES (?,?,?,?,?,?,?,?,?,?)''',
         (datetime.now(timezone.utc).isoformat(),site,model_code.strip(),product_name.strip(),
          ram_gb,weight_kg,value,url,verification,notes))


def list_observations(path):
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory=sqlite3.Row
        return [dict(x) for x in conn.execute('SELECT * FROM observations ORDER BY id DESC LIMIT 500').fetchall()]
