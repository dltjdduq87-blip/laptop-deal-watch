"""Approximate release date of a laptop listing, to drop models launched 3+ years ago.

The comparison list gives no release date, so it is estimated from public facts in the listing:
- a model year in the name ("LG전자 2023 그램16" -> January of that year)
- the CPU's launch month (a laptop cannot ship before its CPU)
The later of the two is used. Unknown listings are kept (not guessed as old).
CPU launch months are public launch announcements, rounded to the month.
"""
import re
from datetime import datetime, timezone

MAX_AGE_MONTHS = 36

NAME_YEAR = re.compile(r'(?<![\w-])(20[12]\d)(?![\w-])')

INTEL_GEN = {8: (2017, 8), 9: (2019, 4), 10: (2019, 8), 11: (2020, 9), 12: (2022, 1), 13: (2023, 1), 14: (2024, 1)}


def cpu_launch(cpu):
    """(year, month) the CPU family launched, or None when the CPU text is not recognised."""
    c = str(cpu or '')
    if not c:
        return None
    # Intel Core Ultra: (S3) Panther Lake, (S2) Lunar/Arrow Lake, plain 1xx Meteor Lake
    if re.search(r'울트라|Ultra', c, re.I):
        if re.search(r'\(S3\)|울트라\s*\d\s*X?\s*3\d\d|Ultra\s*\d\s*3\d\d', c, re.I):
            return (2026, 1)
        if re.search(r'\(S2\)|울트라\s*\d\s*2\d\d|Ultra\s*\d\s*2\d\d', c, re.I):
            return (2024, 9)
        return (2023, 12)
    m = re.search(r'(\d{1,2})세대', c)
    if m and int(m[1]) in INTEL_GEN:
        return INTEL_GEN[int(m[1])]
    m = re.search(r'i[3579]-?(1[0-4])\d{2,3}[A-Z]', c)
    if m:
        return INTEL_GEN[int(m[1])]
    # Intel Core 3/5/7 (no "i"): 1xx Raptor Lake refresh (2024), 2xx (2025), 3xx Wildcat Lake (2026)
    m = re.search(r'(?:코어|Core)\s*[357]\s+([123])\d\d', c)
    if m:
        return {'1': (2024, 1), '2': (2025, 1), '3': (2026, 1)}[m[1]]
    if re.search(r'N-?시리즈|\bN[12]\d\d\b', c):
        return (2023, 1)
    # AMD
    if re.search(r'라이젠\s*AI|Ryzen\s*AI', c, re.I):
        m = re.search(r'\b([34])\d\d\b', c)
        return (2026, 1) if m and m[1] == '4' else (2024, 7)
    if re.search(r'라이젠|Ryzen', c, re.I):
        m = re.search(r'\b([5-9])(\d)(\d)(\d)[A-Z]{0,3}\b', c)
        if m:
            series = int(m[1])
            if series == 7:
                return (2023, 4) if m[3] == '4' else (2023, 1)
            return {5: (2021, 1), 6: (2022, 1), 8: (2024, 1), 9: (2025, 1)}[series]
        m = re.search(r'\b([12])\d\d\b', c)
        if m:  # Ryzen 200 (2025), Ryzen 100 (2026 rebrand)
            return (2025, 1) if m[1] == '2' else (2026, 1)
    # Apple / Qualcomm
    m = re.search(r'\bM([1-5])\b', c)
    if m and re.search(r'애플|Apple', c, re.I):
        pro = re.search(r'M2\s*(Pro|Max)', c, re.I)
        return {1: (2020, 11), 2: (2023, 1) if pro else (2022, 6), 3: (2023, 10), 4: (2024, 11), 5: (2025, 10)}[int(m[1])]
    if re.search(r'Snapdragon|스냅드래곤', c, re.I):
        return (2026, 1) if re.search(r'X2', c) else (2024, 6)
    return None


def estimate(p):
    """{'release': (y, m) or None, 'basis': text}."""
    text = ' '.join(str(p.get(k) or '') for k in ('model_key', 'name', 'model'))
    years = [int(y) for y in NAME_YEAR.findall(text)]
    cands, basis = [], []
    if years:
        cands.append((max(years), 1)); basis.append('모델명 연식 ' + str(max(years)))
    launch = cpu_launch(p.get('cpu'))
    if launch:
        cands.append(launch); basis.append('CPU 출시 %d.%02d' % launch)
    return {'release': max(cands) if cands else None, 'basis': ' · '.join(basis) or '출시 시기 미확인'}


def months_since(ym, now=None):
    now = now or datetime.now(timezone.utc)
    return (now.year - ym[0]) * 12 + now.month - ym[1]


def too_old(p, now=None, max_months=MAX_AGE_MONTHS):
    r = estimate(p)['release']
    return bool(r) and months_since(r, now) >= max_months
