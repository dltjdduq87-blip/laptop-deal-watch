import os
from pathlib import Path
import queue
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import local_launcher as app


class LocalLauncherTests(unittest.TestCase):
    def test_profiles_are_outside_checkout_and_distinct(self):
        with patch.object(sys, 'platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': '/user-data'}):
            self.assertEqual(app.profile_directory(None), Path('/user-data/LaptopDealWatch/profile-chromium'))
            self.assertNotEqual(app.profile_directory(None), app.profile_directory('msedge'))
        with self.assertRaises(ValueError):
            app.profile_directory('../../other-profile')

    def test_only_fixed_https_sites_no_credentials(self):
        from urllib.parse import urlsplit
        self.assertEqual(len(app.SITES), 13)
        self.assertTrue(app.SITES['네이버쇼핑'].startswith('https://nid.naver.com/'))
        for url in app.SITES.values():
            parsed = urlsplit(url)
            self.assertEqual(parsed.scheme, 'https')
            self.assertIsNone(parsed.username)
            self.assertIsNone(parsed.password)

    def test_manual_workspace_reuses_tab_without_export_or_auth_claim(self):
        calls = []
        class Page:
            def is_closed(self): return False
            def goto(self, url, **kwargs):
                calls.append(('goto', url))
                return types.SimpleNamespace(status=200)
            def bring_to_front(self): calls.append(('focus',))
        class Context:
            pages = []
            def on(self, event, callback): pass
            def new_page(self):
                calls.append(('new_page',))
                return Page()
            def close(self): calls.append(('close',))
        class Chromium:
            def launch_persistent_context(self, profile, **kwargs):
                calls.append(('launch', profile, kwargs))
                return Context()
        class Playwright:
            chromium = Chromium()
            def __enter__(self): return self
            def __exit__(self, *args): pass
        module = types.ModuleType('playwright.sync_api')
        module.sync_playwright = Playwright
        commands, events = queue.Queue(), queue.Queue()
        for command in [('open', '11번가'), ('open', '11번가'), ('open', 'unknown'), ('close', None)]:
            commands.put(command)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {'playwright.sync_api': module}):
            app.browser_worker(commands, events, Path(directory) / 'profile', None)
        self.assertEqual(sum(c[0] == 'new_page' for c in calls), 1)
        self.assertEqual(sum(c[0] == 'goto' for c in calls), 1)
        self.assertFalse(calls[0][2]['headless'])
        messages = list(events.queue)
        self.assertFalse(any(kind == 'error' for kind, value in messages))
        self.assertIn(('site', ('11번가', '창 열림 · 로그인은 직접 확인')), messages)
        self.assertEqual(messages[-1][0], 'closed')

    def test_missing_dependency_has_actionable_message(self):
        commands, events = queue.Queue(), queue.Queue()
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {'playwright.sync_api': None}):
            app.browser_worker(commands, events, Path(directory), None)
        messages = list(events.queue)
        self.assertEqual(messages[0][0], 'error')
        self.assertIn('start_windows.bat', messages[0][1])
        self.assertEqual(messages[-1][0], 'closed')


class MemberCaptureTests(unittest.TestCase):
    PAGE = {'url': 'https://www.11st.co.kr/products/123?trTypeCd=1', 'title': '그램 프로 16', 'visible': 'visible',
            'text': '홍길동님 반갑습니다\n판매가 3,383,720원\n최대할인가 3,201,000원\nT멤버십 VIP 10% 할인쿠폰\n'
                    '배송지: 서울시 종로구\n상품 설명 문단\n무료배송\n주문번호 12345',
            'ld': ['{"@type":"Product","offers":{"@type":"Offer","price":"3383720","priceCurrency":"KRW"}}']}

    def test_extracts_visible_benefits_without_personal_lines(self):
        r = app.extract_benefits(self.PAGE, observed_at='t')
        self.assertIn('T멤버십 VIP 10% 할인쿠폰', r['benefit_lines'])
        joined = ' '.join(r['benefit_lines'])
        for personal in ('홍길동', '배송지', '주문번호'):
            self.assertNotIn(personal, joined)
        self.assertEqual(r['displayed_prices_krw'], [3383720, 3201000])
        self.assertNotIn('상품 설명 문단', r['benefit_lines'])
        self.assertEqual(r['structured_offers'], [{'type': 'Offer', 'price_krw': 3383720}])
        self.assertFalse(r['login_state_verified'] or r['coupon_issued_verified'])
        self.assertIsNone(r['checkout_verified_krw'])

    def test_rejects_other_sites(self):
        with self.assertRaises(ValueError):
            app.extract_benefits({**self.PAGE, 'url': 'https://evil.example/11st.co.kr'})
        with self.assertRaises(ValueError):
            app.extract_benefits({**self.PAGE, 'url': 'http://www.11st.co.kr/'})

    def test_capture_uses_visible_tab_and_saves_locally(self):
        class Page:
            def __init__(self, data): self.data = data
            def is_closed(self): return False
            def evaluate(self, js):
                self.js = js
                return self.data
        hidden = Page({**self.PAGE, 'visible': 'hidden', 'title': 'hidden'})
        shown = Page(self.PAGE)
        context = types.SimpleNamespace(pages=[shown, hidden])
        saved = []
        kind, message = app.capture_active_page(context, save=saved.append)
        self.assertEqual(kind, 'capture')
        self.assertIn('기록 완료', message)
        self.assertEqual(saved[0]['title'], '그램 프로 16')
        self.assertNotIn('cookie', shown.js.lower())
        self.assertNotIn('localstorage', shown.js.lower())

    def test_save_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            path = app.save_observation({'a': 1}, Path(d) / 'x' / 'obs.jsonl')
            app.save_observation({'a': 2}, path)
            self.assertEqual(len(path.read_text(encoding='utf-8').splitlines()), 2)


if __name__ == '__main__':
    unittest.main()


class SingleInstanceTests(unittest.TestCase):
    def test_second_lock_is_refused(self):
        first = app.single_instance_lock(47999)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(app.single_instance_lock(47999))
        finally:
            first.close()
