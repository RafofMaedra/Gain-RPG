from __future__ import annotations

import json
import random
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.content import load_theme_pack, narrative_line, weighted_choice

DB_PATH = Path(__file__).resolve().parent.parent / "data.sqlite3"

MINIMUM_SET = {"pushups": 5, "situps": 10, "squats": 10, "pullups": 1}

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
    "discord_webhook_url": "",
    "ntfy_topic_url": "",
    "sidequests_completed": 0,
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json(raw: str | None, fallback=None):
    if not raw:
        return fallback
    return json.loads(raw)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {c[1] for c in cols}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _insert_event(conn: sqlite3.Connection, event_date: str, kind: str, text: str, meta: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO event_log (date, kind, text, meta_json) VALUES (?, ?, ?, ?)",
        (event_date, kind, text, json.dumps(meta or {})),
    )


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

            CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                simulated_date TEXT
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

            CREATE TABLE IF NOT EXISTS sidequest_log (
                date TEXT PRIMARY KEY,
                quest_json TEXT NOT NULL,
                completed_at TEXT,
                result_json TEXT
            );

            CREATE TABLE IF NOT EXISTS inventory_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                effect_json TEXT,
                equipped INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                meta_json TEXT
            );
            """
        )

        _ensure_column(conn, "player", "discord_webhook_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "player", "ntfy_topic_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "player", "sidequests_completed", "INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            """
            INSERT INTO player (
                id, name, level, weeks_completed_towards_next_level, weeks_required_for_next_level,
                grit_current, grit_max, coins, campfire_tokens, theme_pack, testing_mode,
                discord_webhook_url, ntfy_topic_url, sidequests_completed
            ) VALUES (
                :id, :name, :level, :weeks_completed_towards_next_level, :weeks_required_for_next_level,
                :grit_current, :grit_max, :coins, :campfire_tokens, :theme_pack, :testing_mode,
                :discord_webhook_url, :ntfy_topic_url, :sidequests_completed
            ) ON CONFLICT(id) DO NOTHING
            """,
            DEFAULT_PLAYER,
        )
        conn.execute("INSERT INTO app_state (id, simulated_date) VALUES (1, NULL) ON CONFLICT(id) DO NOTHING")
        conn.commit()
    finally:
        conn.close()


def get_player() -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        if not row:
            raise RuntimeError("Missing player")
        return dict(row)
    finally:
        conn.close()


def get_app_today() -> str:
    conn = get_conn()
    try:
        player = conn.execute("SELECT testing_mode FROM player WHERE id = 1").fetchone()
        state = conn.execute("SELECT simulated_date FROM app_state WHERE id = 1").fetchone()
        if player and player["testing_mode"] and state and state["simulated_date"]:
            return state["simulated_date"]
        return date.today().isoformat()
    finally:
        conn.close()


def today_key() -> str:
    return get_app_today()


def testing_advance_day(days: int = 1) -> str:
    conn = get_conn()
    try:
        new_date = (date.fromisoformat(get_app_today()) + timedelta(days=days)).isoformat()
        conn.execute("UPDATE app_state SET simulated_date = ? WHERE id = 1", (new_date,))
        conn.commit()
        return new_date
    finally:
        conn.close()


def update_settings(name: str, theme_pack: str, testing_mode: bool, discord_webhook_url: str, ntfy_topic_url: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE player
            SET name = ?, theme_pack = ?, testing_mode = ?, discord_webhook_url = ?, ntfy_topic_url = ?
            WHERE id = 1
            """,
            (
                name.strip() or DEFAULT_PLAYER["name"],
                theme_pack.strip() or "default",
                int(testing_mode),
                discord_webhook_url.strip(),
                ntfy_topic_url.strip(),
            ),
        )
        if testing_mode:
            conn.execute("UPDATE app_state SET simulated_date = COALESCE(simulated_date, ?) WHERE id = 1", (date.today().isoformat(),))
        else:
            conn.execute("UPDATE app_state SET simulated_date = NULL WHERE id = 1")
        conn.commit()
    finally:
        conn.close()


def ensure_workout_log(log_date: str) -> dict:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO workout_log (date, other_json, last_edited_at) VALUES (?, ?, ?) ON CONFLICT(date) DO NOTHING",
            (log_date, json.dumps({}), utc_now_iso()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM workout_log WHERE date = ?", (log_date,)).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def get_workout_log(log_date: str) -> dict:
    return ensure_workout_log(log_date)


def calculate_grit_restore(pushups: int, situps: int, squats: int, pullups: int) -> int:
    restore = (pushups // 10) + (situps // 15) + (squats // 20) + (pullups // 3)
    if all(v > 0 for v in (pushups, situps, squats, pullups)):
        restore += 1
    return restore


def _minimum_done(p: int, s: int, sq: int, pu: int) -> int:
    return int(
        p >= MINIMUM_SET["pushups"]
        and s >= MINIMUM_SET["situps"]
        and sq >= MINIMUM_SET["squats"]
        and pu >= MINIMUM_SET["pullups"]
    )


def update_workout_reps(log_date: str, pushups: int, situps: int, squats: int, pullups: int) -> dict:
    conn = get_conn()
    try:
        current = ensure_workout_log(log_date)
        if current["locked_in_at"]:
            return current
        p, s, sq, pu = max(0, pushups), max(0, situps), max(0, squats), max(0, pullups)
        conn.execute(
            """
            UPDATE workout_log
            SET pushups = ?, situps = ?, squats = ?, pullups = ?, minimum_set_done = ?, last_edited_at = ?
            WHERE date = ?
            """,
            (p, s, sq, pu, _minimum_done(p, s, sq, pu), utc_now_iso(), log_date),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM workout_log WHERE date = ?", (log_date,)).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def apply_minimum_set(log_date: str) -> dict:
    row = ensure_workout_log(log_date)
    return update_workout_reps(
        log_date,
        max(row["pushups"], MINIMUM_SET["pushups"]),
        max(row["situps"], MINIMUM_SET["situps"]),
        max(row["squats"], MINIMUM_SET["squats"]),
        max(row["pullups"], MINIMUM_SET["pullups"]),
    )


def _minimum_streak(conn: sqlite3.Connection, from_date: str) -> int:
    d = date.fromisoformat(from_date)
    streak = 0
    while True:
        row = conn.execute("SELECT minimum_set_done FROM workout_log WHERE date = ?", (d.isoformat(),)).fetchone()
        if not row or not row["minimum_set_done"]:
            return streak
        streak += 1
        d -= timedelta(days=1)


def lock_in_workout(log_date: str) -> None:
    conn = get_conn()
    try:
        workout = ensure_workout_log(log_date)
        if workout["locked_in_at"]:
            return
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        assert player is not None
        restore = calculate_grit_restore(workout["pushups"], workout["situps"], workout["squats"], workout["pullups"])
        tentative = player["grit_current"] + restore
        overflow = max(0, tentative - player["grit_max"])
        conn.execute("UPDATE player SET grit_current = ?, coins = coins + ? WHERE id = 1", (min(player["grit_max"], tentative), overflow))
        conn.execute("UPDATE workout_log SET locked_in_at = ?, last_edited_at = ? WHERE date = ?", (utc_now_iso(), utc_now_iso(), log_date))
        if _minimum_streak(conn, log_date) % 7 == 0 and _minimum_streak(conn, log_date) > 0:
            conn.execute("UPDATE player SET campfire_tokens = campfire_tokens + 2 WHERE id = 1")
            _insert_event(conn, log_date, "streak_bonus", "7-day minimum-set streak: +2 campfire tokens")
        _insert_event(conn, log_date, "workout", f"Workout locked (+{restore} grit).")
        conn.commit()
    finally:
        conn.close()


def spend_token_for_minimum_set(log_date: str) -> bool:
    conn = get_conn()
    try:
        workout = ensure_workout_log(log_date)
        player = conn.execute("SELECT campfire_tokens FROM player WHERE id = 1").fetchone()
        assert player is not None
        if player["campfire_tokens"] < 1:
            return False
        if any(workout[k] > 0 for k in ["pushups", "situps", "squats", "pullups"]):
            return False
        conn.execute("UPDATE player SET campfire_tokens = campfire_tokens - 1 WHERE id = 1")
        conn.execute(
            "UPDATE workout_log SET pushups=?, situps=?, squats=?, pullups=?, minimum_set_done=1, last_edited_at=? WHERE date=?",
            (MINIMUM_SET["pushups"], MINIMUM_SET["situps"], MINIMUM_SET["squats"], MINIMUM_SET["pullups"], utc_now_iso(), log_date),
        )
        _insert_event(conn, log_date, "token", "Spent token to count day as minimum set.")
        conn.commit()
        return True
    finally:
        conn.close()


def _is_sunday(iso_date: str) -> bool:
    return date.fromisoformat(iso_date).weekday() == 6


def _build_encounter(for_date: str, level: int, theme_key: str, seed_extra: int = 0) -> dict:
    seed = int(for_date.replace("-", "")) + level * 31 + seed_extra
    rng = random.Random(seed)
    theme = load_theme_pack(theme_key)

    entries = theme["bosses"] if _is_sunday(for_date) else theme["threats"]
    chosen = weighted_choice(rng, entries)
    if not chosen:
        chosen = {"name": "Unknown Threat", "tags": ["unknown"], "hp_min": 3, "hp_max": 8, "damage_min": 1, "damage_max": 4}

    return {
        "threat_name": chosen["name"],
        "hp": rng.randint(int(chosen.get("hp_min", 3)), int(chosen.get("hp_max", 8))),
        "damage": rng.randint(int(chosen.get("damage_min", 1)), int(chosen.get("damage_max", 4))),
        "tag": (chosen.get("tags") or ["unknown"])[0],
        "reward_table_key": "boss" if _is_sunday(for_date) else "default",
        "is_boss": _is_sunday(for_date),
        "special": chosen.get("special"),
    }


def get_or_create_daily_roll(for_date: str) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        if row is None:
            player = conn.execute("SELECT level, theme_pack FROM player WHERE id = 1").fetchone()
            assert player is not None
            encounter = _build_encounter(for_date, player["level"], player["theme_pack"])
            conn.execute(
                "INSERT INTO daily_roll (date, encounter_json, generated_at) VALUES (?, ?, ?)",
                (for_date, json.dumps(encounter), utc_now_iso()),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        assert row is not None
        return {"date": row["date"], "encounter": _parse_json(row["encounter_json"], {}), "result": _parse_json(row["result_json"], None), "resolved_at": row["resolved_at"]}
    finally:
        conn.close()


def refresh_daily_roll(for_date: str) -> None:
    conn = get_conn()
    try:
        player = conn.execute("SELECT level, theme_pack FROM player WHERE id = 1").fetchone()
        assert player is not None
        encounter = _build_encounter(for_date, player["level"], player["theme_pack"])
        conn.execute(
            """
            INSERT INTO daily_roll (date, encounter_json, generated_at, resolved_at, result_json)
            VALUES (?, ?, ?, NULL, NULL)
            ON CONFLICT(date) DO UPDATE SET encounter_json=excluded.encounter_json, generated_at=excluded.generated_at, resolved_at=NULL, result_json=NULL
            """,
            (for_date, json.dumps(encounter), utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def _player_attack(level: int) -> int:
    return 2 + (level // 2)


def _grant_item_roll(conn: sqlite3.Connection, for_date: str) -> None:
    rng = random.Random(int(for_date.replace("-", "")) + 777)
    items = [("Iron Sword", "weapon", {"attack": 1}), ("Travel Shield", "armour", {"guard": 1}), ("Wind Boots", "trinket", {"initiative": 1}), ("Focus Ring", "trinket", {"grit_bonus": 1})]
    name, kind, effect = rng.choice(items)
    conn.execute("INSERT INTO inventory_item (name, type, effect_json, equipped) VALUES (?, ?, ?, 0)", (name, kind, json.dumps(effect)))
    _insert_event(conn, for_date, "reward", f"Found item: {name}")


def _progress_leveling(conn: sqlite3.Connection, for_date: str, weeks_gain: int, source: str) -> None:
    player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
    assert player is not None
    weeks = player["weeks_completed_towards_next_level"] + weeks_gain
    level = player["level"]
    required = player["weeks_required_for_next_level"]
    grit_max = player["grit_max"]
    leveled = False
    while weeks >= required:
        weeks -= required
        level += 1
        required = level
        grit_max += 2
        leveled = True
    if leveled:
        conn.execute(
            "UPDATE player SET level=?, weeks_completed_towards_next_level=?, weeks_required_for_next_level=?, grit_max=?, grit_current=MIN(grit_current + 2, ?) WHERE id = 1",
            (level, weeks, required, grit_max, grit_max),
        )
        _insert_event(conn, for_date, "level_up", f"Level up to {level} via {source}.")
        _grant_item_roll(conn, for_date)
    else:
        conn.execute("UPDATE player SET weeks_completed_towards_next_level=? WHERE id=1", (weeks,))


def resolve_encounter(for_date: str, action: str = "auto") -> dict:
    conn = get_conn()
    try:
        roll = get_or_create_daily_roll(for_date)
        encounter = roll["encounter"]
        row = conn.execute("SELECT result_json FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        existing = _parse_json(row["result_json"], None) if row else None
        if existing and existing.get("complete"):
            return existing

        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        assert player is not None
        theme = load_theme_pack(player["theme_pack"])

        state = existing or {"threat_hp": encounter["hp"], "grit_loss": 0, "round": 0, "complete": False, "outcome": None, "log": [], "applied": False, "last_action": None, "narrative": ""}

        def do_round(chosen: str) -> None:
            state["round"] += 1
            state["last_action"] = chosen
            incoming = encounter["damage"] + (1 if encounter.get("special") == "every_3rd_round_plus_1_damage" and state["round"] % 3 == 0 else 0)
            if chosen == "strike":
                dmg = _player_attack(player["level"])
                state["threat_hp"] -= dmg
                state["log"].append(f"Strike for {dmg}.")
                if state["threat_hp"] > 0:
                    state["grit_loss"] += incoming
                    state["log"].append(f"Took {incoming} damage.")
            else:
                guarded = max(0, incoming - 2)
                state["threat_hp"] -= 1
                state["grit_loss"] += guarded
                state["log"].append(f"Guard chip for 1; took {guarded}.")

        if action == "auto":
            while state["threat_hp"] > 0 and state["grit_loss"] < player["grit_current"]:
                remaining = player["grit_current"] - state["grit_loss"]
                do_round("strike" if remaining > 2 else "guard")
        else:
            if state["threat_hp"] > 0 and state["grit_loss"] < player["grit_current"]:
                do_round(action)

        if state["threat_hp"] <= 0:
            state["complete"] = True
            state["outcome"] = "overwhelm" if state["last_action"] == "guard" else "defeat"
        elif state["grit_loss"] >= player["grit_current"]:
            state["complete"] = True
            state["outcome"] = "survived_with_consequence"

        if state["complete"] and not state["applied"]:
            end_grit = max(0, player["grit_current"] - state["grit_loss"])
            coins = 3 if state["outcome"] == "overwhelm" else 2
            if end_grit == 0:
                coins = max(0, coins - 1)
            conn.execute("UPDATE player SET grit_current = ?, coins = coins + ? WHERE id = 1", (end_grit, coins))
            if state["outcome"] == "survived_with_consequence":
                conn.execute("UPDATE player SET campfire_tokens = MAX(campfire_tokens - 1, 0) WHERE id = 1")
            if encounter.get("is_boss") and state["outcome"] != "survived_with_consequence" and end_grit > 0:
                _progress_leveling(conn, for_date, 1, "boss survival")
                state["narrative"] = narrative_line(theme, "boss_survival", int(for_date.replace("-", "")), "You endure the boss encounter.")
            elif state["outcome"] == "overwhelm":
                state["narrative"] = narrative_line(theme, "encounter_guard_win", int(for_date.replace("-", "")), "You outlast the threat.")
            elif state["outcome"] == "defeat":
                state["narrative"] = narrative_line(theme, "encounter_win", int(for_date.replace("-", "")), "You win the encounter.")
            else:
                state["narrative"] = narrative_line(theme, "encounter_consequence", int(for_date.replace("-", "")), "You survive with a consequence.")

            state["coins_earned"] = coins
            state["applied"] = True
            _insert_event(conn, for_date, "encounter", f"{encounter['threat_name']} -> {state['outcome']}", {"coins": coins})
            conn.execute("UPDATE daily_roll SET result_json=?, resolved_at=? WHERE date=?", (json.dumps(state), utc_now_iso(), for_date))
        else:
            conn.execute("UPDATE daily_roll SET result_json=? WHERE date=?", (json.dumps(state), for_date))

        conn.commit()
        return state
    finally:
        conn.close()


def spend_token_negate_tonight_damage(for_date: str) -> bool:
    conn = get_conn()
    try:
        player = conn.execute("SELECT campfire_tokens FROM player WHERE id=1").fetchone()
        row = conn.execute("SELECT result_json FROM daily_roll WHERE date=?", (for_date,)).fetchone()
        if not player or player["campfire_tokens"] < 1 or not row or not row["result_json"]:
            return False
        result = _parse_json(row["result_json"], {})
        if not result.get("complete"):
            return False
        current = conn.execute("SELECT grit_current, grit_max FROM player WHERE id=1").fetchone()
        assert current is not None
        restored = min(current["grit_max"], current["grit_current"] + int(result.get("grit_loss", 0)))
        conn.execute("UPDATE player SET campfire_tokens = campfire_tokens - 1, grit_current = ? WHERE id = 1", (restored,))
        _insert_event(conn, for_date, "token", "Spent token to negate tonight's damage.")
        conn.commit()
        return True
    finally:
        conn.close()


def spend_token_reroll_encounter(for_date: str) -> bool:
    conn = get_conn()
    try:
        player = conn.execute("SELECT campfire_tokens, level, theme_pack FROM player WHERE id = 1").fetchone()
        row = conn.execute("SELECT resolved_at FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        if not player or player["campfire_tokens"] < 1 or (row and row["resolved_at"]):
            return False
        encounter = _build_encounter(for_date, player["level"], player["theme_pack"], seed_extra=999)
        conn.execute("UPDATE player SET campfire_tokens = campfire_tokens - 1 WHERE id = 1")
        conn.execute(
            "INSERT INTO daily_roll (date, encounter_json, generated_at, resolved_at, result_json) VALUES (?, ?, ?, NULL, NULL) ON CONFLICT(date) DO UPDATE SET encounter_json=excluded.encounter_json, generated_at=excluded.generated_at, resolved_at=NULL, result_json=NULL",
            (for_date, json.dumps(encounter), utc_now_iso()),
        )
        _insert_event(conn, for_date, "token", "Spent token to reroll encounter.")
        conn.commit()
        return True
    finally:
        conn.close()


def get_or_create_sidequest(for_date: str) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM sidequest_log WHERE date = ?", (for_date,)).fetchone()
        if row is None:
            player = conn.execute("SELECT theme_pack FROM player WHERE id = 1").fetchone()
            theme_key = player["theme_pack"] if player else "default"
            theme = load_theme_pack(theme_key)
            rng = random.Random(int(for_date.replace("-", "")) + 900)
            chosen = weighted_choice(rng, theme.get("sidequests", []))
            if not chosen:
                chosen = {"kind": "bike_minutes", "target_min": 10, "target_max": 20, "reward": "token", "text": "Complete {target} bike minutes."}
            target = rng.randint(int(chosen.get("target_min", 10)), int(chosen.get("target_max", 20)))
            quest = {"kind": chosen["kind"], "target": target, "reward": chosen.get("reward", "token"), "text": chosen.get("text", "Complete {target} activity.").format(target=target)}
            conn.execute("INSERT INTO sidequest_log (date, quest_json) VALUES (?, ?)", (for_date, json.dumps(quest)))
            conn.commit()
            row = conn.execute("SELECT * FROM sidequest_log WHERE date = ?", (for_date,)).fetchone()
        assert row is not None
        return {"date": row["date"], "quest": _parse_json(row["quest_json"], {}), "completed_at": row["completed_at"], "result": _parse_json(row["result_json"], None)}
    finally:
        conn.close()


def complete_sidequest(for_date: str, bike_minutes: int, km: int, mobility_minutes: int) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM sidequest_log WHERE date = ?", (for_date,)).fetchone()
        if row is None:
            get_or_create_sidequest(for_date)
            row = conn.execute("SELECT * FROM sidequest_log WHERE date = ?", (for_date,)).fetchone()
        assert row is not None
        if row["completed_at"]:
            return _parse_json(row["result_json"], {})

        quest = _parse_json(row["quest_json"], {})
        progress = {"bike_minutes": max(0, bike_minutes), "km": max(0, km), "mobility_minutes": max(0, mobility_minutes)}.get(quest["kind"], 0)
        success = progress >= int(quest["target"])
        result = {"success": success, "progress": progress, "needed": int(quest["target"]), "reward": quest["reward"] if success else None}

        if success:
            if quest["reward"] == "token":
                conn.execute("UPDATE player SET campfire_tokens = campfire_tokens + 1, sidequests_completed = sidequests_completed + 1 WHERE id = 1")
            else:
                conn.execute("UPDATE player SET coins = coins + 4, sidequests_completed = sidequests_completed + 1 WHERE id = 1")
            player = conn.execute("SELECT sidequests_completed, theme_pack FROM player WHERE id = 1").fetchone()
            assert player is not None
            if player["sidequests_completed"] % 2 == 0:
                _progress_leveling(conn, for_date, 1, "sidequest pair")
            line = narrative_line(load_theme_pack(player["theme_pack"]), "sidequest_complete", int(for_date.replace("-", "")), "Side quest completed.")
            _insert_event(conn, for_date, "sidequest", line)

        conn.execute("UPDATE sidequest_log SET completed_at = ?, result_json = ? WHERE date = ?", (utc_now_iso(), json.dumps(result), for_date))
        conn.commit()
        return result
    finally:
        conn.close()


def get_progress_snapshot(for_date: str) -> dict:
    conn = get_conn()
    try:
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        assert player is not None
        streak = _minimum_streak(conn, for_date)
        next_sunday = date.fromisoformat(for_date)
        while next_sunday.weekday() != 6:
            next_sunday += timedelta(days=1)
        events = conn.execute("SELECT * FROM event_log ORDER BY id DESC LIMIT 12").fetchall()
        return {"player": dict(player), "streak": streak, "boss_in_days": (next_sunday - date.fromisoformat(for_date)).days, "events": [dict(e) for e in events]}
    finally:
        conn.close()


def export_save_data() -> dict:
    conn = get_conn()
    try:
        out = {}
        for table in ["player", "app_state", "workout_log", "daily_roll", "sidequest_log", "inventory_item", "event_log"]:
            out[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
        return out
    finally:
        conn.close()


def import_save_data(payload: dict) -> None:
    conn = get_conn()
    try:
        for table in ["player", "app_state", "workout_log", "daily_roll", "sidequest_log", "inventory_item", "event_log"]:
            rows = payload.get(table)
            if rows is None:
                continue
            conn.execute(f"DELETE FROM {table}")
            if not rows:
                continue
            cols = list(rows[0].keys())
            placeholders = ",".join("?" for _ in cols)
            for row in rows:
                conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", tuple(row[c] for c in cols))
        conn.commit()
    finally:
        conn.close()


def should_send_evening_nudge(for_date: str) -> bool:
    workout = ensure_workout_log(for_date)
    return not bool(workout["minimum_set_done"])


def get_notification_summary(for_date: str) -> dict:
    roll = get_or_create_daily_roll(for_date)
    return {
        "date": for_date,
        "threat": roll["encounter"]["threat_name"],
        "resolved": bool(roll["resolved_at"]),
        "result": (roll["result"] or {}).get("outcome"),
    }


def run_midnight_tick() -> dict:
    today = today_key()
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    get_or_create_daily_roll(today)
    prev = get_or_create_daily_roll(yesterday)
    resolved_yesterday = False
    if not prev["resolved_at"]:
        resolve_encounter(yesterday, "auto")
        resolved_yesterday = True
    return {"today": today, "yesterday": yesterday, "resolved_yesterday": resolved_yesterday}
