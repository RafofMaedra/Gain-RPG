from __future__ import annotations

import json

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
    get_or_create_sidequest,
    get_player,
    get_progress_snapshot,
    get_workout_log,
    import_save_data,
    init_db,
    lock_in_workout,
    refresh_daily_roll,
    resolve_encounter,
    run_midnight_tick,
    should_send_evening_nudge,
    spend_token_for_minimum_set,
    spend_token_negate_tonight_damage,
    spend_token_reroll_encounter,
    testing_advance_day,
    today_key,
    update_settings,
    update_workout_reps,
)

app = FastAPI(title="Gain RPG")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


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
    return {
        "today": today,
        "player": player,
        "workout": workout,
        "encounter": daily_roll["encounter"],
        "encounter_result": daily_roll["result"],
        "sidequest": sidequest,
        "preview_grit": preview_grit,
        "minimum_set": MINIMUM_SET,
        "page": "today",
        "needs_evening_nudge": should_send_evening_nudge(today),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "today.html", today_context())


@app.get("/progress", response_class=HTMLResponse)
def progress(request: Request) -> HTMLResponse:
    today = today_key()
    snap = get_progress_snapshot(today)
    return templates.TemplateResponse(
        request,
        "progress.html",
        {"page": "progress", "today": today, **snap},
    )


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
def encounter_manual(action: str = Form(...)) -> RedirectResponse:
    resolve_encounter(today_key(), action=action)
    return RedirectResponse(url="/", status_code=303)


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
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "player": player,
            "page": "settings",
            "saved": False,
        },
    )


@app.post("/settings", response_class=HTMLResponse)
def save_settings(
    request: Request,
    name: str = Form(...),
    theme_pack: str = Form(...),
    testing_mode: bool = Form(False),
    discord_webhook_url: str = Form(""),
    ntfy_topic_url: str = Form(""),
    day_timezone: str = Form("Pacific/Auckland"),
) -> HTMLResponse:
    update_settings(
        name=name,
        theme_pack=theme_pack,
        testing_mode=testing_mode,
        discord_webhook_url=discord_webhook_url,
        ntfy_topic_url=ntfy_topic_url,
        day_timezone=day_timezone,
    )
    player = get_player()
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "settings_form.html",
            {
                "player": player,
                "saved": True,
            },
        )

    return RedirectResponse(url="/settings", status_code=303)


@app.post("/testing/advance-day")
def advance_day() -> RedirectResponse:
    if get_player()["testing_mode"]:
        testing_advance_day(1)
        run_midnight_tick()
    return RedirectResponse(url="/", status_code=303)


@app.get("/export")
def export_save() -> JSONResponse:
    return JSONResponse(export_save_data())


@app.post("/import")
def import_save(payload: str = Form(...)) -> RedirectResponse:
    import_save_data(json.loads(payload))
    return RedirectResponse(url="/settings", status_code=303)
