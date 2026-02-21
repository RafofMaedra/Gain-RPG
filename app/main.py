from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import (
    MINIMUM_SET,
    apply_minimum_set,
    calculate_grit_restore,
    complete_sidequest,
    equip_inventory_item,
    export_save_data,
    get_or_create_daily_roll,
    get_encounter_round_preview,
    get_or_create_sidequest,
    get_player,
    get_progress_snapshot,
    get_workout_log,
    import_save_data,
    init_db,
    lock_in_workout,
    force_generate_roll,
    preview_intensity_tier,
    refresh_daily_roll,
    resolve_encounter,
    run_midnight_tick,
    should_send_evening_nudge,
    spend_token_for_minimum_set,
    spend_token_negate_tonight_damage,
    spend_token_reroll_encounter,
    testing_advance_day,
    today_key,
    set_frontier_heat,
    update_settings,
    update_workout_reps,
)

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Gain RPG")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


@app.on_event("startup")
def startup() -> None:
    init_db()


def today_context() -> dict:
    today = today_key()
    player = get_player()
    workout = get_workout_log(today)
    daily_roll = get_or_create_daily_roll(today)
    sidequest = get_or_create_sidequest(today)
    preview_grit = calculate_grit_restore(
        workout["pushups"],
        workout["situps"],
        workout["squats"],
        workout["pullups"],
    )
    intensity_preview = preview_intensity_tier(today)
    encounter = daily_roll.get("encounter", {}) if isinstance(daily_roll, dict) else {}
    if not isinstance(encounter, dict):
        encounter = {}
    if not isinstance(encounter.get("stakes"), list):
        encounter["stakes"] = []
    encounter_result = daily_roll.get("result") if isinstance(daily_roll, dict) else None
    if encounter_result is not None and not isinstance(encounter_result, dict):
        encounter_result = None
    return {
        "today": today,
        "player": player,
        "workout": workout,
        "encounter": encounter,
        "encounter_result": encounter_result,
        "sidequest": sidequest,
        "preview_grit": preview_grit,
        "minimum_set": MINIMUM_SET,
        "page": "today",
        "needs_evening_nudge": should_send_evening_nudge(today),
        "intensity_preview": intensity_preview,
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("today.html", {"request": request, **today_context()})


@app.get("/progress", response_class=HTMLResponse)
def progress(request: Request) -> HTMLResponse:
    today = today_key()
    snap = get_progress_snapshot(today)
    return templates.TemplateResponse("progress.html", {"request": request, "page": "progress", "today": today, **snap})


@app.post("/workout/minimum-set")
def minimum_set() -> RedirectResponse:
    apply_minimum_set(today_key())
    return RedirectResponse(url="/", status_code=303)


@app.post("/workout/save")
def save_workout(
    pushups: int = Form(...),
    situps: int = Form(...),
    squats: int = Form(...),
    pullups: int = Form(...),
) -> RedirectResponse:
    update_workout_reps(today_key(), pushups, situps, squats, pullups)
    return RedirectResponse(url="/", status_code=303)


@app.post("/workout/lock-in")
def lock_in() -> RedirectResponse:
    lock_in_workout(today_key())
    return RedirectResponse(url="/", status_code=303)


@app.post("/encounter/auto")
def encounter_auto() -> RedirectResponse:
    resolve_encounter(today_key(), action="auto")
    return RedirectResponse(url="/", status_code=303)


@app.post("/encounter/manual")
def encounter_manual(action: str = Form(...), tempo_bonus: int = Form(0), push_budget: int = Form(0), push_red: int = Form(0), push_green: int = Form(0)) -> RedirectResponse:
    resolve_encounter(today_key(), action=action, tempo_bonus=max(0, min(2, tempo_bonus)), push_budget=max(0, min(6, push_budget)), push_red=max(0, min(6, push_red)), push_green=max(0, min(6, push_green)))
    return RedirectResponse(url="/", status_code=303)



@app.get("/api/encounter/status", response_class=JSONResponse)
def encounter_status() -> JSONResponse:
    today = today_key()
    roll = get_or_create_daily_roll(today)
    player = get_player()
    result = roll.get("result") if isinstance(roll, dict) else None
    live_grit = player.get("grit_current")
    if isinstance(result, dict) and not result.get("complete"):
        live_grit = result.get("grit_remaining_live", live_grit)
    return JSONResponse({"encounter": roll.get("encounter", {}), "result": result, "player": {"grit_current": live_grit, "grit_max": player.get("grit_max")}})


@app.post("/api/encounter/preview", response_class=JSONResponse)
def encounter_preview(action: str = Form(...)) -> JSONResponse:
    today = today_key()
    preview = get_encounter_round_preview(today, action=action)
    return JSONResponse(preview)


@app.post("/api/encounter/step", response_class=JSONResponse)
def encounter_step(action: str = Form(...), push_budget: int = Form(0), tempo_bonus: int = Form(0), push_red: int = Form(0), push_green: int = Form(0)) -> JSONResponse:
    today = today_key()
    result = resolve_encounter(today, action=action, push_budget=max(0, min(12, push_budget)), tempo_bonus=max(0, min(2, tempo_bonus)), push_red=max(0, min(6, push_red)), push_green=max(0, min(6, push_green)))
    player = get_player()
    roll = get_or_create_daily_roll(today)
    live_grit = player.get("grit_current")
    if isinstance(result, dict) and not result.get("complete"):
        live_grit = result.get("grit_remaining_live", live_grit)
    return JSONResponse({"encounter": roll.get("encounter", {}), "result": result, "player": {"grit_current": live_grit, "grit_max": player.get("grit_max")}})


@app.post("/encounter/refresh")
def encounter_refresh() -> RedirectResponse:
    if get_player()["testing_mode"]:
        refresh_daily_roll(today_key())
    return RedirectResponse(url="/", status_code=303)




@app.post("/tokens/minimum-set")
def token_minimum_set() -> RedirectResponse:
    spend_token_for_minimum_set(today_key())
    return RedirectResponse(url="/", status_code=303)


@app.post("/tokens/negate-damage")
def token_negate_damage() -> RedirectResponse:
    spend_token_negate_tonight_damage(today_key())
    return RedirectResponse(url="/", status_code=303)


@app.post("/tokens/reroll")
def token_reroll() -> RedirectResponse:
    spend_token_reroll_encounter(today_key())
    return RedirectResponse(url="/", status_code=303)

@app.post("/sidequest/complete")
def sidequest_complete(
    bike_minutes: int = Form(0),
    km: int = Form(0),
    mobility_minutes: int = Form(0),
) -> RedirectResponse:
    complete_sidequest(today_key(), bike_minutes, km, mobility_minutes)
    return RedirectResponse(url="/", status_code=303)




@app.post("/inventory/equip")
def inventory_equip(item_id: int = Form(...)) -> RedirectResponse:
    equip_inventory_item(item_id)
    return RedirectResponse(url="/progress", status_code=303)

@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request) -> HTMLResponse:
    player = get_player()
    return templates.TemplateResponse("settings.html", {"request": request, "player": player, "page": "settings", "saved": False})


@app.post("/settings", response_class=HTMLResponse)
def save_settings(
    request: Request,
    name: str = Form(...),
    theme_pack: str = Form(...),
    testing_mode: bool = Form(False),
    discord_webhook_url: str = Form(""),
    ntfy_topic_url: str = Form(""),
    day_timezone: str = Form("Pacific/Auckland"),
    romance_dial: str = Form("light_flirt"),
) -> HTMLResponse:
    update_settings(
        name=name,
        theme_pack=theme_pack,
        testing_mode=testing_mode,
        discord_webhook_url=discord_webhook_url,
        ntfy_topic_url=ntfy_topic_url,
        day_timezone=day_timezone,
        romance_dial=romance_dial,
    )
    player = get_player()
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("settings_form.html", {"request": request, "player": player, "saved": True})

    return RedirectResponse(url="/settings", status_code=303)


@app.post("/testing/advance-day")
def advance_day() -> RedirectResponse:
    if get_player()["testing_mode"]:
        testing_advance_day(1)
        run_midnight_tick()
    return RedirectResponse(url="/", status_code=303)




@app.post("/testing/set-heat")
def testing_set_heat(value: int = Form(...)) -> RedirectResponse:
    if get_player()["testing_mode"]:
        set_frontier_heat(value)
    return RedirectResponse(url="/", status_code=303)


@app.post("/testing/force-roll")
def testing_force_roll(for_date: str = Form(...)) -> RedirectResponse:
    if get_player()["testing_mode"]:
        force_generate_roll(for_date, force_boss=False)
    return RedirectResponse(url="/", status_code=303)


@app.post("/testing/force-boss-today")
def testing_force_boss_today() -> RedirectResponse:
    if get_player()["testing_mode"]:
        force_generate_roll(today_key(), force_boss=True)
    return RedirectResponse(url="/", status_code=303)


@app.post("/testing/reroll-free")
def testing_reroll_free() -> RedirectResponse:
    if get_player()["testing_mode"]:
        force_generate_roll(today_key(), force_boss=False)
    return RedirectResponse(url="/", status_code=303)

@app.get("/export")
def export_save() -> JSONResponse:
    return JSONResponse(export_save_data())


@app.post("/import")
def import_save(payload: str = Form(...)) -> RedirectResponse:
    import_save_data(json.loads(payload))
    return RedirectResponse(url="/settings", status_code=303)
