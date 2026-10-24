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


if __name__ == '__main__':
    unittest.main()
