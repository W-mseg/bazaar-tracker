from __future__ import annotations

import re
from typing import Optional

from .events import Event


class LogParser:
    """
    Parses The Bazaar's Player.log (client version 1.0.12222-prod-windows-x64
    at the time this was written) into typed Events.

    Every marker here was verified against a real, complete run log
    (hero Jules, Ranked, defeat) before being written down. See
    tests/sample_run.log and tests/test_parser_replay.py.
    """

    RUN_START_MARKER = "[StartRunAppState] Run initialization finalized."

    _GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

    _HERO_RE = re.compile(r"Changing EHero to (?P<hero>[A-Za-z][A-Za-z0-9 _'-]*)")
    _MODE_RE = re.compile(r"Changing EPlayMode to (?P<mode>[A-Za-z]+)")

    # "[ProfileCache] Username: TheWestred - AccountId: 84e5a001-...-fbec519- Tutorial Completed: True"
    # (note: no space between the GUID and the trailing "-", that's the game's own log formatting)
    _PROFILE_RE = re.compile(
        rf"Username:\s*(?P<username>[^-]+?)\s*-\s*AccountId:\s*(?P<account_id>{_GUID})",
    )

    _PURCHASE_RE = re.compile(
        rf"Card Purchased:\s*InstanceId:\s*(?P<iid>itm_[A-Za-z0-9_\-]+)\s*-\s*"
        rf"TemplateId(?P<tid>{_GUID})\s*-\s*Target:(?P<target>[A-Za-z]+_\d+)",
        re.IGNORECASE,
    )
    _SOLD_RE = re.compile(r"Sold Card (?P<iid>itm_[A-Za-z0-9_\-]+) for (?P<gold>\d+) gold\.")

    _SKILL_RE = re.compile(
        r"Selected skill (?P<skill>skl_[A-Za-z0-9_\-]+) to socket (?P<socket>SkillSocket_\d+)"
    )

    _STATE_CHANGE_RE = re.compile(r"State changed from \[.*?\] to \[(?P<state>[A-Za-z]+)\]")
    _COMBAT_PREPARED_RE = re.compile(r"Combat prepared: frames=(?P<frames>\d+)")
    _COMBAT_COMPLETED_RE = re.compile(r"Combat simulation completed: durationMs=(?P<ms>\d+)")

    _RANK_RE = re.compile(r"Changing rank points from (?P<rfrom>\d+) to (?P<rto>\d+)")

    _RUN_END_STATES = {
        "EndRunDefeatState": "defeat",
        "EndRunVictoryState": "victory",
    }
    _COMBAT_STATES = {
        "CombatState": "pve",
        "PVPCombatState": "pvp",
    }

    def __init__(self) -> None:
        # Mirrors the old parser's safety net: don't pick up hero mentions
        # mid-run, only around run start/end where RunConfigurationCache
        # actually reflects the player's chosen hero.
        self._allow_hero_detection = True

    def parse_line(self, line: str) -> Optional[Event]:
        raw = line

        if self.RUN_START_MARKER in line:
            self._allow_hero_detection = False
            return Event(type="RunStart", raw=raw)

        if self._allow_hero_detection:
            m = self._HERO_RE.search(line)
            if m:
                return Event(type="HeroDetected", raw=raw, hero=m.group("hero").strip())

        m = self._MODE_RE.search(line)
        if m:
            return Event(type="GameModeDetected", raw=raw, mode=m.group("mode").strip())

        m = self._PROFILE_RE.search(line)
        if m:
            return Event(
                type="ProfileDetected",
                raw=raw,
                player_username=m.group("username").strip(),
                player_account_id=m.group("account_id"),
            )

        m = self._PURCHASE_RE.search(line)
        if m:
            return Event(
                type="ItemPurchased",
                raw=raw,
                instance_id=m.group("iid"),
                template_id=m.group("tid"),
                socket_target=m.group("target"),
            )

        m = self._SOLD_RE.search(line)
        if m:
            return Event(
                type="ItemSold",
                raw=raw,
                instance_id=m.group("iid"),
                sell_price=int(m.group("gold")),
            )

        if "type=RerollCommand" in line and "result=success" in line:
            return Event(type="RerollUsed", raw=raw)

        m = self._SKILL_RE.search(line)
        if m:
            return Event(
                type="SkillSelected",
                raw=raw,
                skill_id=m.group("skill"),
                socket=m.group("socket"),
            )

        m = self._STATE_CHANGE_RE.search(line)
        if m:
            state = m.group("state")

            if state in self._COMBAT_STATES:
                return Event(type="CombatStarted", raw=raw, combat_type=self._COMBAT_STATES[state])

            if state in self._RUN_END_STATES:
                self._allow_hero_detection = True
                return Event(type="RunEnd", raw=raw, result=self._RUN_END_STATES[state])

            if state == "ChoiceState":
                # The shop/choice screen. Each entry into it is a new "hour"
                # (per the in-game Day/Hour structure) -- except the very
                # first one of a run, and the first one after a PVP fight,
                # both of which RunBuilder treats specially.
                return Event(type="ShopEntered", raw=raw)

            return None

        m = self._COMBAT_PREPARED_RE.search(line)
        if m:
            return Event(type="CombatPrepared", raw=raw, frames=int(m.group("frames")))

        m = self._COMBAT_COMPLETED_RE.search(line)
        if m:
            return Event(type="CombatEnded", raw=raw, duration_ms=int(m.group("ms")))

        m = self._RANK_RE.search(line)
        if m:
            return Event(
                type="RankChanged",
                raw=raw,
                rank_from=int(m.group("rfrom")),
                rank_to=int(m.group("rto")),
            )

        return None
