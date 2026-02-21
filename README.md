# Gain RPG

Self-hosted FastAPI + SQLite workout RPG app.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## Jobs (cron/systemd timer)

```bash
python -m app.jobs.midnight_tick
python -m app.jobs.reminders morning
python -m app.jobs.reminders evening
python -m app.jobs.reminders midnight
```

## Theme packs

Default content pack files live in `app/theme_packs/default/`.
You can add another folder and set `theme_pack` in Settings to load it.
