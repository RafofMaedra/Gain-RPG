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

    def test_auto_resolve_with_sqlite_row_player(self) -> None:
        d = db.today_key()
        result = db.resolve_encounter(d, action="auto")
        self.assertTrue(result["complete"])
        self.assertIsNotNone(result["outcome"])

    def test_generated_encounter_has_twist_effect(self) -> None:
        d = db.today_key()
        encounter = db.get_or_create_daily_roll(d)["encounter"]
        self.assertIn("twist_effect", encounter)
        self.assertIn("key", encounter["twist_effect"])

    def test_zero_grit_results_in_nonlethal_consequence(self) -> None:
        d = db.today_key()
        conn = db.get_conn()
        try:
            encounter = {
                "threat_name": "Test Threat",
                                "damage": 9,
                "tag": "frontier",
                "reward_table_key": "default",
                "is_boss": False,
                "special": None,
                "intensity_tier": 1,
                "intensity_base": 1,
                "intensity_wobble": 0,
                "location": "Test",
                "situation": "Test",
                "twist": "Test",
                "twist_effect": {"key": "extra_damage", "label": "Escalation", "description": "x"},
                "success_threshold": 5,
                "defeat_target": 10,
                "overwhelm_target": 12,
                "stakes": ["x"],
            }
            conn.execute(
                "INSERT INTO daily_roll (date, encounter_json, generated_at) VALUES (?, ?, ?) ON CONFLICT(date) DO UPDATE SET encounter_json=excluded.encounter_json, generated_at=excluded.generated_at, resolved_at=NULL, result_json=NULL",
                (d, db.json.dumps(encounter), db.utc_now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

        result = db.resolve_encounter(d, action="auto")
        self.assertEqual(result["outcome"], "survived_with_consequence")
        player = db.get_player()
        self.assertEqual(player["grit_current"], 1)


if __name__ == "__main__":
    unittest.main()
