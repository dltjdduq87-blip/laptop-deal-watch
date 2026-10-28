"""관심 모델 감시: 조건(등급)과 무관하게 지정한 모델·같은 성능 제품군의 최저가 하락을 알린다.

그룹은 이름 패턴(모델 코드) 또는 CPU 패턴으로 묶는다. 그룹 최저가가 이전 기록보다 내려가면
이전가·현재가·할인액·할인율과 그룹 내 저가 상위 3개를 보낸다. 첫 관측은 등록 알림 1회.
가격은 가격비교 사이트 표시가이며 쿠폰·카드·실결제는 미확인.
"""
import re


def members(group, products):
    name_re = re.compile(group['name_pattern'], re.I) if group.get('name_pattern') else None
    cpu_re = re.compile(group['cpu_pattern'], re.I) if group.get('cpu_pattern') else None
    out = []
    for p in products:
        price = p.get('effective_price_krw') or p.get('price_krw')
        if not price or p.get('in_stock') is False:
            continue
        hit = (name_re and name_re.search(str(p.get('name') or ''))) or (cpu_re and cpu_re.search(str(p.get('cpu') or '')))
        if not hit:
            continue
        if group.get('max_weight') and not (p.get('weight_kg') and p['weight_kg'] <= group['max_weight']):
            continue
        if group.get('min_ram') and (p.get('ram_gb') or 0) < group['min_ram']:
            continue
        out.append({**p, '_price': price})
    return sorted(out, key=lambda p: p['_price'])


def won(v):
    return format(v, ',') + '원'


def due(groups, products, state):
    """[(key, message)] for groups whose cheapest member got cheaper (or first seen). Updates state."""
    seen = state.setdefault('watch_groups', {})
    alerts = []
    for g in groups or []:
        ms = members(g, products)
        if not ms:
            continue
        best = ms[0]
        prev = seen.get(g['id'])
        if prev is not None and best['_price'] >= prev:
            if best['_price'] > prev:
                seen[g['id']] = best['_price']  # 이전 최저가 이탈·품절: 기준을 현재로
            continue
        seen[g['id']] = best['_price']
        lines = ['[관심 모델] ' + g['label']]
        if prev is None:
            lines.append('감시 등록 · 현재 최저가 ' + won(best['_price']))
        else:
            diff = prev - best['_price']
            lines.append('이전가 ' + won(prev) + ' → 현재가 ' + won(best['_price']))
            lines.append('▼ ' + won(diff) + ' (' + format(diff * 100 / prev, '.1f') + '% 할인)')
        if g.get('note'):
            lines.append(g['note'])
        lines.append('저가 상위:')
        for p in ms[:3]:
            lines.append('· ' + won(p['_price']) + ' ' + str(p.get('name'))[:55] + (' ' + str(p['weight_kg']) + 'kg' if p.get('weight_kg') else ''))
        lines.append('가격비교 표시가 기준 · 쿠폰·카드·실결제 미확인')
        lines.append(str(best.get('url') or ''))
        alerts.append(('watch:' + g['id'] + ':' + str(best['_price']), '\n'.join(lines)))
    return alerts
