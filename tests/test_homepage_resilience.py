from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.db as db
import app.main as main


class HomepageResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        db.init_db()

    def tearDown(self) -> None:
        db.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_homepage_handles_invalid_json_in_daily_roll(self) -> None:
        today = db.today_key()
        conn = db.get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO daily_roll (date, encounter_json, generated_at) VALUES (?, ?, ?)",
            (today, "{not valid json", db.utc_now_iso()),
        )
        conn.commit()
        conn.close()

        client = TestClient(main.app)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_homepage_handles_non_list_stakes(self) -> None:
        today = db.today_key()
        conn = db.get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO daily_roll (date, encounter_json, generated_at) VALUES (?, ?, ?)",
            (
                today,
                '{"threat_name":"x","tag":"y","stakes":"bad"}',
                db.utc_now_iso(),
            ),
        )
        conn.commit()
        conn.close()

        client = TestClient(main.app)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
