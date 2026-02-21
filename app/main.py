from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import (
    MINIMUM_SET,
    apply_minimum_set,
    calculate_grit_restore,
    get_or_create_daily_roll,
    get_player,
    get_workout_log,
    init_db,
    lock_in_workout,
    resolve_encounter,
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
        "preview_grit": preview_grit,
        "minimum_set": MINIMUM_SET,
        "page": "today",
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "today.html", today_context())


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
) -> HTMLResponse:
    update_settings(name=name, theme_pack=theme_pack, testing_mode=testing_mode)
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
