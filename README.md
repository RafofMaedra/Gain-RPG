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

## Scheduling jobs

Recommended: run one frequent scheduler (every 5-10 minutes) and let it trigger time-specific actions using your configured `day_timezone`.

```bash
python -m app.jobs.schedule_runner
```

It will:
- run midnight tick + midnight summary around `00:00`
- send morning reminder around `08:00`
- send evening nudge around `19:00` (only when minimum set is missing)


Example crontab (every 5 minutes):

```cron
*/5 * * * * cd /path/to/Gain-RPG && /path/to/venv/bin/python -m app.jobs.schedule_runner
```

You can also run commands directly:

```bash
python -m app.jobs.midnight_tick
python -m app.jobs.reminders morning
python -m app.jobs.reminders evening
python -m app.jobs.reminders midnight
```

## Theme packs

Default content pack files live in `app/theme_packs/default/`.
You can add another folder and set `theme_pack` in Settings to load it.


## Test build checks

```bash
python -m compileall app
python -m unittest discover -s tests -v
```
