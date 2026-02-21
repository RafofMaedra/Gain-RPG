from __future__ import annotations

import json
import random
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data.sqlite3"

MINIMUM_SET = {
    "pushups": 5,
    "situps": 10,
    "squats": 10,
    "pullups": 1,
}

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


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def today_key() -> str:
    return date.today().isoformat()


def _row_to_player(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _parse_json(value: str | None, fallback: dict | list | None = None):
    if value is None:
        return fallback
    return json.loads(value)


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

            CREATE TABLE IF NOT EXISTS daily_roll (
                date TEXT PRIMARY KEY,
                encounter_json TEXT NOT NULL,
                sidequest_json TEXT,
                generated_at TEXT NOT NULL,
                resolved_at TEXT,
                result_json TEXT
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


def get_player() -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("Player row not initialized")
        return _row_to_player(row)
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


def ensure_workout_log(log_date: str) -> dict:
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO workout_log (date, other_json, last_edited_at)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO NOTHING
            """,
            (log_date, json.dumps({}), utc_now_iso()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM workout_log WHERE date = ?", (log_date,)).fetchone()
        assert row is not None
        return {key: row[key] for key in row.keys()}
    finally:
        conn.close()


def get_workout_log(log_date: str) -> dict:
    return ensure_workout_log(log_date)


def calculate_grit_restore(pushups: int, situps: int, squats: int, pullups: int) -> int:
    grit = (pushups // 10) + (situps // 15) + (squats // 20) + (pullups // 3)
    if all(v > 0 for v in (pushups, situps, squats, pullups)):
        grit += 1
    return grit


def _update_workout(conn: sqlite3.Connection, log_date: str, pushups: int, situps: int, squats: int, pullups: int) -> None:
    minimum_done = int(
        pushups >= MINIMUM_SET["pushups"]
        and situps >= MINIMUM_SET["situps"]
        and squats >= MINIMUM_SET["squats"]
        and pullups >= MINIMUM_SET["pullups"]
    )
    conn.execute(
        """
        UPDATE workout_log
        SET pushups = ?, situps = ?, squats = ?, pullups = ?,
            minimum_set_done = ?, last_edited_at = ?
        WHERE date = ?
        """,
        (pushups, situps, squats, pullups, minimum_done, utc_now_iso(), log_date),
    )


def update_workout_reps(log_date: str, pushups: int, situps: int, squats: int, pullups: int) -> dict:
    conn = get_conn()
    try:
        ensure_workout_log(log_date)
        _update_workout(conn, log_date, max(0, pushups), max(0, situps), max(0, squats), max(0, pullups))
        conn.commit()
        row = conn.execute("SELECT * FROM workout_log WHERE date = ?", (log_date,)).fetchone()
        assert row is not None
        return {key: row[key] for key in row.keys()}
    finally:
        conn.close()


def apply_minimum_set(log_date: str) -> dict:
    current = ensure_workout_log(log_date)
    return update_workout_reps(
        log_date,
        max(current["pushups"], MINIMUM_SET["pushups"]),
        max(current["situps"], MINIMUM_SET["situps"]),
        max(current["squats"], MINIMUM_SET["squats"]),
        max(current["pullups"], MINIMUM_SET["pullups"]),
    )


def lock_in_workout(log_date: str) -> None:
    conn = get_conn()
    try:
        workout = ensure_workout_log(log_date)
        if workout["locked_in_at"]:
            return

        restore = calculate_grit_restore(
            workout["pushups"], workout["situps"], workout["squats"], workout["pullups"]
        )
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        assert player is not None
        new_grit = player["grit_current"] + restore
        overflow = max(0, new_grit - player["grit_max"])
        capped_grit = min(player["grit_max"], new_grit)

        conn.execute(
            "UPDATE player SET grit_current = ?, coins = coins + ? WHERE id = 1",
            (capped_grit, overflow),
        )
        conn.execute(
            "UPDATE workout_log SET locked_in_at = ?, last_edited_at = ? WHERE date = ?",
            (utc_now_iso(), utc_now_iso(), log_date),
        )
        conn.commit()
    finally:
        conn.close()


def _build_encounter(for_date: str) -> dict:
    seed = int(for_date.replace("-", ""))
    rng = random.Random(seed)
    threats = [
        ("Bramblefang", "beast"),
        ("Ashroad Bandit", "bandit"),
        ("Gloom Wisp", "curse"),
        ("Crypt Hound", "undead"),
        ("Ridge Stalker", "beast"),
    ]
    threat_name, tag = rng.choice(threats)
    hp = rng.randint(3, 8)
    damage = rng.randint(1, 4)
    return {
        "threat_name": threat_name,
        "hp": hp,
        "damage": damage,
        "tag": tag,
        "reward_table_key": "default",
    }


def get_or_create_daily_roll(for_date: str) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        if row is None:
            encounter = _build_encounter(for_date)
            conn.execute(
                """
                INSERT INTO daily_roll (date, encounter_json, generated_at)
                VALUES (?, ?, ?)
                """,
                (for_date, json.dumps(encounter), utc_now_iso()),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM daily_roll WHERE date = ?", (for_date,)).fetchone()

        assert row is not None
        return {
            "date": row["date"],
            "encounter": _parse_json(row["encounter_json"], {}),
            "result": _parse_json(row["result_json"], None),
            "resolved_at": row["resolved_at"],
        }
    finally:
        conn.close()


def _player_attack(level: int) -> int:
    return 2 + (level // 2)


def _resolve_round(state: dict, action: str, encounter: dict, player: dict) -> None:
    threat_damage = encounter["damage"]
    attack = _player_attack(player["level"])
    guard = 1

    if action == "strike":
        state["threat_hp"] -= attack
        state["log"].append(f"Strike for {attack} damage.")
        if state["threat_hp"] > 0:
            state["grit_loss"] += threat_damage
            state["log"].append(f"{encounter['threat_name']} hits for {threat_damage}.")
    else:
        guarded_damage = max(0, threat_damage - guard - 1)
        state["threat_hp"] -= 1
        state["grit_loss"] += guarded_damage
        state["log"].append(f"Guard chip for 1, take {guarded_damage}.")


def _apply_encounter_result(
    conn: sqlite3.Connection,
    for_date: str,
    encounter: dict,
    result: dict,
    starting_grit: int,
) -> dict:
    player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
    assert player is not None

    if result.get("complete") and not result.get("applied"):
        end_grit = max(0, starting_grit - result["grit_loss"])
        coins_delta = 3 if result.get("outcome") == "overwhelm" else 2
        if end_grit == 0:
            coins_delta = max(0, coins_delta - 1)

        conn.execute(
            "UPDATE player SET grit_current = ?, coins = coins + ? WHERE id = 1",
            (end_grit, coins_delta),
        )
        result["coins_earned"] = coins_delta
        result["applied"] = True
        conn.execute(
            """
            UPDATE daily_roll
            SET result_json = ?, resolved_at = ?
            WHERE date = ?
            """,
            (json.dumps(result), utc_now_iso(), for_date),
        )
        conn.commit()

    row = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
    assert row is not None
    return _row_to_player(row)


def resolve_encounter(for_date: str, action: str = "auto") -> dict:
    conn = get_conn()
    try:
        roll_row = conn.execute("SELECT * FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        if roll_row is None:
            get_or_create_daily_roll(for_date)
            roll_row = conn.execute("SELECT * FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        assert roll_row is not None

        encounter = _parse_json(roll_row["encounter_json"], {})
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        assert player is not None

        existing = _parse_json(roll_row["result_json"], None)
        if existing and existing.get("complete"):
            return existing

        state = existing or {
            "threat_hp": encounter["hp"],
            "grit_loss": 0,
            "round": 0,
            "complete": False,
            "outcome": None,
            "log": [],
            "applied": False,
        }

        if action == "auto":
            while state["threat_hp"] > 0 and state["grit_loss"] < player["grit_current"]:
                state["round"] += 1
                if player["grit_current"] - state["grit_loss"] > 2:
                    round_action = "strike"
                else:
                    round_action = "guard"
                _resolve_round(state, round_action, encounter, player)
        else:
            if state["threat_hp"] > 0 and state["grit_loss"] < player["grit_current"]:
                state["round"] += 1
                _resolve_round(state, action, encounter, player)

        if state["threat_hp"] <= 0:
            state["complete"] = True
            last_action = action
            if action == "auto" and state["log"]:
                last_action = "guard" if "Guard" in state["log"][-1] else "strike"
            state["outcome"] = "overwhelm" if last_action == "guard" else "defeat"
        elif state["grit_loss"] >= player["grit_current"]:
            state["complete"] = True
            state["outcome"] = "survived_with_consequence"

        conn.execute(
            "UPDATE daily_roll SET result_json = ? WHERE date = ?",
            (json.dumps(state), for_date),
        )
        conn.commit()

        _apply_encounter_result(conn, for_date, encounter, state, player["grit_current"])
        return state
    finally:
        conn.close()
