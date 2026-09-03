from __future__ import annotations

import os
import time
from typing import Optional

WINDOW_TITLE = "The Bazaar"


def _find_bazaar_client_rect() -> Optional[dict]:
    try:
        import win32gui
    except Exception:
        return None

    matches: list[int] = []

    def _enum_cb(hwnd, _extra) -> None:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd) or ""
            if WINDOW_TITLE.lower() in title.lower():
                matches.append(hwnd)
        except Exception:
            return

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception:
        return None

    if not matches:
        return None

    hwnd = matches[0]

    try:
        if win32gui.IsIconic(hwnd):
            return None

        client_rect = win32gui.GetClientRect(hwnd)
        left_top = win32gui.ClientToScreen(hwnd, (client_rect[0], client_rect[1]))
        right_bottom = win32gui.ClientToScreen(hwnd, (client_rect[2], client_rect[3]))

        left, top = left_top
        right, bottom = right_bottom
        width = right - left
        height = bottom - top

        if width < 200 or height < 200:
            return None

        return {"left": left, "top": top, "width": width, "height": height}
    except Exception:
        return None


def _fallback_monitor_rect(sct, monitor_index: int) -> dict:
    monitors = sct.monitors
    idx = monitor_index
    if idx < 1 or idx >= len(monitors):
        idx = 1
    return monitors[idx]


def _capture(out_dir: str, filename: str, monitor_index: int = 1) -> Optional[str]:
    """
    Captures the game's client area (falling back to a full monitor grab)
    and saves it as a PNG under the given filename. Returns the saved path,
    or None if screenshotting isn't available (mss/PIL missing, or no
    display -- e.g. during replay tests).
    """
    try:
        from mss import mss
        from PIL import Image
    except Exception as e:
        print(f"[Screenshot] mss/Pillow unavailable: {e!r}")
        return None

    os.makedirs(out_dir, exist_ok=True)

    with mss() as sct:
        region = _find_bazaar_client_rect() or _fallback_monitor_rect(sct, monitor_index)

        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.rgb)

        path = os.path.join(out_dir, filename)
        img.save(path)
        return path


def capture_final_board(out_dir: str, monitor_index: int = 1) -> Optional[str]:
    return _capture(out_dir, f"run_end_{int(time.time())}.png", monitor_index)


def capture_item_snapshot(out_dir: str, template_id: str, monitor_index: int = 1) -> Optional[str]:
    return _capture(out_dir, f"{template_id}_{int(time.time())}.png", monitor_index)
