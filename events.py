"""Shopping-event and first-come coupon alerts from a sourced calendar in config.json.

Only events with a source URL are used. Coupon drop times are added only when a shop announces them.
GitHub scheduled runs can be delayed, so each stage has a window and is sent at most once;
a stage whose window has passed is skipped rather than sent late.
"""
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def _date(s):
    return datetime.fromisoformat(s).replace(tzinfo=KST) if 'T' not in s else datetime.fromisoformat(s).astimezone(KST)


def _day(s):
    return datetime.fromisoformat(s[:10]).date()


def due_alerts(events, now, top_lines=()):
    """Yield (key, message) for every stage whose window contains `now`."""
    kst = now.astimezone(KST)
    today = kst.date()
    for ev in events or []:
        if not ev.get('source_url'):
            continue
        start, end = _day(ev['start']), _day(ev['end'])
        if today > end:
            continue
        head = ev['name'] + ' (' + ev['start'][5:10].replace('-', '/') + '~' + ev['end'][5:10].replace('-', '/') + ')'
        conf = '' if ev.get('confirmed', True) else '\n※ 일정 출처가 공식 발표가 아니어서 확인이 필요합니다.'
        notes = ('\n' + ev['notes']) if ev.get('notes') else ''
        src = '\n근거: ' + ev['source_url']
        days_left = (start - today).days
        notice_from = start - timedelta(days=int(ev.get('notice_days', 7)))
        if notice_from <= today < start:
            yield ('event:' + ev['id'] + ':notice', '[행사 예고 D-' + str(days_left) + '] ' + head + notes + conf
                   + '\n후보 가격을 계속 확인하고, 행사 중 예상가가 내려가면 바로 알립니다.' + src)
        if start <= today <= end:
            tops = ('\n지금 조건 TOP 후보:\n' + '\n'.join(top_lines)) if top_lines else ''
            yield ('event:' + ev['id'] + ':start', '[행사 시작] ' + head + ' 진행 중' + notes + conf + tops + src)
        for drop in ev.get('coupon_drops', []):
            if not drop.get('source_url') or not drop.get('at'):
                continue
            at = _date(drop['at'])
            label = '[선착순 쿠폰] ' + drop['name'] + ' · ' + at.strftime('%m/%d %H:%M') + ' 발급'
            cond = ('\n조건: ' + drop['conditions']) if drop.get('conditions') else ''
            dsrc = '\n근거: ' + drop['source_url']
            eve = datetime.combine(at.date() - timedelta(days=1), datetime.min.time(), KST) + timedelta(hours=20)
            stages = [
                ('d1', eve, at - timedelta(hours=2), '내일 발급 예정 · 휴대폰 알람을 맞춰 두세요'),
                ('pre', at - timedelta(minutes=60), at, '곧 발급 (약 1시간 이내) · 앱에 로그인해 두세요'),
                ('open', at, at + timedelta(minutes=int(drop.get('open_window_min', 20))), '발급 시작 · 선착순이라 빨리 소진될 수 있습니다'),
            ]
            for stage, frm, to, text in stages:
                if frm <= kst < to:
                    yield ('coupon:' + ev['id'] + ':' + drop['id'] + ':' + stage,
                           label + '\n' + text + cond + '\n본인 발급 자격·잔여 수량·노트북 적용 여부는 자동 확인하지 않습니다.' + dsrc)
