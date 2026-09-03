from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Bazaar Tracker"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_data_dir() -> Path:
    override = os.environ.get("BAZAAR_TRACKER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME

    return Path.home() / f".{APP_NAME.lower().replace(' ', '-')}"


def _default_log_path() -> str:
    override = os.environ.get("BAZAAR_PLAYER_LOG_PATH")
    if override:
        return override

    userprofile = os.environ.get("USERPROFILE")
    if not userprofile:
        return "Player.log"
    return os.path.join(userprofile, r"AppData\LocalLow\Tempo Storm\The Bazaar\Player.log")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: str
    screenshot_dir: str
    item_snapshot_dir: str
    log_path: str

    poll_interval_seconds: float = 0.5

    enable_screenshots: bool = True
    screenshot_delay_seconds: float = 3.0
    screenshot_cooldown_seconds: float = 10.0

    # Building a local (and shared, see sync.py) item image catalog: on
    # combat start -- the one moment the board is guaranteed on screen, not
    # covered by a shop/vendor/reward popup -- capture one full frame and
    # crop out every never-seen-before template_id sitting in an actual
    # inventory socket (PlayerSocket_N -- not PlayerStorageSocket_N/stash),
    # per the calibration in board_rois.py. 2s wasn't enough: a real capture
    # at that delay caught the player's items still showing their face-down
    # card back, mid reveal-animation -- 4.5s clears that reliably without
    # eating into the fight itself (see 2026-09-03 session captures).
    enable_item_snapshots: bool = True
    board_capture_delay_seconds: float = 4.5

    tesseract_cmd: str | None = None

    # How often (seconds) the background loop retries syncing finished runs to Supabase.
    sync_interval_seconds: float = 30.0

    # Local web viewer (reads the same SQLite file, no Supabase needed).
    enable_web: bool = True
    web_port: int = 8765


def build_settings() -> Settings:
    data_dir = _ensure_dir(_default_data_dir())
    screenshot_dir = _ensure_dir(data_dir / "screenshots")
    item_snapshot_dir = _ensure_dir(data_dir / "item_snapshots")

    return Settings(
        data_dir=data_dir,
        db_path=str(data_dir / "tracker.sqlite3"),
        screenshot_dir=str(screenshot_dir),
        item_snapshot_dir=str(item_snapshot_dir),
        log_path=_default_log_path(),
    )


settings = build_settings()
