from __future__ import annotations

import argparse
import threading
import time

from .config import settings
from .db import TrackerDb
from .events import Event
from .parser import LogParser
from .state import RunBuilder
from .tailer import follow_file_lines, replay_file_lines

# OCR / screenshot / Supabase pull in heavy or optional dependencies
# (opencv, pytesseract, requests, dotenv). They're only needed for live
# tracking, so they're imported lazily inside the functions below --
# `--replay` should run with nothing but the standard library installed.


def _handle_run_end(run_builder: RunBuilder) -> None:
    """
    Runs after a RunEnd event: capture the final board screenshot and OCR it
    into run_metrics. Best-effort -- a run still gets synced without metrics
    once the grace period in sync.py elapses.
    """
    run_id = run_builder._last_ended_run_id
    if run_id is None or not settings.enable_screenshots:
        return

    def _worker() -> None:
        from .ocr_metrics import extract_run_metrics
        from .ocr_rois import ROIS
        from .screenshot import capture_final_board

        time.sleep(settings.screenshot_delay_seconds)
        path = capture_final_board(settings.screenshot_dir)
        if not path:
            return
        try:
            metrics = extract_run_metrics(path, ROIS)
            # sqlite3 connections can't cross threads -- this runs on its
            # own thread, so it needs its own connection rather than reusing
            # the one the main thread's TrackerDb opened (that raised
            # ProgrammingError on every call, silently swallowed below).
            worker_db = TrackerDb(settings.db_path)
            try:
                worker_db.save_run_metrics(run_id, metrics)
            finally:
                worker_db.close()
            print(f"[OCR] run {run_id} metrics: {metrics}")
        except Exception as e:
            print(f"[OCR] failed for run {run_id}: {e!r}")

    threading.Thread(target=_worker, daemon=True).start()


def _sync_loop(db_path: str) -> None:
    from .sync import sync_pending_runs

    # Own connection for the same reason as the OCR worker above -- this
    # runs on a background thread and the main thread's TrackerDb.conn
    # can't be touched from here.
    db = TrackerDb(db_path)

    while True:
        time.sleep(settings.sync_interval_seconds)
        try:
            sync_pending_runs(db)
        except Exception as e:
            print(f"[Sync] loop error: {e!r}")


def run_live() -> None:
    import os
    import sys
    from pathlib import Path

    try:
        from dotenv import load_dotenv

        if getattr(sys, "frozen", False):
            # Frozen (PyInstaller) build: cwd isn't reliable depending on how
            # the exe was launched, so look for .env next to the exe itself.
            env_path = Path(sys.executable).parent / ".env"
        else:
            env_path = Path.cwd() / ".env"

        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            print(f"[Tracker] .env found: {env_path}")
        else:
            print(f"[Tracker] no .env at {env_path} -- that's fine, Supabase can also be "
                  f"configured from the dashboard's Paramètres page")
    except Exception as e:
        print(f"[Tracker] .env loading failed: {e!r}")

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if supabase_url and supabase_key:
        print("[Tracker] Supabase configured from .env")
    else:
        print("[Tracker] Supabase not set in .env -- checking saved dashboard settings instead")

    db = TrackerDb(settings.db_path)
    parser = LogParser()
    run_builder = RunBuilder(db)

    threading.Thread(target=_sync_loop, args=(settings.db_path,), daemon=True).start()

    if settings.enable_web:
        from .web import run_web

        threading.Thread(
            target=run_web,
            args=(settings.db_path, settings.web_port, supabase_url, supabase_key),
            daemon=True,
        ).start()
        threading.Timer(
            1.0, lambda: __import__("webbrowser").open(f"http://127.0.0.1:{settings.web_port}")
        ).start()
        print(f"[Tracker] local dashboard: http://127.0.0.1:{settings.web_port}")

    print(f"[Tracker] watching {settings.log_path}")
    print(f"[Tracker] local db: {settings.db_path}")

    for line in follow_file_lines(settings.log_path, poll_interval_seconds=settings.poll_interval_seconds):
        ev = parser.parse_line(line)
        if ev is None:
            continue

        ev.observed_at = time.time()
        run_builder.handle(ev)

        if ev.type == "RunEnd":
            _handle_run_end(run_builder)


def run_replay(path: str, db_path: str) -> None:
    """
    Feeds a static log file through the same parser + RunBuilder pipeline,
    without screenshots/OCR/network sync, and prints a summary. Used to
    validate the parser against tests/sample_run.log.
    """
    db = TrackerDb(db_path)
    parser = LogParser()
    run_builder = RunBuilder(db)

    event_counts: dict[str, int] = {}

    for line in replay_file_lines(path):
        ev = parser.parse_line(line)
        if ev is None:
            continue
        ev.observed_at = time.time()
        event_counts[ev.type] = event_counts.get(ev.type, 0) + 1
        run_builder.handle(ev)

    print("Event counts:")
    for t, c in sorted(event_counts.items()):
        print(f"  {t}: {c}")

    cur = db.conn.cursor()
    cur.execute("SELECT * FROM runs ORDER BY run_id")
    for row in cur.fetchall():
        run = dict(row)
        print(f"\nRun {run['run_id']}: hero={run['hero']} mode={run['game_mode']} "
              f"result={run['result']} rank_delta={run['rank_delta']}")

        cur.execute("SELECT COUNT(*), SUM(sold_at IS NOT NULL) FROM run_items WHERE run_id = ?", (run["run_id"],))
        total_items, sold_items = cur.fetchone()
        print(f"  items: {total_items} purchased, {sold_items or 0} sold")

        cur.execute(
            "SELECT combat_type, COUNT(*) FROM run_combats WHERE run_id = ? GROUP BY combat_type",
            (run["run_id"],),
        )
        for combat_type, count in cur.fetchall():
            print(f"  combats ({combat_type}): {count}")

        cur.execute("SELECT COUNT(*) FROM run_rerolls WHERE run_id = ?", (run["run_id"],))
        print(f"  rerolls: {cur.fetchone()[0]}")

        cur.execute("SELECT COUNT(*) FROM run_skills WHERE run_id = ?", (run["run_id"],))
        print(f"  skills selected: {cur.fetchone()[0]}")

    db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Bazaar Tracker")
    ap.add_argument("--replay", metavar="LOG_FILE", help="Replay a static log file instead of tailing live")
    ap.add_argument("--replay-db", default=":memory:", help="SQLite path for --replay (default: in-memory)")
    args = ap.parse_args()

    if args.replay:
        run_replay(args.replay, args.replay_db)
    else:
        run_live()


if __name__ == "__main__":
    main()
