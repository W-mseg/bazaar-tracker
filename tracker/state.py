from __future__ import annotations

import time
from typing import Optional

from .db import TrackerDb
from .events import Event

_GAMEPLAY_EVENT_TYPES = {
    "ItemPurchased",
    "ItemSold",
    "RerollUsed",
    "SkillSelected",
    "CombatStarted",
}


class RunBuilder:
    """
    Turns the flat Event stream from LogParser into rows in the local
    TrackerDb. One instance tracks exactly one "current run" at a time,
    plus a short grace window after RunEnd for events that land a line or
    two late (RankChanged shows up after the EndRunDefeatState transition).
    """

    def __init__(self, db: TrackerDb) -> None:
        self.db = db
        self._run_id: Optional[int] = None
        self._last_ended_run_id: Optional[int] = None
        self._pending_combat: Optional[dict] = None

        # HeroDetected/GameModeDetected land *before* RunStart (during hero
        # select / loadout screens) and *after* RunEnd (post-run profile
        # refresh). Neither should open a run by itself -- only RunStart
        # does that, using whatever was cached here in the meantime.
        self._pending_hero: Optional[str] = None
        self._pending_mode: Optional[str] = None

        # Who's playing. Set once per login and stable across runs/sessions
        # (same Steam account), so it's never cleared on RunEnd like hero/mode.
        self._pending_username: Optional[str] = None
        self._pending_account_id: Optional[str] = None

        # In-game Day/Hour, tracked from AppState transitions rather than
        # wall-clock time (that's what actually matters to a player looking
        # back at "what did my board look like"). An Hour ends when a choice
        # is made that leads back to the shop screen; a Day ends with a PVP
        # fight, after which the next ChoiceState starts a new Day at Hour 1.
        self._day = 1
        self._hour = 1
        self._day_ending_pending = False
        self._pending_first_choice = True  # the run's very first ChoiceState doesn't advance the hour

        # If the process restarts mid-run (crash, update, sleep/wake), the
        # tailer resumes from wherever the log currently is and never sees
        # that run's original RunStart line again. Without this, the next
        # gameplay event would silently open a second, hero-less duplicate
        # run instead of continuing the real one -- reattach to it instead.
        open_run = db.find_open_run()
        if open_run is not None:
            self._run_id = open_run["run_id"]
            self._pending_hero = open_run["hero"]
            self._pending_mode = open_run["game_mode"]
            self._pending_username = open_run["player_username"]
            self._pending_account_id = open_run["player_account_id"]
            self._day = open_run["current_day"]
            self._hour = open_run["current_hour"]
            self._pending_first_choice = False

    def handle(self, ev: Event) -> None:
        ts = ev.observed_at if ev.observed_at is not None else time.time()

        if ev.type == "RunStart":
            self._run_id = self.db.create_run(
                started_at=ts,
                hero=self._pending_hero,
                game_mode=self._pending_mode,
                player_username=self._pending_username,
                player_account_id=self._pending_account_id,
            )
            self._pending_combat = None
            self._day = 1
            self._hour = 1
            self._day_ending_pending = False
            self._pending_first_choice = True
            return

        if ev.type == "HeroDetected" and ev.hero:
            self._pending_hero = ev.hero
            if self._run_id is not None:
                self.db.set_hero(self._run_id, ev.hero)
            return

        if ev.type == "GameModeDetected" and ev.mode:
            self._pending_mode = ev.mode
            if self._run_id is not None:
                self.db.set_game_mode(self._run_id, ev.mode)
            return

        if ev.type == "ProfileDetected" and ev.player_account_id:
            self._pending_username = ev.player_username
            self._pending_account_id = ev.player_account_id
            if self._run_id is not None:
                self.db.set_player_identity(self._run_id, ev.player_username, ev.player_account_id)
            return

        # Tracker started mid-run: open one implicitly so we don't drop data.
        if self._run_id is None and ev.type in _GAMEPLAY_EVENT_TYPES:
            self._run_id = self.db.create_run(started_at=ts)

        if ev.type == "ItemPurchased":
            if self._run_id is not None:
                self.db.add_item_purchase(
                    self._run_id, ev.instance_id, ev.template_id, ev.socket_target, ts,
                    day=self._day, hour=self._hour,
                )
            return

        if ev.type == "ItemSold":
            if self._run_id is not None:
                self.db.add_item_sale(
                    self._run_id, ev.instance_id, ev.sell_price or 0, ts,
                    day=self._day, hour=self._hour,
                )
            return

        if ev.type == "RerollUsed":
            if self._run_id is not None:
                self.db.add_reroll(self._run_id, ts, day=self._day, hour=self._hour)
            return

        if ev.type == "SkillSelected":
            if self._run_id is not None:
                self.db.add_skill(
                    self._run_id, ev.skill_id, ev.socket, ts, day=self._day, hour=self._hour
                )
            return

        if ev.type == "ShopEntered":
            if self._pending_first_choice:
                self._pending_first_choice = False
            elif self._day_ending_pending:
                self._day += 1
                self._hour = 1
                self._day_ending_pending = False
            else:
                self._hour += 1
            if self._run_id is not None:
                self.db.set_day_hour(self._run_id, self._day, self._hour)
            return

        if ev.type == "CombatStarted":
            self._pending_combat = {
                "combat_type": ev.combat_type,
                "started_at": ts,
                "frames": None,
                "day": self._day,
                "hour": self._hour,
            }
            if ev.combat_type == "pvp":
                self._day_ending_pending = True
            return

        if ev.type == "CombatPrepared":
            if self._pending_combat is not None:
                self._pending_combat["frames"] = ev.frames
            return

        if ev.type == "CombatEnded":
            if self._pending_combat is not None and self._run_id is not None:
                self.db.add_combat(
                    self._run_id,
                    self._pending_combat["combat_type"],
                    self._pending_combat["started_at"],
                    ts,
                    ev.duration_ms,
                    self._pending_combat.get("frames"),
                    day=self._pending_combat.get("day"),
                    hour=self._pending_combat.get("hour"),
                )
            self._pending_combat = None
            return

        if ev.type == "RankChanged":
            # This can arrive a line or two after RunEnd, so it targets
            # whichever run most recently closed if none is active.
            target = self._run_id if self._run_id is not None else self._last_ended_run_id
            if target is not None and ev.rank_to is not None and ev.rank_from is not None:
                self.db.add_rank_delta(target, ev.rank_to - ev.rank_from)
            return

        if ev.type == "RunEnd":
            if self._run_id is not None:
                self.db.finalize_run(self._run_id, ts, ev.result or "unknown")
                self._last_ended_run_id = self._run_id
            self._run_id = None
            self._pending_combat = None
            return
