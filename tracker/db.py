from __future__ import annotations

import json
import os
import sqlite3
import uuid
from typing import Any, Optional


class TrackerDb:
    def __init__(self, path: str) -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        # WAL lets the local web viewer read concurrently while the tailer writes.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def _add_column_if_missing(self, table: str, column: str, sql_type: str) -> None:
        """Lets an already-existing local db (created before this column existed) catch up."""
        cur = self.conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        if column not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
            self.conn.commit()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_uuid TEXT UNIQUE NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL,
                hero TEXT,
                game_mode TEXT,
                result TEXT,
                rank_delta INTEGER NOT NULL DEFAULT 0,
                synced_at REAL,
                player_username TEXT,
                player_account_id TEXT
            )
            """
        )
        self._add_column_if_missing("runs", "player_username", "TEXT")
        self._add_column_if_missing("runs", "player_account_id", "TEXT")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS run_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                instance_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                socket_target TEXT,
                purchased_at REAL NOT NULL,
                sold_at REAL,
                sell_price INTEGER,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_run_items_run ON run_items(run_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_run_items_template ON run_items(template_id)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS run_combats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                combat_type TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL,
                duration_ms INTEGER,
                frames INTEGER,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_run_combats_run ON run_combats(run_id)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS run_rerolls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                occurred_at REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_run_rerolls_run ON run_rerolls(run_id)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS run_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                skill_id TEXT NOT NULL,
                socket TEXT,
                selected_at REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_run_skills_run ON run_skills(run_id)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS run_metrics (
                run_id INTEGER PRIMARY KEY,
                wins INTEGER,
                gold INTEGER,
                prestige INTEGER,
                level INTEGER,
                income INTEGER,
                max_health INTEGER,
                won INTEGER,
                ocr_json TEXT,
                updated_at REAL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        self.conn.commit()

    # -- settings --------------------------------------------------------------

    def get_setting(self, key: str) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # -- runs --------------------------------------------------------------

    def create_run(
        self,
        started_at: float,
        hero: Optional[str] = None,
        game_mode: Optional[str] = None,
        player_username: Optional[str] = None,
        player_account_id: Optional[str] = None,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO runs (run_uuid, started_at, hero, game_mode, player_username, player_account_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), started_at, hero, game_mode, player_username, player_account_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_hero(self, run_id: int, hero: str) -> None:
        self.conn.execute("UPDATE runs SET hero = ? WHERE run_id = ?", (hero, run_id))
        self.conn.commit()

    def set_player_identity(self, run_id: int, username: Optional[str], account_id: str) -> None:
        self.conn.execute(
            "UPDATE runs SET player_username = ?, player_account_id = ? WHERE run_id = ?",
            (username, account_id, run_id),
        )
        self.conn.commit()

    def set_game_mode(self, run_id: int, mode: str) -> None:
        self.conn.execute("UPDATE runs SET game_mode = ? WHERE run_id = ?", (mode, run_id))
        self.conn.commit()

    def add_rank_delta(self, run_id: int, delta: int) -> None:
        self.conn.execute(
            "UPDATE runs SET rank_delta = rank_delta + ? WHERE run_id = ?", (delta, run_id)
        )
        self.conn.commit()

    def finalize_run(self, run_id: int, ended_at: float, result: str) -> None:
        self.conn.execute(
            "UPDATE runs SET ended_at = ?, result = ? WHERE run_id = ?",
            (ended_at, result, run_id),
        )
        self.conn.commit()

    # -- items --------------------------------------------------------------

    def add_item_purchase(
        self, run_id: int, instance_id: str, template_id: str, socket_target: Optional[str], ts: float
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO run_items (run_id, instance_id, template_id, socket_target, purchased_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, instance_id, template_id, socket_target, ts),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_item_sale(self, run_id: int, instance_id: str, sell_price: int, ts: float) -> bool:
        """Marks the most recent un-sold purchase of this instance in this run as sold."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id FROM run_items
            WHERE run_id = ? AND instance_id = ? AND sold_at IS NULL
            ORDER BY purchased_at DESC
            LIMIT 1
            """,
            (run_id, instance_id),
        )
        row = cur.fetchone()
        if row is None:
            return False

        cur.execute(
            "UPDATE run_items SET sold_at = ?, sell_price = ? WHERE id = ?",
            (ts, sell_price, row["id"]),
        )
        self.conn.commit()
        return True

    # -- combats --------------------------------------------------------------

    def add_combat(
        self,
        run_id: int,
        combat_type: str,
        started_at: float,
        ended_at: Optional[float],
        duration_ms: Optional[int],
        frames: Optional[int],
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO run_combats (run_id, combat_type, started_at, ended_at, duration_ms, frames)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, combat_type, started_at, ended_at, duration_ms, frames),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    # -- rerolls / skills --------------------------------------------------------------

    def add_reroll(self, run_id: int, ts: float) -> None:
        self.conn.execute("INSERT INTO run_rerolls (run_id, occurred_at) VALUES (?, ?)", (run_id, ts))
        self.conn.commit()

    def add_skill(self, run_id: int, skill_id: str, socket: Optional[str], ts: float) -> None:
        self.conn.execute(
            "INSERT INTO run_skills (run_id, skill_id, socket, selected_at) VALUES (?, ?, ?, ?)",
            (run_id, skill_id, socket, ts),
        )
        self.conn.commit()

    # -- metrics (OCR) --------------------------------------------------------------

    def save_run_metrics(self, run_id: int, metrics: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO run_metrics (run_id, wins, gold, prestige, level, income, max_health, won, ocr_json, updated_at)
            VALUES (:run_id, :wins, :gold, :prestige, :level, :income, :max_health, :won, :ocr_json, :updated_at)
            ON CONFLICT(run_id) DO UPDATE SET
                wins=excluded.wins, gold=excluded.gold, prestige=excluded.prestige,
                level=excluded.level, income=excluded.income, max_health=excluded.max_health,
                won=excluded.won, ocr_json=excluded.ocr_json, updated_at=excluded.updated_at
            """,
            {
                "run_id": run_id,
                "wins": metrics.get("wins"),
                "gold": metrics.get("gold"),
                "prestige": metrics.get("prestige"),
                "level": metrics.get("level"),
                "income": metrics.get("income"),
                "max_health": metrics.get("max_health"),
                "won": int(bool(metrics.get("won"))) if metrics.get("won") is not None else None,
                "ocr_json": metrics.get("ocr_json"),
                "updated_at": metrics.get("updated_at_unix"),
            },
        )
        self.conn.commit()

    # -- sync --------------------------------------------------------------

    def find_open_run(self) -> Optional[sqlite3.Row]:
        """Most recent run with no ended_at -- used to resume after a restart
        mid-run instead of silently opening a second, hero-less duplicate."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM runs WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        )
        return cur.fetchone()

    def pending_sync_runs(self) -> list[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM runs WHERE ended_at IS NOT NULL AND synced_at IS NULL")
        return cur.fetchall()

    def mark_synced(self, run_id: int, ts: float) -> None:
        self.conn.execute("UPDATE runs SET synced_at = ? WHERE run_id = ?", (ts, run_id))
        self.conn.commit()

    def get_full_run(self, run_id: int) -> dict[str, Any]:
        cur = self.conn.cursor()

        cur.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        run = dict(cur.fetchone())

        cur.execute("SELECT * FROM run_items WHERE run_id = ?", (run_id,))
        items = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM run_combats WHERE run_id = ?", (run_id,))
        combats = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM run_rerolls WHERE run_id = ?", (run_id,))
        rerolls = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM run_skills WHERE run_id = ?", (run_id,))
        skills = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM run_metrics WHERE run_id = ?", (run_id,))
        metrics_row = cur.fetchone()
        metrics = dict(metrics_row) if metrics_row else None

        return {
            "run": run,
            "items": items,
            "combats": combats,
            "rerolls": rerolls,
            "skills": skills,
            "metrics": metrics,
        }
