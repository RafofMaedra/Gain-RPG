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

## Midnight tick job

Run this from cron/systemd timer:

```bash
python -m app.jobs.midnight_tick
```
