"""Local, manual sign-in workspace. Never exports cookies or claims authenticated status."""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from pathlib import Path
import queue
import threading
import sys

SITES = {
    '네이버쇼핑': 'https://shopping.naver.com/',
    '쿠팡': 'https://www.coupang.com/',
    '11번가': 'https://www.11st.co.kr/',
    'G마켓': 'https://www.gmarket.co.kr/',
    '옥션': 'https://www.auction.co.kr/',
    'SSG': 'https://www.ssg.com/',
    '롯데하이마트': 'https://www.e-himart.co.kr/',
    '삼성': 'https://www.samsung.com/sec/',
    'LG': 'https://www.lge.co.kr/',
    'ASUS': 'https://www.asus.com/kr/',
    'HP': 'https://www.hp.com/kr-ko/shop/',
    '다나와': 'https://prod.danawa.com/list/?cate=112758',
    '에누리': 'https://price.enuri.com/list?category=0404',
}
CHANNELS = {'전용 Chromium': None, 'Microsoft Edge': 'msedge', 'Google Chrome': 'chrome'}
SITE_HOSTS = ('naver.com', 'coupang.com', '11st.co.kr', 'gmarket.co.kr', 'auction.co.kr', 'ssg.com',
              'e-himart.co.kr', 'samsung.com', 'lge.co.kr', 'asus.com', 'hp.com', 'danawa.com', 'enuri.com')
BENEFIT = re.compile(r'쿠폰|할인|혜택|적립|캐시백|청구|무이자|카드|페이|최대|선착순|배송|멤버십|회원')
PERSONAL = re.compile(r'님|주소|연락처|휴대폰|전화|이메일|@|주문번호|배송지|받는\s*분|로그아웃|마이페이지')
PRICE = re.compile(r'(?<![\d,])(\d{1,3}(?:,\d{3})+|\d{5,8})\s*원')
# Read only on an explicit click: page URL/title, visible benefit lines and JSON-LD offers.
# No cookies, storage, form values or password fields are read.
CAPTURE_JS = '''() => {
  const ld = [];
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) { ld.push(s.textContent.slice(0, 20000)); }
  return {url: location.href, title: document.title, visible: document.visibilityState,
          text: (document.body ? document.body.innerText : '').slice(0, 400000), ld: ld.slice(0, 10)};
}'''


def allowed_host(url):
    host = (urlsplit(url).hostname or '').lower()
    return urlsplit(url).scheme == 'https' and any(host == h or host.endswith('.' + h) for h in SITE_HOSTS)


def ld_offers(blocks):
    found = []
    def walk(v):
        if isinstance(v, list):
            for x in v: walk(x)
        elif isinstance(v, dict):
            if v.get('@type') in ('Offer', 'AggregateOffer') and v.get('priceCurrency') == 'KRW':
                price = v.get('price', v.get('lowPrice'))
                try:
                    found.append({'type': v['@type'], 'price_krw': int(str(price).replace(',', ''))})
                except (TypeError, ValueError):
                    pass
            for k in ('@graph', 'offers', 'hasVariant', 'itemListElement'):
                if k in v: walk(v[k])
    for block in blocks:
        try: walk(json.loads(block))
        except (ValueError, TypeError): continue
    return found[:20]


def extract_benefits(data, observed_at=None):
    """Benefit evidence shown to the signed-in viewer. Not a checkout or eligibility verification."""
    url = str(data.get('url', ''))
    if not allowed_host(url):
        raise ValueError('UNSUPPORTED_SITE')
    lines, seen = [], set()
    for raw_line in str(data.get('text', '')).splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if not line or len(line) > 160 or line in seen or PERSONAL.search(line):
            continue
        if not BENEFIT.search(line) and not PRICE.search(line):
            continue
        seen.add(line); lines.append(line)
        if len(lines) >= 80:
            break
    # Keep first-appearance order: the main product price is usually shown before related items.
    prices = []
    for line in lines:
        for m in PRICE.findall(line):
            value = int(m.replace(',', ''))
            if 10000 <= value <= 20000000 and value not in prices:
                prices.append(value)
    parts = urlsplit(url)
    return {
        'observed_at': observed_at or datetime.now(timezone.utc).isoformat(),
        'url': parts.scheme + '://' + parts.netloc + parts.path + ('?' + parts.query if parts.query else ''),
        'title': str(data.get('title', ''))[:200],
        'benefit_lines': lines,
        'displayed_prices_krw': prices[:40],
        'structured_offers': ld_offers(data.get('ld') or []),
        'evidence_type': 'member_view_snapshot',
        'login_state_verified': False, 'coupon_issued_verified': False, 'checkout_verified_krw': None,
        'note': '로그인한 본인 화면에 표시된 문구 기록 · 쿠폰 발급·중복·결제액은 결제창에서 별도 확인 필요',
    }


def observations_path():
    return data_directory() / 'member_observations.jsonl'


def save_observation(record, path=None):
    path = Path(path or observations_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    return path


def summary_text(record):
    prices = [o['price_krw'] for o in record['structured_offers']] or record['displayed_prices_krw']
    head = record['title'][:40] or record['url']
    label = '상품 가격(구조화) ' if record['structured_offers'] else '화면 첫 가격 '
    price = (label + ', '.join(format(p, ',') + '원' for p in prices[:3])) if prices else '표시 가격 못 찾음'
    return head + ' · ' + price + ' · 혜택 문구 ' + str(len(record['benefit_lines'])) + '줄 기록'


def data_directory():
    if sys.platform == 'win32':
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
    elif sys.platform == 'darwin':
        root = Path.home() / 'Library' / 'Application Support'
    else:
        root = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share')))
    return root / 'LaptopDealWatch'


def profile_directory(channel):
    if channel not in CHANNELS.values():
        raise ValueError('지원하지 않는 브라우저입니다.')
    return data_directory() / ('profile-' + (channel or 'chromium'))


def browser_worker(commands, events, profile, channel):
    """All Playwright calls belong to this thread; the GUI never reads credentials."""
    context = None
    closed = threading.Event()
    try:
        from playwright.sync_api import sync_playwright
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(profile), channel=channel, headless=False,
                no_viewport=True, accept_downloads=False,
            )
            context.on('close', lambda _: closed.set())
            events.put(('ready', '전용 브라우저 준비 완료 · 사이트를 선택하세요.'))
            pages = {}
            while not closed.is_set():
                # Pump browser events even while waiting for a GUI command.
                try:
                    command, site = commands.get_nowait()
                except queue.Empty:
                    if context.pages:
                        context.pages[0].wait_for_timeout(150)
                    else:
                        closed.wait(.15)
                    continue
                if command == 'close':
                    break
                if command == 'capture':
                    events.put(capture_active_page(context))
                    continue
                if command != 'open' or site not in SITES:
                    continue
                page = pages.get(site)
                if page is None or page.is_closed():
                    page = context.new_page()
                    pages[site] = page
                    try:
                        response = page.goto(SITES[site], wait_until='domcontentloaded', timeout=20000)
                        failed = response is not None and response.status >= 400
                        events.put(('site', (site, '접속 오류 · 브라우저 확인' if failed else '창 열림 · 로그인은 직접 확인')))
                    except Exception:
                        events.put(('site', (site, '접속 미확인 · 브라우저 확인')))
                page.bring_to_front()
            context.close()
    except ImportError:
        events.put(('error', '필수 구성요소가 없습니다. setup_windows.py(또는 start_windows.bat)로 다시 설치하세요.'))
    except Exception:
        if not closed.is_set():
            events.put(('error', '브라우저를 열지 못했습니다. 같은 프로그램의 다른 창을 닫고 다시 시도하세요. Edge/Chrome 선택 시 해당 브라우저가 설치되어 있어야 합니다.'))
    finally:
        events.put(('closed', '브라우저 종료 · 로그인 유지 여부는 사이트 정책에 따라 달라집니다.'))


def capture_active_page(context, save=save_observation):
    """Record the visible tab only when the user clicks. Never reads cookies or form fields."""
    try:
        visible = []
        for page in list(context.pages):
            if page.is_closed():
                continue
            data = page.evaluate(CAPTURE_JS)
            if data.get('visible') == 'visible':
                visible.append(data)
        if not visible:
            return ('capture', '기록할 쇼핑몰 화면을 찾지 못했습니다. 상품 페이지를 앞에 띄우고 다시 누르세요.')
        record = extract_benefits(visible[-1])
        save(record)
        return ('capture', '기록 완료 · ' + summary_text(record))
    except ValueError:
        return ('capture', '13개 대상 쇼핑몰 화면만 기록합니다.')
    except Exception:
        return ('capture', '화면을 읽지 못했습니다. 페이지가 다 열린 뒤 다시 누르세요.')


def doctor():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return 0 if Path(pw.chromium.executable_path).is_file() else 1
    except ImportError:
        return 1


def main():
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = tk.Tk()
    root.title('노트북 감시 · 로그인 준비')
    root.geometry('820x760')
    root.minsize(720, 650)
    root.configure(bg='#f4f6fa')
    style = ttk.Style(root)
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    style.configure('TFrame', background='#f4f6fa')
    style.configure('TLabel', background='#f4f6fa', font=('맑은 고딕', 10))
    style.configure('TButton', padding=9, font=('맑은 고딕', 10))
    style.configure('Treeview', rowheight=28, font=('맑은 고딕', 10))
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='내 노트북에서 로그인 준비', font=('맑은 고딕', 20, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='1. 브라우저 시작 → 2. 사이트 선택 → 3. 열린 브라우저에서 직접 로그인', wraplength=730).pack(anchor='w', pady=(10, 6))
    ttk.Label(frame, text='로그인은 직접 하세요. 혜택 기록은 누를 때만 동작하며 GitHub·텔레그램 자동 감시와는 아직 연결되지 않았습니다.', foreground='#9a3412', wraplength=730).pack(anchor='w', pady=(0, 12))
    controls = ttk.Frame(frame)
    controls.pack(fill='x')
    selected = tk.StringVar(value='전용 Chromium')
    chooser = ttk.Combobox(controls, textvariable=selected, values=list(CHANNELS), state='readonly', width=23)
    chooser.pack(side='left', padx=(0, 10))
    commands, events = queue.Queue(), queue.Queue()
    running = False
    closing = False
    status = tk.StringVar(value='브라우저를 시작하면 로그인할 사이트를 선택할 수 있습니다.')
    tree = ttk.Treeview(frame, columns=('site', 'status'), show='headings', height=13, selectmode='browse')
    tree.heading('site', text='쇼핑몰')
    tree.heading('status', text='현재 상태 (로그인 성공을 자동 판정하지 않습니다)')
    tree.column('site', width=140, stretch=False)
    tree.column('status', width=540)
    for site in SITES:
        tree.insert('', 'end', iid=site, values=(site, '아직 열지 않음'))

    def start():
        nonlocal running
        if running:
            return
        if not messagebox.askokcancel('이 노트북에 로그인 상태 저장',
            '전용 브라우저의 쿠키·로그인 상태를 이 Windows 사용자 계정의 데이터 폴더에 저장합니다.\n'
            '기존 Chrome/Edge 프로필을 복사하거나 GitHub·텔레그램에 전송하지 않습니다.\n'
            '본인 노트북에서만 진행하고, 비밀번호와 인증번호는 쇼핑몰 화면에 직접 입력하세요.\n\n전용 브라우저를 시작할까요?'):
            return
        running = True
        while not commands.empty():
            try: commands.get_nowait()
            except queue.Empty: break
        start_button.configure(state='disabled')
        chooser.configure(state='disabled')
        status.set('전용 브라우저를 여는 중입니다…')
        threading.Thread(target=browser_worker, args=(commands, events, profile_directory(CHANNELS[selected.get()]), CHANNELS[selected.get()]), daemon=True).start()

    def open_site(event=None):
        choice = tree.selection()
        if running and choice:
            commands.put(('open', choice[0]))
            status.set(choice[0] + ' 창으로 이동 중입니다…')

    def close_browser():
        if running:
            commands.put(('close', None))
            status.set('브라우저를 종료하는 중입니다…')

    def quit_app():
        nonlocal closing
        if running:
            if not messagebox.askokcancel('종료', '프로그램이 연 전용 브라우저도 함께 닫습니다. 종료할까요?'):
                return
            closing = True
            close_browser()
        else:
            root.destroy()

    start_button = ttk.Button(controls, text='브라우저 시작', command=start)
    start_button.pack(side='left')
    stop_button = ttk.Button(controls, text='브라우저 닫기', command=close_browser, state='disabled')
    stop_button.pack(side='left', padx=10)
    tree.pack(fill='both', expand=True, pady=14)
    tree.bind('<Double-1>', open_site)
    actions = ttk.Frame(frame)
    actions.pack(anchor='w', fill='x')
    open_button = ttk.Button(actions, text='선택한 쇼핑몰 열기', command=open_site, state='disabled')
    open_button.pack(side='left')

    def capture():
        if running:
            commands.put(('capture', None))
            status.set('현재 화면의 가격·혜택 문구를 읽는 중입니다…')

    capture_button = ttk.Button(actions, text='현재 상품 화면 혜택 기록', command=capture, state='disabled')
    capture_button.pack(side='left', padx=10)
    ttk.Label(frame, text='로그인 후 상품 페이지를 띄우고 "혜택 기록"을 누르면 화면의 가격·쿠폰 문구만 이 PC에 저장합니다 (쿠키·입력값은 읽지 않음).', wraplength=730, foreground='#475569').pack(anchor='w', pady=(6, 0))
    ttk.Label(frame, textvariable=status, wraplength=730, foreground='#1d4ed8').pack(anchor='w', pady=(14, 8))
    ttk.Label(frame, text='로그인 완료 후에도 이 프로그램을 다시 열어 로그인 상태가 유지되는지 확인하세요.\n접근 제한이나 보안 확인이 나오면 해당 사이트에서 멈추고 화면을 알려주세요.', wraplength=730).pack(anchor='w')

    def poll():
        nonlocal running
        while True:
            try: kind, value = events.get_nowait()
            except queue.Empty: break
            if kind == 'site':
                site, text = value
                tree.item(site, values=(site, text))
                status.set(site + ': ' + text)
            elif kind == 'capture':
                status.set(value)
            elif kind == 'ready':
                status.set(value)
                capture_button.configure(state='normal')
                open_button.configure(state='normal')
                stop_button.configure(state='normal')
            elif kind == 'error':
                status.set(value)
                messagebox.showerror('실행 확인 필요', value)
            elif kind == 'closed':
                running = False
                status.set(value)
                start_button.configure(state='normal')
                chooser.configure(state='readonly')
                open_button.configure(state='disabled')
                capture_button.configure(state='disabled')
                stop_button.configure(state='disabled')
                if closing:
                    root.destroy()
                    return
        root.after(150, poll)

    root.protocol('WM_DELETE_WINDOW', quit_app)
    root.after(150, poll)
    root.mainloop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--doctor', action='store_true')
    args = parser.parse_args()
    if args.doctor:
        raise SystemExit(doctor())
    main()
