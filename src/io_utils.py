"""
Shared I/O utilities for the Canon Engine.

All JSON persistence across Phase 1 and Phase 2 goes through here.
save_json() uses an atomic write pattern (tmp → fsync → os.replace)
so a process crash cannot produce an empty or half-written output file.

Usage:
    from io_utils import load_json, save_json
    data = load_json("output/story_state.json", default={})
    save_json("output/story_state.json", data)
"""
from __future__ import annotations

import json
import os


def load_json(path: str, default=None):
    """
    Load JSON from *path*. Returns *default* (or {}) if the file does not exist.
    Raises json.JSONDecodeError on malformed files (do not swallow silently).
    """
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: str, data) -> None:
    """
    Atomically write *data* to *path* as pretty-printed JSON.

    Strategy:
        1. Write to <path>.tmp
        2. fsync to flush OS buffers
        3. os.replace() — atomic rename on POSIX, closes then replaces on Windows
    """
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
