from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import get_player, init_db, update_settings

app = FastAPI(title="Gain RPG")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    player = get_player()
    return templates.TemplateResponse(
        request,
        "today.html",
        {
            "player": player,
            "page": "today",
        },
    )


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
