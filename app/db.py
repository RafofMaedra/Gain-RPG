from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data.sqlite3"

DEFAULT_PLAYER = {
    "id": 1,
    "name": "Adventurer",
    "level": 1,
    "weeks_completed_towards_next_level": 0,
    "weeks_required_for_next_level": 1,
    "grit_current": 5,
    "grit_max": 5,
    "coins": 0,
    "campfire_tokens": 0,
    "theme_pack": "default",
    "testing_mode": 0,
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS player (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                weeks_completed_towards_next_level INTEGER NOT NULL,
                weeks_required_for_next_level INTEGER NOT NULL,
                grit_current INTEGER NOT NULL,
                grit_max INTEGER NOT NULL,
                coins INTEGER NOT NULL,
                campfire_tokens INTEGER NOT NULL,
                theme_pack TEXT NOT NULL,
                testing_mode INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS workout_log (
                date TEXT PRIMARY KEY,
                pushups INTEGER NOT NULL DEFAULT 0,
                situps INTEGER NOT NULL DEFAULT 0,
                squats INTEGER NOT NULL DEFAULT 0,
                pullups INTEGER NOT NULL DEFAULT 0,
                other_json TEXT,
                minimum_set_done INTEGER NOT NULL DEFAULT 0,
                locked_in_at TEXT,
                last_edited_at TEXT
            );
            """
        )

        conn.execute(
            """
            INSERT INTO player (
                id, name, level, weeks_completed_towards_next_level,
                weeks_required_for_next_level, grit_current, grit_max,
                coins, campfire_tokens, theme_pack, testing_mode
            ) VALUES (
                :id, :name, :level, :weeks_completed_towards_next_level,
                :weeks_required_for_next_level, :grit_current, :grit_max,
                :coins, :campfire_tokens, :theme_pack, :testing_mode
            )
            ON CONFLICT(id) DO NOTHING;
            """,
            DEFAULT_PLAYER,
        )
        conn.commit()
    finally:
        conn.close()


def get_player() -> sqlite3.Row:
    conn = get_conn()
    try:
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        if player is None:
            raise RuntimeError("Player row not initialized")
        return player
    finally:
        conn.close()


def update_settings(name: str, theme_pack: str, testing_mode: bool) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE player
            SET name = ?, theme_pack = ?, testing_mode = ?
            WHERE id = 1
            """,
            (name.strip() or DEFAULT_PLAYER["name"], theme_pack.strip() or "default", int(testing_mode)),
        )
        conn.commit()
    finally:
        conn.close()
