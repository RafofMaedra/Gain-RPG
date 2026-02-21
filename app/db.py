from __future__ import annotations

import json
import random
import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path

from app.content import load_theme_pack, narrative_line, stable_seed, weighted_choice

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
    "theme_pack": "frontier_kingdom",
    "testing_mode": 0,
    "discord_webhook_url": "",
    "ntfy_topic_url": "",
    "sidequests_completed": 0,
    "day_timezone": "Pacific/Auckland",
    "frontier_heat": 0,
    "renown": 0,
    "romance_dial": "light_flirt",
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
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return fallback


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
        _ensure_column(conn, "player", "day_timezone", "TEXT NOT NULL DEFAULT 'Pacific/Auckland'")
        _ensure_column(conn, "player", "frontier_heat", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "player", "renown", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "player", "romance_dial", "TEXT NOT NULL DEFAULT 'light_flirt'")

        conn.execute(
            """
            INSERT INTO player (
                id, name, level, weeks_completed_towards_next_level, weeks_required_for_next_level,
                grit_current, grit_max, coins, campfire_tokens, theme_pack, testing_mode,
                discord_webhook_url, ntfy_topic_url, sidequests_completed, day_timezone, frontier_heat, renown, romance_dial
            ) VALUES (
                :id, :name, :level, :weeks_completed_towards_next_level, :weeks_required_for_next_level,
                :grit_current, :grit_max, :coins, :campfire_tokens, :theme_pack, :testing_mode,
                :discord_webhook_url, :ntfy_topic_url, :sidequests_completed, :day_timezone, :frontier_heat, :renown, :romance_dial
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


def _player_zoneinfo(player: sqlite3.Row | dict | None):
    tz_name = (player or {}).get("day_timezone") if isinstance(player, dict) else (player["day_timezone"] if player and "day_timezone" in player.keys() else "Pacific/Auckland")
    try:
        return ZoneInfo(tz_name or "Pacific/Auckland")
    except ZoneInfoNotFoundError:
        try:
            return ZoneInfo("UTC")
        except ZoneInfoNotFoundError:
            return timezone.utc


def get_app_today() -> str:
    conn = get_conn()
    try:
        player = conn.execute("SELECT testing_mode, day_timezone FROM player WHERE id = 1").fetchone()
        state = conn.execute("SELECT simulated_date FROM app_state WHERE id = 1").fetchone()
        if player and player["testing_mode"] and state and state["simulated_date"]:
            return state["simulated_date"]
        tz = _player_zoneinfo(player)
        return datetime.now(tz).date().isoformat()
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


def update_settings(
    name: str,
    theme_pack: str,
    testing_mode: bool,
    discord_webhook_url: str,
    ntfy_topic_url: str,
    day_timezone: str,
    romance_dial: str = "light_flirt",
) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE player
            SET name = ?, theme_pack = ?, testing_mode = ?, discord_webhook_url = ?, ntfy_topic_url = ?, day_timezone = ?, romance_dial = ?
            WHERE id = 1
            """,
            (
                name.strip() or DEFAULT_PLAYER["name"],
                theme_pack.strip() or "frontier_kingdom",
                int(testing_mode),
                discord_webhook_url.strip(),
                ntfy_topic_url.strip(),
                day_timezone.strip() or "Pacific/Auckland",
                romance_dial if romance_dial in {"off", "light_flirt", "strong_flirt"} else "light_flirt",
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
        combat_stats = _combat_stats_from_player(conn, player)
        effective_grit_max = player["grit_max"] + combat_stats["grit_bonus"]
        tentative = player["grit_current"] + restore
        overflow = max(0, tentative - effective_grit_max)
        conn.execute("UPDATE player SET grit_current = ?, coins = coins + ? WHERE id = 1", (min(effective_grit_max, tentative), overflow))
        conn.execute("UPDATE workout_log SET locked_in_at = ?, last_edited_at = ? WHERE date = ?", (utc_now_iso(), utc_now_iso(), log_date))
        if _minimum_streak(conn, log_date) % 7 == 0 and _minimum_streak(conn, log_date) > 0:
            conn.execute("UPDATE player SET campfire_tokens = campfire_tokens + 2 WHERE id = 1")
            _insert_event(conn, log_date, "streak_bonus", "7-day minimum-set streak: +2 campfire tokens")
        other = _parse_json(workout.get("other_json"), {})
        other["overflow_bonus"] = 1 if overflow > 0 else 0
        conn.execute("UPDATE workout_log SET other_json = ? WHERE date = ?", (json.dumps(other), log_date))
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


def _roll_twist_effect(rng: random.Random) -> dict:
    effects = [
        {"key": "lower_st", "label": "Opening in the Defense", "description": "Success Threshold is reduced by 1 this encounter.", "weight": 2},
        {"key": "raise_st", "label": "Fog of War", "description": "Success Threshold is increased by 1 this encounter.", "weight": 2},
        {"key": "extra_damage", "label": "Escalation", "description": "Threat deals +1 damage on every hit.", "weight": 2},
        {"key": "wider_overwhelm", "label": "Shifting Ground", "description": "Overwhelm target is +1 harder.", "weight": 1},
    ]
    total = sum(effect["weight"] for effect in effects)
    pick = rng.randint(1, total)
    cursor = 0
    for effect in effects:
        cursor += effect["weight"]
        if pick <= cursor:
            return {k: effect[k] for k in ["key", "label", "description"]}
    return {k: effects[0][k] for k in ["key", "label", "description"]}


def _boss_trait(rng: random.Random) -> dict:
    traits = [
        {
            "key": "every_3rd_round_plus_1_damage",
            "label": "Relentless Assault",
            "description": "Every 3rd round the boss deals +1 damage.",
        },
        {
            "key": "guard_twice_st_up",
            "label": "Learns Your Guard",
            "description": "Guard twice in a row and next round ST increases by 1.",
        },
        {
            "key": "half_grit_raise_defeat",
            "label": "Second Wind",
            "description": "First time you drop below half grit, Defeat target rises by +2.",
        },
    ]
    return rng.choice(traits)


def _build_encounter(
    for_date: str,
    level: int,
    theme_key: str,
    seed_extra: int = 0,
    force_boss: bool = False,
    frontier_heat: int = 0,
) -> dict:
    theme = load_theme_pack(theme_key)
    seed = stable_seed(for_date, theme_key, "encounter", str(seed_extra))
    rng = random.Random(seed)

    base_tier = 1 + (max(0, frontier_heat) // 3)
    wobble_roll = rng.randint(1, 6)
    wobble = -1 if wobble_roll <= 2 else (1 if wobble_roll >= 5 else 0)
    tier = max(1, min(4, base_tier + wobble))

    is_boss = force_boss or _is_sunday(for_date)
    threats_key = "boss_threats" if is_boss else "weekday_threats"
    threat_table = theme.get(threats_key, {}).get(str(tier), [])
    threat_name = rng.choice(threat_table) if threat_table else "Unknown Threat"

    locations = theme.get("locations", ["Unknown location"])
    situations = theme.get("situations", ["Unknown situation"])
    twists = theme.get("twists", ["No twist"])
    stakes_pool = theme.get("stakes", ["No stakes"])

    stakes_count = 1 if rng.randint(1, 100) <= 60 else 2
    stakes = rng.sample(stakes_pool, k=min(stakes_count, len(stakes_pool))) if stakes_pool else []

    success_threshold = 2 + (1 if tier >= 2 else 0) + (1 if is_boss else 0)
    damage = rng.randint(2, 4) if is_boss else rng.randint(1, 4)
    defeat_target = 4 + tier + (1 if is_boss else 0)
    overwhelm_target = defeat_target + (3 if is_boss else 2)

    twist_effect = _roll_twist_effect(rng)
    if twist_effect["key"] == "lower_st":
        success_threshold = max(2, success_threshold - 1)
    elif twist_effect["key"] == "raise_st":
        success_threshold = min(5, success_threshold + 1)
    elif twist_effect["key"] == "extra_damage":
        damage += 1
    elif twist_effect["key"] == "wider_overwhelm":
        overwhelm_target += 1

    trait = _boss_trait(rng) if is_boss else None

    return {
        "threat_name": threat_name,
        "tag": "boss" if is_boss else "frontier",
        "reward_table_key": "boss" if is_boss else "default",
        "is_boss": is_boss,
        "special": trait["key"] if trait else None,
        "trait": trait,
        "intensity_tier": tier,
        "intensity_base": base_tier,
        "intensity_wobble": wobble,
        "location": rng.choice(locations),
        "situation": rng.choice(situations),
        "twist": rng.choice(twists),
        "twist_effect": twist_effect,
        "stakes": stakes,
        "success_threshold": success_threshold,
        "damage": damage,
        "damage_dice": 2 if is_boss else 1,
        "defeat_target": defeat_target,
        "overwhelm_target": overwhelm_target,
    }

def get_or_create_daily_roll(for_date: str) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        if row is None:
            player = conn.execute("SELECT level, theme_pack, frontier_heat FROM player WHERE id = 1").fetchone()
            assert player is not None
            encounter = _build_encounter(
                for_date,
                player["level"],
                player["theme_pack"],
                frontier_heat=player["frontier_heat"],
            )
            conn.execute(
                "INSERT INTO daily_roll (date, encounter_json, generated_at) VALUES (?, ?, ?)",
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

def refresh_daily_roll(for_date: str, force_boss: bool = False, seed_extra: int = 999) -> None:
    conn = get_conn()
    try:
        player = conn.execute("SELECT level, theme_pack, frontier_heat FROM player WHERE id = 1").fetchone()
        assert player is not None
        encounter = _build_encounter(
            for_date,
            player["level"],
            player["theme_pack"],
            seed_extra=seed_extra,
            force_boss=force_boss,
            frontier_heat=player["frontier_heat"],
        )
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

def get_inventory() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM inventory_item ORDER BY id DESC").fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["effect"] = _parse_json(item.get("effect_json"), {})
            items.append(item)
        return items
    finally:
        conn.close()


def equip_inventory_item(item_id: int) -> bool:
    conn = get_conn()
    try:
        row = conn.execute("SELECT id, name, type, equipped FROM inventory_item WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return False
        if row["equipped"]:
            conn.execute("UPDATE inventory_item SET equipped = 0 WHERE id = ?", (item_id,))
            _insert_event(conn, today_key(), "inventory", f"Unequipped {row['name']}.")
        else:
            conn.execute("UPDATE inventory_item SET equipped = 0 WHERE type = ?", (row["type"],))
            conn.execute("UPDATE inventory_item SET equipped = 1 WHERE id = ?", (item_id,))
            _insert_event(conn, today_key(), "inventory", f"Equipped {row['name']}.")
        conn.commit()
        return True
    finally:
        conn.close()


def _equipped_effect_totals(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT effect_json FROM inventory_item WHERE equipped = 1").fetchall()
    totals = {"attack": 0, "guard": 0, "grit_bonus": 0}
    for row in rows:
        effect = _parse_json(row["effect_json"], {})
        for key in totals:
            totals[key] += int(effect.get(key, 0) or 0)
    return totals


def _combat_stats_from_player(conn: sqlite3.Connection, player: sqlite3.Row | dict) -> dict:
    effects = _equipped_effect_totals(conn)
    level = player["level"]
    attack = 2 + (level // 2) + effects["attack"]
    guard = 1 + effects["guard"]
    combat_dice = 2
    return {
        "attack": attack,
        "guard": guard,
        "guard_rating": guard,
        "combat_dice": combat_dice,
        "grit_bonus": effects["grit_bonus"],
    }


def _player_attack(level: int, attack_bonus: int = 0) -> int:
    return 2 + (level // 2) + attack_bonus


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


def preview_intensity_tier(for_date: str) -> dict:
    conn = get_conn()
    try:
        player = conn.execute("SELECT level, theme_pack, frontier_heat FROM player WHERE id = 1").fetchone()
        assert player is not None
        encounter = _build_encounter(
            for_date,
            player["level"],
            player["theme_pack"],
            frontier_heat=player["frontier_heat"],
        )
        return {
            "base": encounter["intensity_base"],
            "wobble": encounter["intensity_wobble"],
            "tier": encounter["intensity_tier"],
        }
    finally:
        conn.close()


def set_frontier_heat(value: int) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE player SET frontier_heat = ? WHERE id = 1", (max(0, min(12, int(value))),))
        conn.commit()
    finally:
        conn.close()


def force_generate_roll(for_date: str, force_boss: bool = False) -> None:
    refresh_daily_roll(for_date, force_boss=force_boss, seed_extra=2024)


def _grant_loot_items(conn: sqlite3.Connection, for_date: str, count: int, theme_key: str) -> list[str]:
    theme = load_theme_pack(theme_key)
    loot = theme.get("loot_table", ["Frontier Keepsake"])
    rng = random.Random(stable_seed(for_date, theme_key, "loot", str(count)))
    awarded = []
    for _ in range(count):
        name = rng.choice(loot)
        conn.execute(
            "INSERT INTO inventory_item (name, type, effect_json, equipped) VALUES (?, ?, ?, 0)",
            (name, "loot", json.dumps({}), 0),
        )
        awarded.append(name)
    return awarded


def _compose_frontier_narrative(
    for_date: str,
    encounter: dict,
    outcome: str,
    reward_text: str,
    overflow_bonus: bool,
    player: sqlite3.Row,
) -> str:
    player_data = dict(player)
    theme = load_theme_pack(player["theme_pack"])
    rng = random.Random(stable_seed(for_date, "frontier", "narrative", outcome))
    beat = ""
    if overflow_bonus:
        beat = rng.choice(theme.get("narrative_candy", [])) if theme.get("narrative_candy") else ""
    elif player_data.get("romance_dial") != "off" and outcome == "overwhelm":
        beat = rng.choice(theme.get("romance_light_flirt", [])) if theme.get("romance_light_flirt") else ""
    elif rng.random() < min(0.5, 0.1 + (player_data.get("frontier_heat", 0) * 0.05)):
        beat = rng.choice(theme.get("rival_beats", [])) if theme.get("rival_beats") else ""

    if (player["level"] >= 3 or player_data.get("renown", 0) >= 10) and rng.random() < 0.2:
        beat = rng.choice(theme.get("legacy_events", [])) if theme.get("legacy_events") else beat

    sentence1 = f"At {encounter.get('location', 'the frontier')}, {encounter['threat_name']} turned a routine push into chaos as {encounter.get('twist', 'the situation shifted')}."
    sentence2 = f"{reward_text} {beat}".strip()
    return f"{sentence1} {sentence2}".strip()


def resolve_encounter(for_date: str, action: str = "auto", tempo_bonus: int = 0, push_budget: int = 0) -> dict:
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
        combat_stats = _combat_stats_from_player(conn, player)
        starting_grit_pool = player["grit_current"] + combat_stats["grit_bonus"]

        state = existing or {
            "accumulated_successes": 0,
            "grit_loss": 0,
            "grit_spent_push": 0,
            "round": 0,
            "complete": False,
            "outcome": None,
            "log": [],
            "applied": False,
            "last_action": None,
            "narrative": "",
            "combat_stats": combat_stats,
            "openings": 0,
            "last_round_damage": 0,
            "consequence": None,
            "last_round": {},
        }

        def _count_successes(dice: list[int], st: int) -> int:
            return sum(2 if d == 6 else 1 for d in dice if d >= st)

        def _apply_pushes(base_dice: list[int], max_spend: int, choose_best: bool = True) -> tuple[list[int], int]:
            dice = base_dice[:]
            spent = 0
            candidates = sorted(range(len(dice)), key=lambda i: dice[i]) if choose_best else list(range(len(dice)))
            for idx in candidates:
                while dice[idx] < 6 and spent < max_spend:
                    dice[idx] += 1
                    spent += 1
            return dice, spent

        def _roll_damage(seed_parts: list[str], dice_count: int) -> tuple[list[int], int]:
            rng = random.Random(stable_seed(*seed_parts))
            dice = [rng.randint(1, 6) for _ in range(dice_count)]
            return dice, sum(dice)

        def do_round(chosen: str, manual_push_budget: int = 0) -> None:
            state["round"] += 1
            state["last_action"] = chosen
            st = max(2, min(5, encounter.get("success_threshold", 3)))
            player_seed = [for_date, "combat", str(state["round"]), "player", chosen, str(state["accumulated_successes"])]
            rng = random.Random(stable_seed(*player_seed))
            base_dice = [rng.randint(1, 6) for _ in range(combat_stats["combat_dice"])]
            grit_left = max(0, starting_grit_pool - state["grit_loss"])

            if action == "auto":
                max_push = 0
                needed_over = encounter["overwhelm_target"] - state["accumulated_successes"]
                needed_def = encounter["defeat_target"] - state["accumulated_successes"]
                if needed_over > 0 or needed_def > 0:
                    # cheap heuristic: allow up to grit needed to push both dice to 6 if it can finish this round
                    potential_max = sum(6 - d for d in base_dice)
                    for trial in range(0, min(grit_left, potential_max) + 1):
                        td, _ = _apply_pushes(base_dice, trial)
                        succ = _count_successes(td, st)
                        if succ >= needed_over:
                            max_push = trial
                            break
                    if max_push == 0:
                        for trial in range(0, min(grit_left, potential_max) + 1):
                            td, _ = _apply_pushes(base_dice, trial)
                            succ = _count_successes(td, st)
                            if succ >= needed_def:
                                max_push = trial
                                break
                final_dice, spent = _apply_pushes(base_dice, max_push)
            else:
                spend_cap = max(0, min(grit_left, manual_push_budget + tempo_bonus))
                final_dice, spent = _apply_pushes(base_dice, spend_cap)

            if spent > 0:
                state["grit_loss"] += spent
                state["grit_spent_push"] += spent

            successes = _count_successes(final_dice, st)
            round_summary = {
                "player_base_dice": base_dice,
                "player_final_dice": final_dice,
                "success_threshold": st,
                "successes": successes,
                "action": chosen,
                "push_spent": spent,
                "barrier_rolls": [],
                "barrier_total": 0,
                "threat_damage_rolls": [],
                "threat_damage_raw": 0,
                "threat_damage_after_barrier": 0,
            }

            incoming_bonus = encounter.get("damage", 1)
            if encounter.get("special") == "every_3rd_round_plus_1_damage" and state["round"] % 3 == 0:
                incoming_bonus += 1
            damage_dice = max(1, int(encounter.get("damage_dice", 1)))
            damage_rolls, damage_raw = _roll_damage([for_date, "combat", str(state["round"]), "threat"], damage_dice)
            incoming = max(0, damage_raw + incoming_bonus - 1)
            round_summary["threat_damage_rolls"] = damage_rolls
            round_summary["threat_damage_raw"] = damage_raw

            chosen = {"fight": "strike", "defend": "guard"}.get(chosen, chosen)
            if chosen == "strike":
                state["accumulated_successes"] += successes
                if state["accumulated_successes"] >= encounter["overwhelm_target"]:
                    state["complete"] = True
                    state["outcome"] = "overwhelm"
                    incoming = 0
                elif state["accumulated_successes"] >= encounter["defeat_target"]:
                    state["complete"] = True
                    state["outcome"] = "defeat"
                state["grit_loss"] += incoming
            elif chosen == "guard":
                state["accumulated_successes"] += 1 if successes > 0 else 0
                barrier_rolls, barrier_total = _roll_damage([for_date, "combat", str(state["round"]), "barrier"], successes)
                incoming = max(0, incoming - barrier_total)
                round_summary["barrier_rolls"] = barrier_rolls
                round_summary["barrier_total"] = barrier_total
                if state["accumulated_successes"] >= encounter["overwhelm_target"]:
                    state["complete"] = True
                    state["outcome"] = "overwhelm"
                    incoming = 0
                elif state["accumulated_successes"] >= encounter["defeat_target"]:
                    state["complete"] = True
                    state["outcome"] = "defeat"
                state["grit_loss"] += incoming
            elif chosen == "flee":
                flee_st = min(6, st + 1)
                flee_successes = _count_successes(final_dice, flee_st)
                round_summary["success_threshold"] = flee_st
                round_summary["successes"] = flee_successes
                if flee_successes >= 2:
                    state["complete"] = True
                    state["outcome"] = "fled"
                    incoming = 1
                state["grit_loss"] += incoming

            round_summary["threat_damage_after_barrier"] = incoming
            state["last_round_damage"] = incoming
            state["last_round"] = round_summary
            state["log"].append(
                f"R{state['round']} {chosen}: dice {final_dice} vs ST {round_summary['success_threshold']} => {round_summary['successes']} successes; damage {incoming}."
            )

            if not state["complete"] and state["grit_loss"] >= starting_grit_pool:
                state["complete"] = True
                state["outcome"] = "survived_with_consequence"

            if state["complete"] and state["outcome"] in {"overwhelm", "defeat"}:
                target = encounter["overwhelm_target"] if state["outcome"] == "overwhelm" else encounter["defeat_target"]
                openings = max(0, state["accumulated_successes"] - target)
                state["openings"] = openings
                if state["last_round_damage"] > 0 and openings > 0:
                    reduced = min(openings, state["last_round_damage"])
                    state["last_round_damage"] -= reduced
                    state["grit_loss"] -= reduced
                    round_summary["threat_damage_after_barrier"] = state["last_round_damage"]
                    openings -= reduced
                state["openings"] = openings

        if action == "auto":
            while not state["complete"] and state["grit_loss"] < starting_grit_pool:
                grit_left = max(0, starting_grit_pool - state["grit_loss"])
                choice = "guard" if grit_left <= encounter.get("damage", 1) + 1 else "strike"
                do_round(choice)
        elif not state["complete"] and state["grit_loss"] < starting_grit_pool:
            do_round(action, push_budget)

        if state["complete"] and not state["applied"]:
            workout = ensure_workout_log(for_date)
            overflow_bonus = 1 if _parse_json(workout.get("other_json"), {}).get("overflow_bonus") else 0

            end_grit = max(0, starting_grit_pool - state["grit_loss"] - combat_stats["grit_bonus"])
            rng = random.Random(stable_seed(for_date, player["theme_pack"], "reward", state["outcome"]))
            if state["outcome"] == "overwhelm":
                coins = rng.randint(3, 6)
            elif state["outcome"] == "defeat":
                coins = rng.randint(1, 3)
            else:
                coins = 0
            coins += overflow_bonus + int(state.get("openings", 0))

            heat_delta = 2 if state["outcome"] == "overwhelm" else (1 if state["outcome"] == "defeat" else -1 if state["outcome"] == "survived_with_consequence" else 0)
            renown_delta = 1 if state["outcome"] == "overwhelm" else (-1 if state["outcome"] == "survived_with_consequence" else 0)

            if state["outcome"] == "survived_with_consequence":
                state["consequence"] = "lost_coins"
                lost = min(2, player["coins"] + coins)
                coins -= lost
                state["log"].append(f"Consequence: lost {lost} coins while recovering.")

            conn.execute(
                "UPDATE player SET grit_current = ?, coins = MAX(coins + ?, 0), frontier_heat = MAX(frontier_heat + ?, 0), renown = MAX(renown + ?, 0) WHERE id = 1",
                (max(1, end_grit) if state["outcome"] == "survived_with_consequence" else end_grit, coins, heat_delta, renown_delta),
            )

            loot_count = 0
            if state["outcome"] == "overwhelm":
                loot_count += 1
            if encounter.get("is_boss") and state["outcome"] in {"defeat", "overwhelm"}:
                loot_count += 2
            loot_awarded = _grant_loot_items(conn, for_date, loot_count, player["theme_pack"]) if loot_count else []

            reward_text = f"You earned +{coins} coins"
            if state.get("openings"):
                reward_text += f" ({state['openings']} from Openings)"
            if renown_delta:
                reward_text += f", +{renown_delta} renown"
            if loot_awarded:
                reward_text += f", and loot: {loot_awarded[0]}"
            reward_text += "."

            state["narrative"] = _compose_frontier_narrative(for_date, encounter, state["outcome"], reward_text, bool(overflow_bonus), player)
            state["coins_earned"] = coins
            state["renown_earned"] = renown_delta
            state["heat_delta"] = heat_delta
            state["loot_awarded"] = loot_awarded
            state["applied"] = True
            _insert_event(conn, for_date, "encounter", state["narrative"], {"outcome": state["outcome"], "coins": coins, "heat": heat_delta})
            conn.execute("UPDATE daily_roll SET encounter_json=?, result_json=?, resolved_at=? WHERE date=?", (json.dumps(encounter), json.dumps(state), utc_now_iso(), for_date))
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
        current = conn.execute("SELECT grit_current, grit_max, level FROM player WHERE id=1").fetchone()
        assert current is not None
        stats = _combat_stats_from_player(conn, current)
        restored = min(current["grit_max"] + stats["grit_bonus"], current["grit_current"] + int(result.get("grit_loss", 0)))
        conn.execute("UPDATE player SET campfire_tokens = campfire_tokens - 1, grit_current = ? WHERE id = 1", (restored,))
        _insert_event(conn, for_date, "token", "Spent token to negate tonight's damage.")
        conn.commit()
        return True
    finally:
        conn.close()


def spend_token_reroll_encounter(for_date: str) -> bool:
    conn = get_conn()
    try:
        player = conn.execute("SELECT campfire_tokens, level, theme_pack, frontier_heat FROM player WHERE id = 1").fetchone()
        row = conn.execute("SELECT resolved_at FROM daily_roll WHERE date = ?", (for_date,)).fetchone()
        if not player or player["campfire_tokens"] < 1 or (row and row["resolved_at"]):
            return False
        encounter = _build_encounter(for_date, player["level"], player["theme_pack"], seed_extra=999, frontier_heat=player["frontier_heat"])
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
            theme = load_theme_pack(player["theme_pack"] if player else "frontier_kingdom")
            rng = random.Random(stable_seed(for_date, (player["theme_pack"] if player else "frontier_kingdom"), "sidequest"))

            requirement = rng.choice([
                {"kind": "bike_minutes", "target": 10, "label": "10 min bike"},
                {"kind": "km", "target": 1, "label": "1 km"},
                {"kind": "mobility_minutes", "target": 10, "label": "10 min mobility"},
            ])
            prompt = rng.choice(theme.get("sidequest_prompts", ["Deliver medicine over rough ground (race the clock)"]))
            reward_kind = rng.choice(["token", "coins", "loot"])
            reward_amount = rng.randint(3, 6) if reward_kind == "coins" else None
            quest = {
                "prompt": prompt,
                "kind": requirement["kind"],
                "target": requirement["target"],
                "requirement_label": requirement["label"],
                "reward_kind": reward_kind,
                "reward_amount": reward_amount,
                "text": f"{prompt} — Requirement: {requirement['label']}",
                "chain": ["Approach", "Complication", "Resolution"],
            }
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
        result = {"success": success, "progress": progress, "needed": int(quest["target"]), "reward": None}

        if success:
            reward_kind = quest.get("reward_kind", "token")
            player = conn.execute("SELECT sidequests_completed, theme_pack FROM player WHERE id = 1").fetchone()
            assert player is not None
            if reward_kind == "token":
                conn.execute("UPDATE player SET campfire_tokens = campfire_tokens + 1, sidequests_completed = sidequests_completed + 1 WHERE id = 1")
                result["reward"] = "+1 token"
            elif reward_kind == "coins":
                coins = int(quest.get("reward_amount") or random.randint(3, 6))
                conn.execute("UPDATE player SET coins = coins + ?, sidequests_completed = sidequests_completed + 1 WHERE id = 1", (coins,))
                result["reward"] = f"+{coins} coins"
            else:
                _grant_loot_items(conn, for_date, 1, player["theme_pack"])
                conn.execute("UPDATE player SET sidequests_completed = sidequests_completed + 1 WHERE id = 1")
                result["reward"] = "+1 loot"

            player2 = conn.execute("SELECT sidequests_completed, theme_pack FROM player WHERE id = 1").fetchone()
            assert player2 is not None
            if player2["sidequests_completed"] % 2 == 0:
                _progress_leveling(conn, for_date, 1, "sidequest pair")

            line = narrative_line(load_theme_pack(player2["theme_pack"]), "romance_light_flirt", stable_seed(for_date, "sidequest", "narrative"), "Side quest completed.")
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
        inventory_rows = conn.execute("SELECT * FROM inventory_item ORDER BY id DESC").fetchall()
        inventory = []
        for item_row in inventory_rows:
            item = dict(item_row)
            item["effect"] = _parse_json(item.get("effect_json"), {})
            inventory.append(item)
        combat_stats = _combat_stats_from_player(conn, player)
        return {"player": dict(player), "streak": streak, "boss_in_days": (next_sunday - date.fromisoformat(for_date)).days, "events": [dict(e) for e in events], "inventory": inventory, "combat_stats": combat_stats}
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



def was_reminder_sent(kind: str, for_date: str) -> bool:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM event_log WHERE date = ? AND kind = ? LIMIT 1",
            (for_date, f"reminder_{kind}"),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def mark_reminder_sent(kind: str, for_date: str) -> None:
    conn = get_conn()
    try:
        if not was_reminder_sent(kind, for_date):
            _insert_event(conn, for_date, f"reminder_{kind}", f"Sent {kind} reminder")
            conn.commit()
    finally:
        conn.close()


def get_schedule_context(now_utc: datetime | None = None) -> dict:
    now_utc = now_utc or datetime.now(timezone.utc)
    player = get_player()
    tz = _player_zoneinfo(player)
    local = now_utc.astimezone(tz)
    return {
        "timezone": str(tz),
        "local_date": local.date().isoformat(),
        "local_hour": local.hour,
        "local_minute": local.minute,
    }

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
