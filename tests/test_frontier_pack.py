from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app.db as db


class FrontierPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "frontier.sqlite3"
        db.init_db()

    def tearDown(self) -> None:
        db.DB_PATH = self.old
        self.tmp.cleanup()

    def test_daily_roll_stable_for_date(self) -> None:
        d = db.today_key()
        a = db.get_or_create_daily_roll(d)["encounter"]
        b = db.get_or_create_daily_roll(d)["encounter"]
        self.assertEqual(a, b)

    def test_force_reroll_changes_content(self) -> None:
        d = db.today_key()
        a = db.get_or_create_daily_roll(d)["encounter"]
        db.force_generate_roll(d)
        b = db.get_or_create_daily_roll(d)["encounter"]
        self.assertNotEqual(a, b)

    def test_heat_affects_preview_tier(self) -> None:
        d = db.today_key()
        db.set_frontier_heat(0)
        t1 = db.preview_intensity_tier(d)["base"]
        db.set_frontier_heat(9)
        t2 = db.preview_intensity_tier(d)["base"]
        self.assertLess(t1, t2)


if __name__ == "__main__":
    unittest.main()
