"""관심 모델 감시: 예산·등급과 무관하게 지정한 모델·같은 성능 제품군의 최저가 하락을 알린다.

그룹은 이름 패턴(모델 코드) 또는 CPU 패턴으로 묶는다. 메이저 브랜드·해외 브랜드 국내 정품 조건은
적용하되, 정품 신호가 없는 해외 브랜드는 빼지 않고 '국내 정품·A/S 확인 필요'로 표시한다. 기준가는 최근 7일 최저가이며, 그보다 내려갈 때만 알린다
(판매처가 바뀌며 가격이 오르내릴 때 같은 가격을 '할인'으로 반복 알리지 않도록).
첫 관측은 등록 알림 1회. 가격은 가격비교 사이트 표시가이며 쿠폰·카드·실결제는 미확인.
"""
import re
from datetime import datetime, timedelta, timezone

BASELINE_DAYS = 7


def members(group, products, brands=None, require_genuine=()):
    import as_service
    name_re = re.compile(group['name_pattern'], re.I) if group.get('name_pattern') else None
    cpu_re = re.compile(group['cpu_pattern'], re.I) if group.get('cpu_pattern') else None
    out, keys = [], set()
    for p in products:
        price = p.get('effective_price_krw') or p.get('price_krw')
        if not price or p.get('in_stock') is False:
            continue
        hit = (name_re and name_re.search(str(p.get('name') or '') + ' ' + str(p.get('model') or ''))) or (cpu_re and cpu_re.search(str(p.get('cpu') or '')))
        if not hit:
            continue
        if group.get('max_weight') and not (p.get('weight_kg') and p['weight_kg'] <= group['max_weight']):
            continue
        if group.get('min_ram') and p.get('ram_gb') is not None and p['ram_gb'] < group['min_ram']:
            continue
        ram_unknown = bool(group.get('min_ram')) and p.get('ram_gb') is None
        if not as_service.brand_ok(p, brands):
            continue  # 메이저 브랜드만
        if as_service.assess(p).get('as_status') == '병행수입 의심':
            continue
        # 해외 브랜드는 빼지 않고 '국내 정품 확인 필요' 표시 (기본 알림의 확인 대기 처리와 같은 취지)
        needs_check = as_service.brand(p) in require_genuine and not as_service.genuine_confirmed(p)
        key = (p.get('url') or p.get('name'), price)
        if key in keys:
            continue
        keys.add(key)
        out.append({**p, '_price': price, '_needs_genuine_check': needs_check, '_ram_unknown': ram_unknown})
    return sorted(out, key=lambda p: p['_price'])


def coupon_estimate(p, coupon_events, today):
    """LG 공식몰 등 행사 쿠폰 구간표로 계산한 '쿠폰 적용 시 예상가'. 발급·적용 자격은 미확인."""
    price = p.get('_price') or p.get('price_krw')
    for ev in coupon_events or []:
        tiers = ev.get('coupon_tiers')
        if not tiers or not price or p.get('site') != ev.get('coupon_site'):
            continue
        if not (ev['start'][:10] <= today <= ev['end'][:10]):
            continue
        off = max((amt for floor, amt in tiers if price >= floor), default=0)
        if off:
            return price - off, off, ev
    return None


def fresh_official(state_products, now=None, max_age_hours=72):
    """직전 실행들에서 수집한 LG 공식몰 관측 중 최근·재고 있음만 (오래된 가격이 최저가로 남지 않게)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for v in (state_products or {}).values():
        o = (v or {}).get('last_observation') if isinstance(v, dict) else None
        if not o or o.get('site') != 'LG' or not o.get('cpu') or o.get('in_stock') is False:
            continue
        try:
            at = datetime.fromisoformat(o['observed_at'])
            at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if now - at <= timedelta(hours=max_age_hours):
            out.append(o)
    return out


def won(v):
    return format(v, ',') + '원'


def _entry(entry):
    """state 항목 -> (low, at). 예전 형식(int)은 오래된 기록으로 취급해 곧 재설정되게 한다."""
    if entry is None:
        return None, None
    if isinstance(entry, (int, float)):
        return int(entry), datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        at = datetime.fromisoformat(entry['at'])
        return entry.get('low'), (at if at.tzinfo else at.replace(tzinfo=timezone.utc))
    except Exception:
        return entry.get('low'), datetime(1970, 1, 1, tzinfo=timezone.utc)


def due(groups, products, state, brands=None, require_genuine=(), now=None, report=None, coupon_events=None):
    """[(key, message, group_id, price)] — 기준가보다 싸진 그룹(또는 첫 관측).

    state 갱신은 호출자가 전송 성공 후 commit()으로 한다(전송 실패 시 다음 실행에 재시도).
    """
    now = now or datetime.now(timezone.utc)
    seen = state.setdefault('watch_groups', {})
    alerts, counts = [], {}
    for g in groups or []:
        ms = members(g, products, brands, require_genuine)
        counts[g['id']] = len(ms)
        if not ms:
            continue
        best = ms[0]
        low, at = _entry(seen.get(g['id']))
        if low is not None and best['_price'] >= low:
            if best['_price'] == low:
                seen[g['id']] = {'low': low, 'at': now.isoformat()}  # 최저가 유지 중: 기준 갱신
            elif now - at > timedelta(days=BASELINE_DAYS):
                seen[g['id']] = {'low': best['_price'], 'at': now.isoformat()}  # 7일 넘게 그 가격 없음: 현재가로 재설정
            continue
        base = low  # None이면 첫 관측(등록), 아니면 기준가보다 싸진 것(7일 지난 기준이라도 더 싸면 알림)
        lines = ['[관심 모델] ' + g['label']]
        if base is None:
            lines.append('감시 등록 · 현재 최저가 ' + won(best['_price']))
        else:
            diff = base - best['_price']
            lines.append('이전 최저가(7일) ' + won(base) + ' → 현재가 ' + won(best['_price']))
            lines.append('▼ ' + won(diff) + ' (' + format(diff * 100 / base, '.1f') + '% 할인)')
        if g.get('note'):
            lines.append(g['note'])
        lines.append('저가 상위:')
        today = now.astimezone(timezone(timedelta(hours=9))).date().isoformat()
        for p in ms[:3]:
            lines.append('· ' + won(p['_price']) + ' ' + str(p.get('name'))[:55] + (' ' + str(p['weight_kg']) + 'kg' if p.get('weight_kg') else '')
                         + (' · 국내 정품·A/S 확인 필요' if p.get('_needs_genuine_check') else '')
                         + (' · RAM 미확인' if p.get('_ram_unknown') else ''))
            est = coupon_estimate(p, coupon_events, today)
            if est:
                lines.append('  └ ' + est[2]['name'] + ' 쿠폰 ' + won(est[1]) + ' 적용 시 예상 ' + won(est[0]) + ' (' + est[2].get('coupon_note', '발급·적용 미확인') + ')')
        lines.append('가격비교 표시가 기준 · 쿠폰·카드·실결제 미확인')
        lines.append(str(best.get('url') or ''))
        alerts.append(('watch:' + g['id'] + ':' + str(base) + '>' + str(best['_price']) + ':' + now.date().isoformat(),
                       '\n'.join(lines), g['id'], best['_price']))
    if report is not None:
        report['watch_groups'] = counts
    return alerts


def commit(state, group_id, price, now=None):
    now = now or datetime.now(timezone.utc)
    state.setdefault('watch_groups', {})[group_id] = {'low': price, 'at': now.isoformat()}
