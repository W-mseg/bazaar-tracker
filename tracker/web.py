from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import datetime

import requests
from flask import Flask, abort, flash, redirect, render_template, request, send_from_directory, url_for

from .sync import ITEM_BUCKET


def _jwt_role(token: str) -> str | None:
    """
    Reads the "role" claim out of a Supabase JWT without verifying its
    signature -- only used to decide whether to show admin-only UI (delete
    buttons). Not a security boundary: Supabase itself verifies the
    signature server-side on every request, so a forged claim here would
    just show a button whose actual DELETE call still gets rejected.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("role")
    except Exception:
        return None


def _get_db(db_path: str) -> sqlite3.Connection:
    # Separate connection per request -- WAL mode (set in db.py) lets this
    # read happily while the tailer keeps writing from another thread.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row else None


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _short_guid(value: str | None) -> str:
    if not value:
        return "—"
    return value[:8]


def _day_hour(day: object, hour: object) -> str:
    # Guards against more than plain None: a missing column on an
    # unmigrated table resolves through Jinja as Undefined, not None.
    if not isinstance(day, int) or not isinstance(hour, int):
        return "—"
    return f"Jour {day} · Heure {hour}"


# The game only logs a generic EndRunVictoryState / EndRunDefeatState --
# never which milestone was reached -- and the milestone banked doesn't
# necessarily match victory/defeat anyway: a player can bank a 7-win reward
# mid-run and still ultimately die, which the game logs as EndRunDefeatState
# even though 7 wins were reached (confirmed against a real run: reward
# screen showed "7 VICTOIRES / VICTOIRE ARGENT", the log's own state still
# said defeat). So classification is purely wins-based, not tied to which
# EndRun*State fired: >=4 wins is a win at that tier regardless of how the
# run technically ended; under 4 is a defeat. Falls back to the raw log
# state only when OCR hasn't produced a wins count yet.
def _result_badge(result: str | None, wins: int | None) -> tuple[str, str]:
    if wins is not None:
        if wins >= 10:
            return "Victoire 10", "victory"
        if wins >= 7:
            return "Victoire 7", "victory"
        if wins >= 4:
            return "Victoire 4", "victory"
        return "Défaite", "defeat"
    if result == "victory":
        return "Victoire", "victory"
    if result == "defeat":
        return "Défaite", "defeat"
    return "En cours", "unknown"


def create_app(
    db_path: str,
    supabase_url: str | None = None,
    supabase_key: str | None = None,
    item_snapshot_dir: str | None = None,
) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.urandom(24)  # local-only, single-user -- just needs to exist for flash()
    app.jinja_env.filters["fmt_ts"] = _fmt_ts
    app.jinja_env.filters["fmt_duration"] = _fmt_duration
    app.jinja_env.filters["short_guid"] = _short_guid
    app.jinja_env.filters["result_badge"] = _result_badge
    app.jinja_env.filters["day_hour"] = _day_hour
    app.jinja_env.filters["basename"] = lambda p: os.path.basename(p) if p else ""

    @app.route("/")
    def index():
        conn = _get_db(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT r.*, m.wins, m.gold, m.prestige, m.level, m.income, m.max_health, m.won
                FROM runs r
                LEFT JOIN run_metrics m ON m.run_id = r.run_id
                ORDER BY r.started_at DESC
                """
            )
            runs = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM runs WHERE ended_at IS NOT NULL")
            finished = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM runs WHERE result = 'victory'")
            wins = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM runs WHERE result = 'defeat'")
            defeats = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(sell_price), 0) FROM run_items")
            gold_from_sales = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM runs WHERE synced_at IS NULL AND ended_at IS NOT NULL")
            pending_sync = cur.fetchone()[0]

            summary = {
                "finished": finished,
                "wins": wins,
                "defeats": defeats,
                "win_rate": round(100 * wins / finished, 1) if finished else None,
                "gold_from_sales": gold_from_sales,
                "pending_sync": pending_sync,
            }
        finally:
            conn.close()

        return render_template("index.html", runs=runs, summary=summary)

    @app.route("/runs/<int:run_id>")
    def run_detail(run_id: int):
        conn = _get_db(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT r.*, m.wins, m.gold, m.prestige, m.level, m.income, m.max_health, m.won
                FROM runs r LEFT JOIN run_metrics m ON m.run_id = r.run_id
                WHERE r.run_id = ?
                """,
                (run_id,),
            )
            run = cur.fetchone()
            if run is None:
                abort(404)

            cur.execute("SELECT * FROM run_items WHERE run_id = ? ORDER BY purchased_at", (run_id,))
            items = cur.fetchall()

            cur.execute("SELECT * FROM run_combats WHERE run_id = ? ORDER BY started_at", (run_id,))
            combats = cur.fetchall()

            cur.execute("SELECT * FROM run_rerolls WHERE run_id = ? ORDER BY occurred_at", (run_id,))
            rerolls = cur.fetchall()

            cur.execute("SELECT * FROM run_skills WHERE run_id = ? ORDER BY selected_at", (run_id,))
            skills = cur.fetchall()
        finally:
            conn.close()

        return render_template(
            "run_detail.html", run=run, items=items, combats=combats, rerolls=rerolls, skills=skills
        )

    def _effective_supabase_config() -> tuple[str | None, str | None]:
        # .env (passed in at process start) wins if present; otherwise fall
        # back to whatever was saved from the in-browser settings form. This
        # keeps the original .env-based setup working unchanged while giving
        # everyone else a way in that doesn't depend on file placement.
        if supabase_url and supabase_key:
            return supabase_url, supabase_key
        conn = _get_db(db_path)
        try:
            return _get_setting(conn, "supabase_url"), _get_setting(conn, "supabase_key")
        finally:
            conn.close()

    @app.route("/settings", methods=["GET", "POST"])
    def settings_view():
        conn = _get_db(db_path)
        try:
            if request.method == "POST":
                # Neither value can legitimately contain whitespace (it's a
                # URL and a JWT), but pasting a long key through a chat app
                # can silently insert a line break or stray space in the
                # middle of it -- strip all whitespace, not just the ends,
                # so that doesn't turn into a mystifying 401 from Supabase.
                url_val = "".join(request.form.get("supabase_url", "").split())
                key_val = "".join(request.form.get("supabase_key", "").split())
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('supabase_url', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (url_val,),
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('supabase_key', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key_val,),
                )
                conn.commit()
                return redirect(url_for("global_view"))

            saved_url = _get_setting(conn, "supabase_url") or ""
            saved_key = _get_setting(conn, "supabase_key") or ""
        finally:
            conn.close()

        return render_template(
            "settings.html",
            saved_url=saved_url,
            saved_key=saved_key,
            env_configured=bool(supabase_url and supabase_key),
        )

    @app.route("/global")
    def global_view():
        eff_url, eff_key = _effective_supabase_config()
        if not eff_url or not eff_key:
            return render_template("global.html", configured=False, error=None, runs=[], leaderboard=[])

        headers = {"apikey": eff_key, "Authorization": f"Bearer {eff_key}"}
        try:
            resp = requests.get(
                f"{eff_url}/rest/v1/runs",
                headers=headers,
                params={
                    "select": "*,run_metrics(wins,gold,prestige,level,income,max_health,won)",
                    "order": "started_at.desc",
                    "limit": "200",
                },
                timeout=15,
            )
            resp.raise_for_status()
            rows = resp.json()
        except requests.RequestException as e:
            return render_template("global.html", configured=True, error=str(e), runs=[], leaderboard=[])

        # PostgREST embeds a 1:1 related table (run_metrics.run_uuid is both
        # its PK and the FK to runs) as an object in recent versions, but as
        # a one-item list on older ones -- handle both.
        runs = []
        for r in rows:
            m = r.get("run_metrics") or {}
            if isinstance(m, list):
                m = m[0] if m else {}
            r["wins"] = m.get("wins")
            r["gold"] = m.get("gold")
            runs.append(r)

        by_player: dict[str, dict] = {}
        for r in runs:
            key = r.get("player_username") or "?"
            entry = by_player.setdefault(key, {"username": key, "runs": 0, "wins": 0, "defeats": 0})
            if r.get("ended_at"):
                entry["runs"] += 1
            if r.get("result") == "victory":
                entry["wins"] += 1
            elif r.get("result") == "defeat":
                entry["defeats"] += 1
        leaderboard = sorted(by_player.values(), key=lambda e: e["runs"], reverse=True)

        return render_template("global.html", configured=True, error=None, runs=runs, leaderboard=leaderboard)

    @app.route("/items")
    def items_view():
        conn = _get_db(db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM item_catalog ORDER BY captured_at DESC")
            local_rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        by_template: dict[str, dict] = {}
        for r in local_rows:
            by_template[r["template_id"]] = {
                "template_id": r["template_id"],
                "image_src": url_for("item_snapshot_file", filename=os.path.basename(r["screenshot_path"])),
                "socket_target": r["socket_target"],
                "day": r["day"],
                "hour": r["hour"],
                "contributed_by": r["contributed_by"],
                "mine": True,
            }

        eff_url, eff_key = _effective_supabase_config()
        shared_error = None
        if eff_url and eff_key:
            headers = {"apikey": eff_key, "Authorization": f"Bearer {eff_key}"}
            try:
                resp = requests.get(
                    f"{eff_url}/rest/v1/item_catalog",
                    headers=headers,
                    params={"select": "*", "order": "captured_at.desc", "limit": "1000"},
                    timeout=15,
                )
                resp.raise_for_status()
                for r in resp.json():
                    tid = r["template_id"]
                    if tid in by_template:
                        if not by_template[tid]["contributed_by"]:
                            by_template[tid]["contributed_by"] = r.get("contributed_by")
                    else:
                        by_template[tid] = {
                            "template_id": tid,
                            "image_src": r["image_url"],
                            "socket_target": r.get("socket_target"),
                            "day": None,
                            "hour": None,
                            "contributed_by": r.get("contributed_by"),
                            "mine": False,
                        }
            except requests.RequestException as e:
                shared_error = str(e)

        items = sorted(by_template.values(), key=lambda x: x["template_id"])
        return render_template(
            "items.html",
            items=items,
            shared_configured=bool(eff_url and eff_key),
            shared_error=shared_error,
            is_admin=bool(eff_key and _jwt_role(eff_key) == "service_role"),
        )

    @app.route("/item_snapshots/<path:filename>")
    def item_snapshot_file(filename: str):
        if not item_snapshot_dir:
            abort(404)
        return send_from_directory(item_snapshot_dir, filename)

    @app.route("/items/<template_id>/delete", methods=["POST"])
    def delete_item(template_id: str):
        """
        Admin-only (needs the service_role key configured in Parametres,
        which bypasses RLS): wipes one item out of the catalog -- table row,
        storage file, and local copy -- so it's treated as never-captured
        again and gets recaptured automatically the next time it's seen on
        a board. This is how a bad crop gets fixed, without anyone needing
        to touch SQL or the Supabase dashboard by hand.
        """
        eff_url, eff_key = _effective_supabase_config()
        if not eff_url or not eff_key or _jwt_role(eff_key) != "service_role":
            abort(403)

        headers = {"apikey": eff_key, "Authorization": f"Bearer {eff_key}"}
        remote_error = None
        try:
            requests.delete(
                f"{eff_url}/storage/v1/object/{ITEM_BUCKET}/{template_id}.png",
                headers=headers, timeout=15,
            )
            resp = requests.delete(
                f"{eff_url}/rest/v1/item_catalog",
                headers=headers, params={"template_id": f"eq.{template_id}"}, timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            remote_error = str(e)

        conn = _get_db(db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT screenshot_path FROM item_catalog WHERE template_id = ?", (template_id,))
            row = cur.fetchone()
            if row and row["screenshot_path"] and os.path.exists(row["screenshot_path"]):
                os.remove(row["screenshot_path"])
            conn.execute("DELETE FROM item_catalog WHERE template_id = ?", (template_id,))
            conn.commit()
        finally:
            conn.close()

        if remote_error:
            flash(f"Supprimé localement, mais le nettoyage Supabase a échoué : {remote_error}")
        else:
            flash("Item supprimé -- il sera recapturé automatiquement au prochain combat où il apparaît.")
        return redirect(url_for("items_view"))

    return app


def run_web(
    db_path: str,
    port: int = 8765,
    supabase_url: str | None = None,
    supabase_key: str | None = None,
    item_snapshot_dir: str | None = None,
) -> None:
    app = create_app(
        db_path, supabase_url=supabase_url, supabase_key=supabase_key, item_snapshot_dir=item_snapshot_dir
    )
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
