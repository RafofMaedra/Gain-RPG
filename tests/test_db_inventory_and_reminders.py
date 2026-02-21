from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import app.db as db
from app.jobs import reminders


class DBIsolatedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = db.DB_PATH
        db.DB_PATH = Path(self._tmp.name) / "test.sqlite3"
        db.init_db()

    def tearDown(self) -> None:
        db.DB_PATH = self._old_db
        self._tmp.cleanup()


class InventoryEffectsTests(DBIsolatedTestCase):
    def test_equipped_effects_change_combat_stats(self) -> None:
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO inventory_item (name, type, effect_json, equipped) VALUES (?, ?, ?, 1)",
            ("Sword", "weapon", json.dumps({"attack": 2})),
        )
        conn.execute(
            "INSERT INTO inventory_item (name, type, effect_json, equipped) VALUES (?, ?, ?, 1)",
            ("Shield", "armour", json.dumps({"guard": 1})),
        )
        conn.execute(
            "INSERT INTO inventory_item (name, type, effect_json, equipped) VALUES (?, ?, ?, 1)",
            ("Ring", "trinket", json.dumps({"grit_bonus": 2})),
        )
        conn.commit()
        conn.close()

        snap = db.get_progress_snapshot(db.today_key())
        self.assertEqual(snap["combat_stats"]["attack"], 4)
        self.assertEqual(snap["combat_stats"]["guard"], 2)
        self.assertEqual(snap["combat_stats"]["grit_bonus"], 2)

    def test_equip_toggle_single_per_type(self) -> None:
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO inventory_item (name, type, effect_json, equipped) VALUES (?, ?, ?, 0)",
            ("Sword A", "weapon", json.dumps({"attack": 1})),
        )
        conn.execute(
            "INSERT INTO inventory_item (name, type, effect_json, equipped) VALUES (?, ?, ?, 0)",
            ("Sword B", "weapon", json.dumps({"attack": 2})),
        )
        conn.commit()
        rows = conn.execute("SELECT id FROM inventory_item ORDER BY id").fetchall()
        conn.close()

        first_id, second_id = rows[0][0], rows[1][0]
        self.assertTrue(db.equip_inventory_item(first_id))
        self.assertTrue(db.equip_inventory_item(second_id))

        items = db.get_inventory()
        equipped_weapon_count = sum(1 for item in items if item["type"] == "weapon" and item["equipped"])
        self.assertEqual(equipped_weapon_count, 1)




class TimezoneFallbackTests(DBIsolatedTestCase):
    def test_get_app_today_falls_back_when_zoneinfo_unavailable(self) -> None:
        with patch("app.db.ZoneInfo", side_effect=db.ZoneInfoNotFoundError("missing")):
            today = db.get_app_today()
        self.assertRegex(today, r"^\d{4}-\d{2}-\d{2}$")


class ReminderIdempotencyTests(DBIsolatedTestCase):
    def test_reminders_send_once_per_day(self) -> None:
        today = db.today_key()
        self.assertTrue(reminders.send_morning(today))
        self.assertFalse(reminders.send_morning(today))

        self.assertTrue(reminders.send_midnight(today))
        self.assertFalse(reminders.send_midnight(today))


if __name__ == "__main__":
    unittest.main()
