#!/usr/bin/env python3
"""
Gain RPG - One-click launcher (FastAPI + SQLite)

What it does:
- Creates .venv if missing
- Installs requirements.txt into .venv
- Starts the FastAPI server (uvicorn)
- Optionally starts the scheduler runner in the background

Usage:
  Double-click: starts server at http://127.0.0.1:8000
  CLI options:
    python run_gain_rpg.py --scheduler       # scheduler only
    python run_gain_rpg.py --both            # server + scheduler
    python run_gain_rpg.py --no-install      # skip pip install
    python run_gain_rpg.py --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import textwrap
import time
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"


def is_windows() -> bool:
    return platform.system().lower().startswith("win")


def venv_python_path() -> Path:
    if is_windows():
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> int:
    # Print the command so you can see what it's doing
    print("\n> " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(cwd or PROJECT_ROOT), check=check).returncode


def ensure_project_layout() -> None:
    req = PROJECT_ROOT / "requirements.txt"
    app_pkg = PROJECT_ROOT / "app"
    if not req.exists():
        raise FileNotFoundError(f"Missing requirements.txt in {PROJECT_ROOT}")
    if not app_pkg.exists():
        raise FileNotFoundError(f"Missing app/ package in {PROJECT_ROOT}")
    if not (app_pkg / "main.py").exists() and not (app_pkg / "main" / "__init__.py").exists():
        # Not fatal, but likely wrong folder
        print("Warning: couldn't confirm app.main exists. If startup fails, verify you're in the project root.")


def ensure_venv() -> Path:
    py = venv_python_path()
    if py.exists():
        return py

    print(f"Creating virtual environment at: {VENV_DIR}")
    run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if not py.exists():
        raise RuntimeError(f"Virtualenv created but python not found at: {py}")
    return py


def pip_install(venv_py: Path) -> None:
    req = PROJECT_ROOT / "requirements.txt"
    print("Upgrading pip...")
    run([str(venv_py), "-m", "pip", "install", "--upgrade", "pip"])
    print("Installing requirements...")
    run([str(venv_py), "-m", "pip", "install", "-r", str(req)])

    if is_windows():
        print("Checking zoneinfo timezone data (Windows)...")
        try:
            run([str(venv_py), "-c", "from zoneinfo import ZoneInfo; ZoneInfo('UTC')"])
        except subprocess.CalledProcessError:
            print("Installing tzdata for zoneinfo support on Windows...")
            run([str(venv_py), "-m", "pip", "install", "tzdata"])


def start_scheduler(venv_py: Path) -> subprocess.Popen:
    # Runs: python -m app.jobs.schedule_runner
    print("Starting scheduler runner in background...")
    creationflags = 0
    if is_windows():
        # Avoid opening a second console window
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    return subprocess.Popen(
        [str(venv_py), "-m", "app.jobs.schedule_runner"],
        cwd=str(PROJECT_ROOT),
        creationflags=creationflags,
    )


def start_server(venv_py: Path, host: str, port: int, reload: bool) -> int:
    # Runs: python -m uvicorn app.main:app --reload
    cmd = [str(venv_py), "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")

    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}"
    print(f"\nStarting server: {url}")
    print("Press Ctrl+C to stop.\n")

    # Give uvicorn a moment, then open browser
    def open_later():
        time.sleep(1.0)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # Fire-and-forget thread without importing threading (keep dependencies minimal)
    import threading  # stdlib

    threading.Thread(target=open_later, daemon=True).start()

    return run(cmd, check=False)


def pause_on_exit_if_double_clicked() -> None:
    # If launched by double-click on Windows, the console may vanish instantly on error.
    if is_windows() and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nPress Enter to close...")
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="Gain RPG Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """
            One-click launcher for Gain RPG.

            Modes:
              (default) server only
              --scheduler  scheduler only
              --both       server + scheduler
            """
        ).strip(),
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scheduler", action="store_true", help="Run only the scheduler runner")
    mode.add_argument("--both", action="store_true", help="Run server + scheduler runner")

    parser.add_argument("--no-install", action="store_true", help="Skip pip install (assumes .venv is ready)")
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    parser.add_argument("--no-reload", action="store_true", help="Disable uvicorn --reload")

    args = parser.parse_args()

    ensure_project_layout()
    venv_py = ensure_venv()

    if not args.no_install:
        pip_install(venv_py)

    reload = not args.no_reload

    if args.scheduler:
        print("Running scheduler runner (Ctrl+C to stop)...\n")
        return run([str(venv_py), "-m", "app.jobs.schedule_runner"], check=False)

    sched_proc: subprocess.Popen | None = None
    if args.both:
        sched_proc = start_scheduler(venv_py)

    try:
        return start_server(venv_py, args.host, args.port, reload)
    finally:
        if sched_proc is not None and sched_proc.poll() is None:
            print("\nStopping scheduler runner...")
            try:
                sched_proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise
    except Exception as e:
        print(f"\nERROR: {e}")
        pause_on_exit_if_double_clicked()
        raise