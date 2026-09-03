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
        "final_day": run.get("current_day"),
        "final_hour": run.get("current_hour"),
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
            "purchased_day": it.get("purchased_day"),
            "purchased_hour": it.get("purchased_hour"),
            "sold_day": it.get("sold_day"),
            "sold_hour": it.get("sold_hour"),
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
            "day": c.get("day"),
            "hour": c.get("hour"),
        }
        for c in full["combats"]
    ]
    if not _post(url, key, "run_combats", combats):
        return False

    rerolls = [
        {"run_uuid": run_uuid, "occurred_at": r["occurred_at"], "day": r.get("day"), "hour": r.get("hour")}
        for r in full["rerolls"]
    ]
    if not _post(url, key, "run_rerolls", rerolls):
        return False

    skills = [
        {
            "run_uuid": run_uuid, "skill_id": s["skill_id"], "socket": s["socket"],
            "selected_at": s["selected_at"], "day": s.get("day"), "hour": s.get("hour"),
        }
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


ITEM_BUCKET = "item-snapshots"


def _post_insert_only(url: str, key: str, table: str, rows: list[dict[str, Any]]) -> tuple[bool, bool]:
    """
    Plain insert, no upsert -- unlike _post (which merges on conflict), this
    is for the shared item catalog where the rule is "first capture wins":
    a primary-key clash means someone else in the group already added this
    item, not something to overwrite. Returns (success, was_conflict).
    """
    if not rows:
        return True, False

    endpoint = f"{url}/rest/v1/{table}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    try:
        resp = requests.post(endpoint, headers=headers, json=rows, timeout=15)
        if resp.status_code == 409:
            return False, True
        if resp.status_code >= 300:
            print(f"[Sync] {table} insert failed: {resp.status_code} {resp.text[:300]}")
            return False, False
        return True, False
    except requests.RequestException as e:
        print(f"[Sync] {table} insert errored: {e!r}")
        return False, False


def _upload_item_image(url: str, key: str, storage_path: str, file_path: str) -> bool:
    endpoint = f"{url}/storage/v1/object/{ITEM_BUCKET}/{storage_path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "image/png",
        "x-upsert": "false",  # first capture wins -- never overwrite an existing image
    }
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        resp = requests.post(endpoint, headers=headers, data=data, timeout=30)
        if resp.status_code >= 300:
            print(f"[Sync] item image upload ({storage_path}) -> {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except (requests.RequestException, OSError) as e:
        print(f"[Sync] item image upload errored: {e!r}")
        return False


def _item_public_url(url: str, storage_path: str) -> str:
    return f"{url}/storage/v1/object/public/{ITEM_BUCKET}/{storage_path}"


def _get_remote_item(url: str, key: str, template_id: str) -> dict[str, Any] | None:
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    try:
        resp = requests.get(
            f"{url}/rest/v1/item_catalog",
            headers=headers,
            params={"template_id": f"eq.{template_id}", "select": "template_id,image_url"},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None
    except requests.RequestException as e:
        print(f"[Sync] item_catalog lookup errored: {e!r}")
        return None


def sync_pending_items(db: TrackerDb) -> None:
    """
    Pushes locally-captured item screenshots into the shared community
    catalog: check first whether someone else in the group already found
    this template_id (skip uploading if so, just adopt their image), else
    upload the image to Storage and add the row. First capture wins -- an
    upload/insert conflict means someone beat us to it, not an overwrite.
    """
    config = _supabase_config(db)
    if config is None:
        return

    url, key = config
    now = time.time()

    for row in db.pending_sync_items():
        template_id = row["template_id"]

        existing = _get_remote_item(url, key, template_id)
        if existing is not None:
            db.mark_item_synced(template_id, existing["image_url"], now)
            print(f"[Sync] item {template_id} already in shared catalog, adopted")
            continue

        storage_path = f"{template_id}.png"
        if not _upload_item_image(url, key, storage_path, row["screenshot_path"]):
            existing = _get_remote_item(url, key, template_id)
            if existing is not None:
                db.mark_item_synced(template_id, existing["image_url"], now)
            continue  # otherwise retry next pass

        image_url = _item_public_url(url, storage_path)
        payload = [{
            "template_id": template_id,
            "storage_path": storage_path,
            "image_url": image_url,
            "socket_target": row["socket_target"],
            "contributed_by": row["contributed_by"],
            "captured_at": row["captured_at"],
        }]
        ok, conflict = _post_insert_only(url, key, "item_catalog", payload)
        if ok:
            db.mark_item_synced(template_id, image_url, now)
            print(f"[Sync] item {template_id} added to shared catalog")
        elif conflict:
            existing = _get_remote_item(url, key, template_id)
            if existing is not None:
                db.mark_item_synced(template_id, existing["image_url"], now)


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
