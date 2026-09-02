from __future__ import annotations

import os
import time
from typing import Iterator


def follow_file_lines(
    path: str,
    poll_interval_seconds: float = 0.5,
    encoding: str = "utf-8",
    errors: str = "ignore",
    start_at_end: bool = True,
) -> Iterator[str]:
    """
    Incrementally follow a file and yield complete lines as they are appended.
    Handles the file not existing yet, truncation/rotation, and partial line writes.
    """
    last_pos = 0
    carry = ""
    initialized = False

    while True:
        try:
            if not os.path.exists(path):
                time.sleep(poll_interval_seconds)
                continue

            if not initialized:
                initialized = True
                if start_at_end:
                    last_pos = os.path.getsize(path)
                    carry = ""
                    time.sleep(poll_interval_seconds)
                    continue

            size = os.path.getsize(path)
            if size < last_pos:
                last_pos = 0
                carry = ""

            with open(path, "r", encoding=encoding, errors=errors) as f:
                f.seek(last_pos)
                chunk = f.read()
                last_pos = f.tell()

            if not chunk:
                time.sleep(poll_interval_seconds)
                continue

            carry += chunk
            lines = carry.splitlines(keepends=False)

            ends_with_newline = carry.endswith("\n") or carry.endswith("\r")
            if not ends_with_newline and lines:
                carry = lines.pop()
            else:
                carry = ""

            for line in lines:
                yield line

        except Exception:
            time.sleep(poll_interval_seconds)
            continue


def replay_file_lines(path: str, encoding: str = "utf-8", errors: str = "ignore") -> Iterator[str]:
    """Read a file once from start to end. Used for offline parser validation."""
    with open(path, "r", encoding=encoding, errors=errors) as f:
        for line in f:
            yield line.rstrip("\n").rstrip("\r")
