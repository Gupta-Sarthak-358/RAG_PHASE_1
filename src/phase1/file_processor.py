"""
Scan the chapters directory, extract chapter numbers from filenames,
and track which chapters have already been processed.
"""

import json
import os
import re

from phase1 import config
from io_utils import load_json, save_json

# ---------------------------------------------------------------------------
# Chapter-number extraction from filename
# ---------------------------------------------------------------------------
_PATTERNS = [
    re.compile(r"chapter[_\s\-]*(\d+)", re.IGNORECASE),
    re.compile(r"ch[_\s\-]*(\d+)", re.IGNORECASE),
    re.compile(r"^(\d+)"),
]


def _chapter_number(filename: str) -> int | None:
    stem = os.path.splitext(filename)[0]
    for pat in _PATTERNS:
        m = pat.search(stem)
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Processed-chapters bookkeeping
# ---------------------------------------------------------------------------

def _load_processed() -> set[int]:
    return set(load_json(config.PROCESSED_FILE, []))


def mark_processed(chapter_number: int) -> None:
    done = _load_processed()
    done.add(chapter_number)
    save_json(config.PROCESSED_FILE, sorted(done))


def unmark_chapters(chapters: list[int]) -> None:
    """Remove chapters from the processed list so they can be reprocessed."""
    done = _load_processed()
    for ch in chapters:
        done.discard(ch)
    save_json(config.PROCESSED_FILE, sorted(done))


# ---------------------------------------------------------------------------
# Public scanning helpers
# ---------------------------------------------------------------------------

def scan_new_chapters() -> list[tuple[int, str]]:
    """Return sorted list of (chapter_number, filepath) for unprocessed .txt files."""
    if not os.path.isdir(config.CHAPTERS_DIR):
        print(f"Chapter directory not found: {config.CHAPTERS_DIR}")
        return []

    done = _load_processed()
    found: list[tuple[int, str]] = []

    for fname in os.listdir(config.CHAPTERS_DIR):
        if not fname.lower().endswith(".txt"):
            continue
        num = _chapter_number(fname)
        if num is None:
            print(f"  ⚠ cannot parse chapter number: {fname}")
            continue
        if num in done:
            continue
        found.append((num, os.path.join(config.CHAPTERS_DIR, fname)))

    found.sort(key=lambda t: t[0])
    return found


def get_all_chapters() -> list[tuple[int, str]]:
    """Return (chapter_number, full_text) for every .txt in the chapters dir."""
    if not os.path.isdir(config.CHAPTERS_DIR):
        print(f"Chapter directory not found: {config.CHAPTERS_DIR}")
        return []

    chapters: list[tuple[int, str]] = []
    for fname in os.listdir(config.CHAPTERS_DIR):
        if not fname.lower().endswith(".txt"):
            continue
        num = _chapter_number(fname)
        if num is None:
            continue
        path = os.path.join(config.CHAPTERS_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            chapters.append((num, f.read()))

    chapters.sort(key=lambda t: t[0])
    return chapters


def get_processed_sorted() -> list[int]:
    """Return sorted list of all processed chapter numbers."""
    return sorted(_load_processed())


def read_chapter(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
