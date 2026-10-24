"""Local, manual sign-in workspace. Never exports cookies or claims authenticated status."""
from __future__ import annotations

import argparse
import os
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
        events.put(('error', '필수 구성요소가 없습니다. start_windows.bat으로 다시 실행하세요.'))
    except Exception:
        if not closed.is_set():
            events.put(('error', '브라우저를 열지 못했습니다. 같은 프로그램의 다른 창을 닫고 다시 시도하세요. Edge/Chrome 선택 시 해당 브라우저가 설치되어 있어야 합니다.'))
    finally:
        events.put(('closed', '브라우저 종료 · 로그인 유지 여부는 사이트 정책에 따라 달라집니다.'))


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
    root.geometry('800x710')
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
    ttk.Label(frame, text='이 버전은 로그인 준비 단계입니다. 가격·쿠폰 자동 감시는 아직 연결되지 않았습니다.', foreground='#9a3412', wraplength=730).pack(anchor='w', pady=(0, 12))
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
    open_button = ttk.Button(frame, text='선택한 쇼핑몰 열기', command=open_site, state='disabled')
    open_button.pack(anchor='w')
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
            elif kind == 'ready':
                status.set(value)
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
