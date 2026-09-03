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


def capture_board_snapshot(out_dir: str, monitor_index: int = 1) -> Optional[str]:
    """
    One full-frame capture taken at combat start, when the board is
    guaranteed visible (see board_rois.py). Prefixed with an underscore so
    it reads clearly as a transient working file -- item_crop callers
    delete it once every pending item has been cropped out of it.
    """
    return _capture(out_dir, f"_board_{int(time.time() * 1000)}.png", monitor_index)


def _find_matching_board_resolution(width: int, height: int, tolerance: int = 10) -> Optional[str]:
    from .board_rois import BOARD_ROIS

    exact_key = f"{width}x{height}"
    if exact_key in BOARD_ROIS:
        return exact_key

    for key in BOARD_ROIS:
        try:
            rw, rh = map(int, key.split("x"))
        except ValueError:
            continue
        if abs(rw - width) <= tolerance and abs(rh - height) <= tolerance:
            return key

    return None


def crop_item_icon(
    board_image_path: str,
    socket_index: int,
    occupied_socket_indices: list[int],
    out_path: str,
) -> Optional[str]:
    """
    Crops one item's icon out of a full board screenshot.

    socket_index is where the item starts (PlayerSocket_N). The log never
    reports an item's size (small/medium/large -- 1/2/3 sockets wide), so
    the crop width is inferred from occupied_socket_indices: the gap to the
    next occupied socket, capped at 3 (the game's largest item size) so a
    stale gap left by a sold item doesn't balloon the crop.

    Returns None if there's no board calibration for this resolution yet
    (see board_rois.py) -- the caller should just skip the item in that case
    rather than fail the whole capture.
    """
    from PIL import Image

    from .board_rois import BOARD_ROIS

    im = Image.open(board_image_path)
    w, h = im.size
    key = _find_matching_board_resolution(w, h)
    if key is None:
        return None

    roi = BOARD_ROIS[key]
    if not (0 <= socket_index < roi["socket_count"]):
        return None

    # If there's no occupied socket further right, there's nothing to bound
    # the width against -- default to 1 rather than assuming a large item,
    # since most items are small and an over-wide crop on a trailing item
    # bleeds into empty board past it (or into unrelated interface chrome).
    higher = sorted(i for i in occupied_socket_indices if i > socket_index)
    span = (higher[0] - socket_index) if higher else 1
    span = max(1, min(span, 3))

    x1 = roi["row_left"] + socket_index * roi["cell_width"]
    x2 = min(x1 + span * roi["cell_width"], w)
    y1, y2 = roi["row_top"], roi["row_bottom"]

    crop = im.crop((x1, y1, x2, y2))
    crop.save(out_path)
    return out_path
