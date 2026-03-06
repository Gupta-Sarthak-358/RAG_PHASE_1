#!/usr/bin/env python3
"""
run.py — Interactive menu for the Story Canon Engine.

Eliminates the need to memorize CLI commands by providing a guided
prompt-driven interface for both Phase 1 and Phase 2 operations.

Usage:
    python run.py
"""

from __future__ import annotations

import os
import sys
import subprocess
import textwrap

# ── Ensure src/ is on the path so modules are importable ────────────────────
SRC_DIR = os.path.join(os.path.dirname(__file__), "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


# ─────────────────────────────────────────────────────────────────────────────
# Colours (ANSI — gracefully disabled if terminal doesn't support them)
# ─────────────────────────────────────────────────────────────────────────────

def _supports_color() -> bool:
    try:
        import sys
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    except Exception:
        return False

USE_COLOR = _supports_color()

def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def header(text: str) -> str:
    return c(text, "1;36")       # bold cyan

def success(text: str) -> str:
    return c(text, "1;32")       # bold green

def warn(text: str) -> str:
    return c(text, "1;33")       # bold yellow

def error(text: str) -> str:
    return c(text, "1;31")       # bold red

def dim(text: str) -> str:
    return c(text, "2")          # dim


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def clear():
    os.system("cls" if os.name == "nt" else "clear")


def _run(module: str, *args: str) -> int:
    """Run a src/ module with the given args and return exit code."""
    cmd = [sys.executable, os.path.join(SRC_DIR, module)] + list(args)
    result = subprocess.run(cmd)
    return result.returncode


def _prompt(label: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    raw = input(f"  {label}{hint}: ").strip()
    return raw if raw else default


def _prompt_chapter(label: str = "Chapter number") -> str | None:
    raw = _prompt(label)
    if not raw.isdigit():
        print(error(f"  ✗ '{raw}' is not a valid chapter number."))
        return None
    return raw


def _pause():
    input(dim("\n  Press Enter to return to the menu..."))


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 actions
# ─────────────────────────────────────────────────────────────────────────────

def action_extract():
    print(header("\n  ── Phase 1: Extract Canon ──\n"))
    print("  This will process all new chapter files in chapters/\n")
    _run("main.py", "extract")
    _pause()


def action_reprocess():
    print(header("\n  ── Phase 1: Reprocess Chapters ──\n"))
    n = _prompt("How many recent chapters to reprocess", "5")
    if not n.isdigit():
        print(error("  ✗ Invalid number."))
        _pause()
        return
    _run("main.py", "reprocess", n)
    _pause()


def action_build_index():
    print(header("\n  ── Phase 1: Build FAISS Index ──\n"))
    _run("main.py", "build_index")
    _pause()


def action_summary():
    print(header("\n  ── Phase 1: Generate Canon Bible Summary ──\n"))
    _run("main.py", "summary")
    _pause()


def action_query():
    print(header("\n  ── Phase 1: Semantic Query ──\n"))
    q = _prompt("Enter your query")
    if not q:
        print(error("  ✗ Query cannot be empty."))
        _pause()
        return
    _run("main.py", "query", q)
    _pause()


def action_recap():
    print(header("\n  ── Phase 1: Story Recap ──\n"))
    n = _prompt("Number of recent chapters to include", "10")
    _run("main.py", "recap", n)
    _pause()


def action_snapshot():
    print(header("\n  ── Phase 1: World State Snapshot ──\n"))
    _run("main.py", "snapshot")
    _pause()


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 actions
# ─────────────────────────────────────────────────────────────────────────────

def action_init():
    print(header("\n  ── Phase 2: Initialise Narrative State ──\n"))
    print("  This reads Phase 1's story_state.json and builds:")
    print("    · thread_health_state.json")
    print("    · tension_state.json")
    print("    · emotional_state.json\n")
    confirm = _prompt("Initialise now? (y/N)", "n")
    if confirm.lower() != "y":
        print(dim("  Cancelled."))
        _pause()
        return
    _run("phase2_main.py", "init")
    _pause()


def action_outline():
    print(header("\n  ── Phase 2: Generate Chapter Outline ──\n"))
    ch = _prompt_chapter()
    if ch is None:
        _pause()
        return
    print()
    print("  Describe what should happen in this chapter.")
    print("  Example: 'Akane discovers the sealed gate and confronts the Elder'")
    direction = _prompt("Chapter direction")
    if not direction:
        print(error("  ✗ Direction cannot be empty."))
        _pause()
        return
    _run("phase2_main.py", "outline", ch, direction)
    print(success(f"\n  ✓ Outline saved to output/outlines/chapter_{int(ch):03d}_outline.json"))
    print(dim("  Edit the JSON if needed, then approve it."))
    _pause()


def action_approve():
    print(header("\n  ── Phase 2: Approve Outline ──\n"))
    ch = _prompt_chapter()
    if ch is None:
        _pause()
        return
    _run("phase2_main.py", "approve", ch)
    _pause()


def action_expand():
    print(header("\n  ── Phase 2: Expand Outline to Draft ──\n"))
    ch = _prompt_chapter()
    if ch is None:
        _pause()
        return
    print(f"\n  Expanding chapter {ch} scene-by-scene. This may take a few minutes...\n")
    _run("phase2_main.py", "expand", ch)
    print(success(f"\n  ✓ Draft saved to output/drafts/chapter_{int(ch):03d}_draft.txt"))
    _pause()


def action_validate():
    print(header("\n  ── Phase 2: Validate Chapter ──\n"))
    ch = _prompt_chapter()
    if ch is None:
        _pause()
        return
    _run("phase2_main.py", "validate", ch)
    _pause()


def action_update():
    print(header("\n  ── Phase 2: Update Narrative State ──\n"))
    print("  Run this AFTER Phase 1 has extracted the chapter.")
    print("  It updates threads, tension, and emotional state.\n")
    ch = _prompt_chapter()
    if ch is None:
        _pause()
        return
    _run("phase2_main.py", "update", ch)
    _pause()


def action_dashboard():
    print(header("\n  ── Phase 2: Narrative Dashboard ──\n"))
    _run("phase2_main.py", "dashboard")
    _pause()


def action_metrics():
    print(header("\n  ── Phase 2: Narrative Metrics ──\n"))
    _run("phase2_main.py", "metrics")
    _pause()


def action_forecast():
    print(header("\n  ── Phase 2: 3-Chapter Forecast ──\n"))
    _run("phase2_main.py", "forecast")
    _pause()


def action_inspect():
    print(header("\n  ── Phase 2: Inspect State File ──\n"))
    print("  Choose a state file to inspect:")
    options = ["threads", "tension", "emotional", "story", "conflicts"]
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    choice = _prompt("Enter number or name")
    if choice.isdigit() and 1 <= int(choice) <= len(options):
        target = options[int(choice) - 1]
    elif choice in options:
        target = choice
    else:
        print(error("  ✗ Invalid choice."))
        _pause()
        return
    _run("phase2_main.py", "inspect", target)
    _pause()


def action_set_tension():
    print(header("\n  ── Phase 2: Override Tension ──\n"))
    val = _prompt("New tension value (0.0 – 1.0)")
    try:
        float(val)
    except ValueError:
        print(error("  ✗ Must be a decimal number."))
        _pause()
        return
    _run("phase2_main.py", "set_tension", val)
    _pause()


def action_set_importance():
    print(header("\n  ── Phase 2: Override Thread Importance ──\n"))
    thread = _prompt("Thread name (partial match supported)")
    importance = _prompt("New importance (1–5)")
    if not importance.isdigit() or int(importance) not in range(1, 6):
        print(error("  ✗ Importance must be 1–5."))
        _pause()
        return
    _run("phase2_main.py", "set_importance", thread, importance)
    _pause()


# ─────────────────────────────────────────────────────────────────────────────
# Menu definitions
# ─────────────────────────────────────────────────────────────────────────────

MAIN_MENU = [
    ("Phase 1 — Canon Management",   None),
    ("Extract new chapters",          action_extract),
    ("Reprocess recent chapters",     action_reprocess),
    ("Build FAISS semantic index",    action_build_index),
    ("Generate Canon Bible summary",  action_summary),
    ("Semantic query",                action_query),
    ("Story recap",                   action_recap),
    ("World state snapshot",          action_snapshot),
    ("",                              None),
    ("Phase 2 — Narrative Co-Writer", None),
    ("Initialise Phase 2 state",      action_init),
    ("Generate chapter outline",      action_outline),
    ("Approve outline",               action_approve),
    ("Expand outline to draft",       action_expand),
    ("Validate chapter draft",        action_validate),
    ("Update narrative state",        action_update),
    ("",                              None),
    ("Phase 2 — Analytics",          None),
    ("Narrative dashboard",           action_dashboard),
    ("Full metrics panel",            action_metrics),
    ("3-chapter forecast",            action_forecast),
    ("Inspect state file",            action_inspect),
    ("Override tension",              action_set_tension),
    ("Override thread importance",    action_set_importance),
    ("",                              None),
    ("Exit",                          None),
]


def _build_numbered(items):
    """Build a numbered list, skipping section headers and blank entries."""
    numbered = []
    for label, action in items:
        if label == "" or action is None:
            numbered.append((label, None, None))
        else:
            numbered.append((label, action, len([x for x in numbered if x[2] is not None]) + 1))
    return numbered


def show_menu(numbered):
    width = 60
    print("\n" + "═" * width)
    print(header("  STORY CANON ENGINE").center(width + 11))
    print("═" * width)
    for label, action, num in numbered:
        if label == "":
            print()
        elif action is None:
            print(c(f"  ── {label}", "1;35"))   # bold magenta section header
        else:
            pad = f"{num:2}."
            print(f"  {dim(pad)} {label}")
    print("\n" + "═" * width)


def run():
    numbered = _build_numbered(MAIN_MENU)
    max_choice = max(n for _, _, n in numbered if n is not None)

    while True:
        clear()
        show_menu(numbered)

        raw = input(warn("\n  Choose an option: ")).strip()

        if raw == "" or raw.lower() in ("q", "quit", "exit"):
            print(success("\n  Goodbye!\n"))
            sys.exit(0)

        if not raw.isdigit():
            continue

        choice = int(raw)
        if not 1 <= choice <= max_choice:
            continue

        # find the action for this number
        for _, action, num in numbered:
            if num == choice:
                if action is None:
                    break
                clear()
                try:
                    action()
                except KeyboardInterrupt:
                    print(dim("\n\n  Interrupted."))
                    _pause()
                break


if __name__ == "__main__":
    run()
