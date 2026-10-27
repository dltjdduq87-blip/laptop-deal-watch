import unittest
from datetime import datetime, timezone
import release as R

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)


class ReleaseTest(unittest.TestCase):
    def old(self, **p):
        return R.too_old(p, NOW)

    def test_three_years_or_more_excluded(self):
        self.assertTrue(self.old(name='LG전자 2023 그램16', cpu='인텔 코어i7-13세대 i7-1360P (2.2GHz)'))
        self.assertTrue(self.old(name='HP 15', cpu='AMD 라이젠5(Zen3+) 7535HS (3.3GHz)'))
        self.assertTrue(self.old(name='X', cpu='인텔 코어i5-12세대 i5-1235U (1.3GHz)'))

    def test_recent_kept(self):
        self.assertFalse(self.old(name='HP 15', cpu='인텔 코어 울트라7 155H (4.8GHz) 11TOPS'))
        self.assertFalse(self.old(name='ASUS TUF', cpu='AMD 라이젠7(Zen4) 260 (5.1GHz) 16TOPS'))
        self.assertFalse(self.old(name='DELL', cpu='AMD 라이젠AI 5 PRO 340 (4.8GHz) 50TOPS'))
        self.assertFalse(self.old(name='LG전자 2026 그램', cpu='인텔 코어 울트라5(S3) 322'))
        self.assertFalse(self.old(name='HP', cpu='인텔 코어5 320 (4.6GHz)'))

    def test_newer_name_year_wins_over_old_cpu_and_unknown_kept(self):
        self.assertFalse(self.old(name='MSI 2024 모델', cpu='인텔 코어i7-13세대 i7-13620H'))
        self.assertFalse(self.old(name='모델명만'))
        self.assertFalse(self.old(name='ASUS P1503CVA-S72002', cpu=''))


if __name__ == '__main__':
    unittest.main()
