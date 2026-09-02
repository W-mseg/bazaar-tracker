from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Event:
    type: str
    raw: str

    observed_at: Optional[float] = None  # set by the caller (tailer loop), wall-clock time.time()

    # HeroDetected / GameModeDetected
    hero: Optional[str] = None
    mode: Optional[str] = None

    # ProfileDetected
    player_username: Optional[str] = None
    player_account_id: Optional[str] = None

    # ItemPurchased / ItemSold
    instance_id: Optional[str] = None
    template_id: Optional[str] = None
    socket_target: Optional[str] = None
    sell_price: Optional[int] = None

    # SkillSelected
    skill_id: Optional[str] = None
    socket: Optional[str] = None

    # CombatStarted / CombatPrepared / CombatEnded
    combat_type: Optional[str] = None  # "pve" | "pvp"
    frames: Optional[int] = None
    duration_ms: Optional[int] = None

    # RankChanged
    rank_from: Optional[int] = None
    rank_to: Optional[int] = None

    # RunEnd
    result: Optional[str] = None  # "victory" | "defeat"
