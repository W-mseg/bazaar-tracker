from __future__ import annotations

import os
import time
from typing import Any

import requests

from .db import TrackerDb

# Below this many seconds since the run ended, we still wait for OCR metrics
# to land before pushing (screenshot delay + OCR normally finish in a few
# seconds). Past it, we sync anyway rather than get stuck forever (e.g. if
# Tesseract isn't available on this machine).
METRICS_GRACE_SECONDS = 45.0


def _supabase_config(db: TrackerDb) -> tuple[str, str] | None:
    # .env wins if present; otherwise whatever was saved from the dashboard's
    # Parametres page (tracker/web.py writes the same two keys there), so
    # syncing works the same way the Global tab's read side already does --
    # no restart needed either way, this is re-read every sync pass.
    url = os.environ.get("SUPABASE_URL") or db.get_setting("supabase_url")
    # SUPABASE_KEY for anyone using the restricted anon key (friends syncing
    # into a shared project); SUPABASE_SERVICE_KEY kept for the project
    # owner's original .env so it doesn't need to change.
    key = (
        os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or db.get_setting("supabase_key")
    )
    if not url or not key:
        return None
    return url.rstrip("/"), key


def _post(url: str, key: str, table: str, rows: list[dict[str, Any]], on_conflict: str | None = None) -> bool:
    if not rows:
        return True

    endpoint = f"{url}/rest/v1/{table}"
    params = {"on_conflict": on_conflict} if on_conflict else {}
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    try:
        resp = requests.post(endpoint, params=params, headers=headers, json=rows, timeout=15)
        if resp.status_code >= 300:
            print(f"[Sync] {table} push failed: {resp.status_code} {resp.text[:300]}")
            return False
        return True
    except requests.RequestException as e:
        print(f"[Sync] {table} push errored: {e!r}")
        return False


def _run_payload(full: dict[str, Any]) -> dict[str, Any]:
    run = full["run"]
    return {
        "run_uuid": run["run_uuid"],
        "started_at": run["started_at"],
        "ended_at": run["ended_at"],
        "hero": run["hero"],
        "game_mode": run["game_mode"],
        "result": run["result"],
        "rank_delta": run["rank_delta"],
        "player_username": run["player_username"],
        "player_account_id": run["player_account_id"],
    }


def push_run(url: str, key: str, full: dict[str, Any]) -> bool:
    run_uuid = full["run"]["run_uuid"]

    if not _post(url, key, "runs", [_run_payload(full)], on_conflict="run_uuid"):
        return False

    items = [
        {
            "run_uuid": run_uuid,
            "instance_id": it["instance_id"],
            "template_id": it["template_id"],
            "socket_target": it["socket_target"],
            "purchased_at": it["purchased_at"],
            "sold_at": it["sold_at"],
            "sell_price": it["sell_price"],
        }
        for it in full["items"]
    ]
    if not _post(url, key, "run_items", items):
        return False

    combats = [
        {
            "run_uuid": run_uuid,
            "combat_type": c["combat_type"],
            "started_at": c["started_at"],
            "ended_at": c["ended_at"],
            "duration_ms": c["duration_ms"],
            "frames": c["frames"],
        }
        for c in full["combats"]
    ]
    if not _post(url, key, "run_combats", combats):
        return False

    rerolls = [{"run_uuid": run_uuid, "occurred_at": r["occurred_at"]} for r in full["rerolls"]]
    if not _post(url, key, "run_rerolls", rerolls):
        return False

    skills = [
        {"run_uuid": run_uuid, "skill_id": s["skill_id"], "socket": s["socket"], "selected_at": s["selected_at"]}
        for s in full["skills"]
    ]
    if not _post(url, key, "run_skills", skills):
        return False

    if full["metrics"] is not None:
        m = full["metrics"]
        metrics_payload = [{
            "run_uuid": run_uuid,
            "wins": m["wins"], "gold": m["gold"], "prestige": m["prestige"],
            "level": m["level"], "income": m["income"], "max_health": m["max_health"],
            "won": bool(m["won"]) if m["won"] is not None else None,
        }]
        if not _post(url, key, "run_metrics", metrics_payload, on_conflict="run_uuid"):
            return False

    return True


def sync_pending_runs(db: TrackerDb) -> None:
    config = _supabase_config(db)
    if config is None:
        return  # not configured yet -- runs pile up locally until it is

    url, key = config
    now = time.time()

    for run_row in db.pending_sync_runs():
        run_id = run_row["run_id"]
        full = db.get_full_run(run_id)

        has_metrics = full["metrics"] is not None
        ended_at = run_row["ended_at"] or 0
        if not has_metrics and (now - ended_at) < METRICS_GRACE_SECONDS:
            continue  # give OCR a bit more time before pushing

        if push_run(url, key, full):
            db.mark_synced(run_id, now)
            print(f"[Sync] run {run_id} ({full['run']['run_uuid']}) synced to Supabase")
