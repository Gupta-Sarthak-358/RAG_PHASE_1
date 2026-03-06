#!/usr/bin/env python3
"""
Phase 2 CLI entry point.

Commands
--------
  python phase2_main.py init                         Initialise Phase 2 state
  python phase2_main.py outline <ch> "<direction>"   Generate outline (Pass 1)
  python phase2_main.py approve <ch>                 Mark outline as approved
  python phase2_main.py expand  <ch>                 Expand outline to draft (Pass 2)
  python phase2_main.py validate <ch>                Validate chapter vs outline
  python phase2_main.py update  <ch>                 Update P2 state after canonisation
  python phase2_main.py metrics                      Show narrative telemetry
  python phase2_main.py forecast                     Show 3-chapter projection
  python phase2_main.py dashboard                    One-glance story state panel

Debugging:
  python phase2_main.py inspect <threads|tension|emotional|story|conflicts>
  python phase2_main.py set_tension <0.0-1.0>
  python phase2_main.py set_importance "<thread>" <1-5>
  python phase2_main.py set_emotion "<character>" <dimension> <0.0-1.0>
"""

from __future__ import annotations

import json
import os
import sys
import time

from phase1 import config
from io_utils import load_json


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _require_int(arg: str, name: str) -> int:
    try:
        return int(arg)
    except ValueError:
        print(f"Error: {name} must be an integer, got '{arg}'")
        sys.exit(1)


def _require_float(arg: str, name: str) -> float:
    try:
        return float(arg)
    except ValueError:
        print(f"Error: {name} must be a number, got '{arg}'")
        sys.exit(1)


def _check_p2_state() -> bool:
    """Warn if Phase 2 state hasn't been initialised."""
    from phase2 import config as p2
    needed = [p2.THREAD_HEALTH_FILE, p2.TENSION_STATE_FILE, p2.EMOTIONAL_STATE_FILE]
    missing = [f for f in needed if not os.path.exists(f)]
    if missing:
        print("  ⚠ Phase 2 state files missing.  Run 'init' first:")
        for f in missing:
            print(f"    {f}")
        print()
        return False
    return True


def _load_story_state() -> dict:
    return load_json(config.STORY_STATE_FILE, {})


# ── Audit Fix #1: Phase 1 gate ────────────────────────────────────
def _require_phase1_done(chapter: int) -> None:
    """Raise RuntimeError if Phase 1 has not canonised this chapter yet."""
    story_state = _load_story_state()
    processed = story_state.get("metadata", {}).get("chapters_processed", [])
    if chapter not in processed:
        raise RuntimeError(
            f"Phase 1 extraction not completed for chapter {chapter}. "
            f"Run:  python main.py extract  before updating Phase 2 state."
        )


# ──────────────────────────────────────────────────────────────────
# init
# ──────────────────────────────────────────────────────────────────

def cmd_init():
    """Initialise Phase 2 state from existing Phase 1 data."""
    from phase2.state.thread_health import ThreadHealthTracker
    from phase2.state.tension_model import TensionTracker
    from phase2.state.emotional_state import EmotionalState

    if not os.path.exists(config.STORY_STATE_FILE):
        print("No story_state.json found. Run Phase 1 'extract' first.")
        return

    story_state = _load_story_state()

    # Thread health
    tracker = ThreadHealthTracker()
    added = tracker.init_from_story_state(story_state)
    print(f"[init] Thread health: {added} threads imported, "
          f"{len(tracker.threads)} total")

    # Tension
    tension = TensionTracker()
    initial = tension.estimate_initial_tension(story_state)
    tension.init(initial)
    print(f"[init] Tension initialised at {initial:.2f}")

    # Emotional state
    emo = EmotionalState()
    added_e = emo.init_from_story_state(story_state)
    print(f"[init] Emotional state: {added_e} characters initialised, "
          f"{len(emo.characters)} total")

    print("[init] Done.  Review state files in output/ and adjust if needed.")


# ──────────────────────────────────────────────────────────────────
# outline
# ──────────────────────────────────────────────────────────────────

def cmd_outline(chapter: int, direction: str):
    from phase2.planning.outline_planner import generate_outline
    from phase2.analysis.narrative_metrics import display
    from phase2.analysis.forecasting import forecast as run_forecast

    print(f"\n━━━ Generating Outline: Chapter {chapter} ━━━")
    print(f"  Direction: \"{direction}\"\n")

    t0 = time.time()
    outline = generate_outline(chapter, direction)
    dt = time.time() - t0

    if outline is None:
        print("  FAILED — no outline produced.")
        return

    # ── Audit Fix #3: scene count schema validation ───────────────
    scene_count = outline.get("scene_count", 0)
    actual_scenes = len(outline.get("scenes", []))
    if actual_scenes != scene_count:
        outline.setdefault("risk_flags", []).append(
            f"scene_count mismatch: declared {scene_count}, got {actual_scenes}")

    # ── Audit Fix #3b: scene_number gap check ─────────────────────
    scene_numbers = [s.get("scene_number", 0) for s in outline.get("scenes", [])]
    if scene_numbers != list(range(1, len(scene_numbers) + 1)):
        outline.setdefault("risk_flags", []).append(
            f"scene_number gap detected: {scene_numbers}")

    print(f"\n  Generated in {dt:.1f}s")
    print(f"  Scenes: {actual_scenes}")
    print(f"  Closing tension: {outline.get('closing_tension', '?')}")
    print(f"  Threads advanced: {outline.get('threads_advanced', [])}")
    flags = outline.get("risk_flags", [])
    if flags:
        print(f"  ⚠ Risk flags ({len(flags)}):")
        for flag in flags:
            print(f"    - {flag}")
    else:
        print(f"  Status: {outline.get('status', '?')}")

    for scene in outline.get("scenes", []):
        sn = scene.get("scene_number", "?")
        print(f"\n  Scene {sn}: {scene.get('summary', '')[:100]}")
        print(f"    POV: {scene.get('pov_character', '?')}  "
              f"Setting: {scene.get('setting', '?')}  "
              f"Δtension: {scene.get('tension_delta', 0):+.2f}")
        shifts = scene.get("emotional_shifts", {})
        if shifts:
            for char, dims in shifts.items():
                parts = [f"{d}{v:+.2f}" for d, v in dims.items()]
                print(f"    Emo: {char} → {', '.join(parts)}")

    display(planned_tension=outline.get("closing_tension"))
    run_forecast()

    print("\n  → Review the outline JSON, edit if needed, then run:")
    print(f"    python phase2_main.py approve {chapter}")
    print(f"    python phase2_main.py expand  {chapter}")


# ──────────────────────────────────────────────────────────────────
# approve
# ──────────────────────────────────────────────────────────────────

def cmd_approve(chapter: int):
    from phase2.planning.outline_planner import approve_outline
    if approve_outline(chapter):
        print(f"  ✓ Outline for chapter {chapter} marked as approved")
    else:
        print(f"  ✗ No outline found for chapter {chapter}")


# ──────────────────────────────────────────────────────────────────
# expand
# ──────────────────────────────────────────────────────────────────

def cmd_expand(chapter: int):
    from phase2.planning.expander import expand_chapter

    print(f"\n━━━ Expanding Chapter {chapter} ━━━\n")
    t0 = time.time()
    draft = expand_chapter(chapter)
    dt = time.time() - t0

    if draft is None:
        print("  FAILED — no draft produced.")
        return

    print(f"\n  Expansion complete in {dt:.1f}s")
    print(f"  Word count: {len(draft.split())}")
    print("  → Review the draft, edit if needed, then run:")
    print(f"    python phase2_main.py validate {chapter}")


# ──────────────────────────────────────────────────────────────────
# validate
# ──────────────────────────────────────────────────────────────────

def cmd_validate(chapter: int):
    from phase2.analysis.validator import validate_chapter

    print(f"\n━━━ Validating Chapter {chapter} ━━━\n")
    report = validate_chapter(chapter)

    if report is None:
        return

    print(f"\n  Overall Risk: {report['overall_risk'].upper()}")
    for check_name, check_data in report["checks"].items():
        status = "✓ PASS" if check_data.get("pass") else "✗ FAIL"
        print(f"\n  {check_name}: {status}")
        for key in ("details", "violations", "issues"):
            items = check_data.get(key, [])
            for item in items:
                print(f"    {item}")


# ──────────────────────────────────────────────────────────────────
# update (after Phase 1 canonisation)  — Audit Fix #1 applied
# ──────────────────────────────────────────────────────────────────

def cmd_update(chapter: int):
    """Update Phase 2 state after Phase 1 has canonised a chapter."""
    # ── AUDIT FIX #1: Prevent update if Phase 1 hasn't run ──────
    _require_phase1_done(chapter)

    from phase2.state.thread_health import ThreadHealthTracker
    from phase2.state.tension_model import TensionTracker
    from phase2.state.emotional_state import EmotionalState
    from phase2.planning.outline_planner import load_outline

    print(f"\n━━━ Updating Phase 2 State: Chapter {chapter} ━━━\n")

    story_state = _load_story_state()
    outline = load_outline(chapter)

    # ── Thread health ────────────────────────────────────────────
    tracker = ThreadHealthTracker()
    touched: list[str] = []
    resolved: list[str] = []
    new_threads: list[dict] = []

    if outline:
        touched = list(outline.get("threads_advanced", []))
        resolved = list(outline.get("threads_to_resolve", []))

    for tname, tdata in story_state.get("plot_threads", {}).items():
        if tname not in tracker.threads:
            new_threads.append({"name": tname, "importance": 3})
        for u in tdata.get("updates", []):
            if u.get("chapter") == chapter and tname not in touched:
                touched.append(tname)
        if tdata.get("status") == "resolved" and tname not in resolved:
            for u in tdata.get("updates", []):
                if (u.get("chapter") == chapter
                        and "resolved" in u.get("detail", "").lower()):
                    resolved.append(tname)

    warnings = tracker.advance_chapter(chapter, touched, resolved, new_threads)
    print(f"  Threads: {len(touched)} touched, {len(resolved)} resolved, "
          f"{len(new_threads)} new")
    for w in warnings:
        print(f"    ⚠ {w}")

    # ── Tension — Audit Fix #4: Chapter gap detection ─────────────
    tension = TensionTracker()
    history = tension.state.get("history", [])
    if history:
        last_ch = history[-1].get("chapter", 0)
        if chapter != last_ch + 1:
            print(f"  ⚠ Chapter gap detected: expected ch {last_ch+1}, got {chapter}")

    if outline and "closing_tension" in outline:
        new_tension = outline["closing_tension"]
    else:
        events = [e for e in story_state.get("events", [])
                  if e.get("chapter") == chapter]
        delta = min(0.1, len(events) * 0.03)
        new_tension = round(tension.current + delta, 2)
        print(f"  Tension: no outline — estimated delta +{delta:.2f}")

    t_warnings = tension.record(chapter, new_tension)
    print(f"  Tension: {tension.current:.2f}  Phase: {tension.phase}")
    for w in t_warnings:
        print(f"    ⚠ {w}")

    # ── Emotional state — Audit Fix #2: only active characters ───
    emo = EmotionalState()

    # Compute active characters (updated in last 10 chapters or in active threads)
    active_threads = [t for t, d in tracker.threads.items()
                      if d.get("status") == "active"]
    recent_chapter_threshold = chapter - 10
    active_char_ids: set[str] = set()
    for cid, cdata in story_state.get("characters", {}).items():
        last_update = max(
            (u.get("chapter", 0) for u in cdata.get("updates", [])),
            default=cdata.get("first_appearance", 0)
        )
        if last_update >= recent_chapter_threshold:
            active_char_ids.add(cdata.get("display_name", cid))

    for name in story_state.get("characters", {}).values():
        display_name = name.get("display_name", "")
        if display_name:
            emo.ensure(display_name)

    if outline:
        all_shifts: dict[str, dict[str, float]] = {}
        triggers: dict[str, str] = {}
        for scene in outline.get("scenes", []):
            for char, dims in scene.get("emotional_shifts", {}).items():
                # ── Audit Fix #2: skip non-active characters ────
                if char not in active_char_ids:
                    continue
                if char not in all_shifts:
                    all_shifts[char] = {}
                for dim, delta in dims.items():
                    all_shifts[char][dim] = (
                        all_shifts[char].get(dim, 0) + delta)
            for char in scene.get("emotional_shifts", {}):
                if char in active_char_ids:
                    triggers[char] = scene.get("summary", "")[:100]

        if all_shifts:
            e_warnings = emo.apply_shifts(chapter, all_shifts, triggers)
            print(f"  Emotional: {len(all_shifts)} active character(s) updated")
            for w in e_warnings:
                print(f"    ⚠ {w}")
        else:
            print("  Emotional: no shifts for active characters")
    else:
        print("  Emotional: no outline — skipping emotional update")

    emo.save()
    print(f"\n  ✓ Phase 2 state updated for chapter {chapter}")


# ──────────────────────────────────────────────────────────────────
# metrics
# ──────────────────────────────────────────────────────────────────

def cmd_metrics():
    from phase2.analysis.narrative_metrics import display
    display()


# ──────────────────────────────────────────────────────────────────
# forecast
# ──────────────────────────────────────────────────────────────────

def cmd_forecast():
    from phase2.analysis.forecasting import forecast as run_forecast
    run_forecast()


# ──────────────────────────────────────────────────────────────────
# dashboard  — Audit Bonus: single-glance story state
# ──────────────────────────────────────────────────────────────────

def cmd_dashboard():
    """One glance at the story state: arc, tension, threads, characters."""
    from phase2.state.thread_health import ThreadHealthTracker
    from phase2.state.tension_model import TensionTracker
    from phase2.state.emotional_state import EmotionalState

    print("\n" + "═" * 60)
    print("  PHASE 2 NARRATIVE DASHBOARD")
    print("═" * 60)

    tension = TensionTracker()
    print(f"\n  Arc Phase   : {tension.phase.upper()}")
    print(f"  Tension     : {tension.current:.2f}  "
          f"(trend: {tension.state.get('recent_trend', '?')})")

    tracker = ThreadHealthTracker()
    active = [(n, d) for n, d in tracker.threads.items()
              if d.get("status") == "active"]
    dormant = [(n, d) for n, d in tracker.threads.items()
               if d.get("status") == "dormant"]

    # top 5 by pressure
    top5 = sorted(active, key=lambda x: x[1].get("resolution_pressure", 0), reverse=True)[:5]
    print(f"\n  Top 5 Threads by Pressure:")
    for name, d in top5:
        print(f"    [{d.get('resolution_pressure', 0):.2f}] {name}"
              f"  (pos: {d.get('narrative_position', '?')})")

    if dormant:
        print(f"\n  Dormant Threads ({len(dormant)}):")
        for name, d in dormant[:5]:
            print(f"    · {name}  (last ch {d.get('last_touched_chapter', '?')})")

    emo = EmotionalState()
    # most emotionally active (highest variance)
    act_chars = sorted(
        emo.characters.items(),
        key=lambda x: x[1].get("last_updated_chapter") or 0,
        reverse=True
    )[:5]
    print(f"\n  Top 5 Characters by Activity:")
    for name, cd in act_chars:
        dims = cd.get("dimensions", {})
        dim_str = "  ".join(f"{k[0].upper()}:{v:.2f}" for k, v in dims.items())
        print(f"    {name:20s}  {dim_str}")

    print("\n" + "═" * 60 + "\n")


# ──────────────────────────────────────────────────────────────────
# inspect — dump raw state for debugging
# ──────────────────────────────────────────────────────────────────

def cmd_inspect(target: str):
    from phase2 import config as p2
    targets = {
        "threads":   p2.THREAD_HEALTH_FILE,
        "tension":   p2.TENSION_STATE_FILE,
        "emotional": p2.EMOTIONAL_STATE_FILE,
        "story":     config.STORY_STATE_FILE,
        "conflicts": config.CONFLICT_LOG_FILE,
    }
    path = targets.get(target)
    if path is None:
        print(f"Unknown target '{target}'.  Choose from: {', '.join(targets)}")
        return
    data = load_json(path)
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ──────────────────────────────────────────────────────────────────
# set — manual overrides
# ──────────────────────────────────────────────────────────────────

def cmd_set_tension(value: float):
    from phase2.state.tension_model import TensionTracker
    tension = TensionTracker()
    old = tension.current
    tension.state["current_tension"] = round(max(0.0, min(1.0, value)), 3)
    tension.save()
    print(f"  Tension: {old:.3f} → {tension.current:.3f}")


def cmd_set_importance(thread_name: str, importance: int):
    from phase2.state.thread_health import ThreadHealthTracker
    tracker = ThreadHealthTracker()
    if thread_name not in tracker.threads:
        matches = [t for t in tracker.threads if thread_name.lower() in t.lower()]
        if len(matches) == 1:
            thread_name = matches[0]
        elif matches:
            print(f"  Ambiguous match: {matches}")
            return
        else:
            print(f"  Thread '{thread_name}' not found")
            return
    importance = max(1, min(5, importance))
    old = tracker.threads[thread_name]["importance"]
    tracker.threads[thread_name]["importance"] = importance
    tracker.save()
    print(f"  '{thread_name}' importance: {old} → {importance}")


def cmd_set_emotion(character: str, dimension: str, value: float):
    from phase2.state.emotional_state import EmotionalState
    from phase2 import config as p2
    if dimension not in p2.EMOTIONAL_DIMENSIONS:
        print(f"  Unknown dimension '{dimension}'.  "
              f"Choose from: {', '.join(p2.EMOTIONAL_DIMENSIONS)}")
        return
    emo = EmotionalState()
    emo.ensure(character)
    old = emo.characters[character]["dimensions"][dimension]
    emo.characters[character]["dimensions"][dimension] = round(
        max(0.0, min(1.0, value)), 3)
    emo.save()
    print(f"  {character}.{dimension}: {old:.3f} → {value:.3f}")


# ──────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────

USAGE = """\
Phase 2 — Narrative Co-Writer CLI

Core workflow:
  python phase2_main.py init                          Initialise from Phase 1
  python phase2_main.py outline <ch> "<direction>"    Generate outline (Pass 1)
  python phase2_main.py approve <ch>                  Approve outline for expansion
  python phase2_main.py expand  <ch>                  Expand to draft (Pass 2)
  python phase2_main.py validate <ch>                 Validate draft vs outline
  python phase2_main.py update  <ch>                  Update state post-canonisation

Telemetry:
  python phase2_main.py dashboard                     One-glance story state panel
  python phase2_main.py metrics                       Show narrative dashboard
  python phase2_main.py forecast                      Show 3-chapter projection

Debugging:
  python phase2_main.py inspect <threads|tension|emotional|story|conflicts>
  python phase2_main.py set_tension <0.0-1.0>
  python phase2_main.py set_importance "<thread>" <1-5>
  python phase2_main.py set_emotion "<character>" <dimension> <0.0-1.0>
"""


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "init":
        cmd_init()
        return

    if cmd == "dashboard":
        if not _check_p2_state():
            sys.exit(1)
        cmd_dashboard()
        return

    if cmd == "inspect":
        if len(sys.argv) < 3:
            print("Usage: phase2_main.py inspect <threads|tension|emotional|story|conflicts>")
            sys.exit(1)
        cmd_inspect(sys.argv[2].lower())
        return

    if cmd not in ("set_tension", "set_importance", "set_emotion"):
        if not _check_p2_state():
            print("  Run:  python phase2_main.py init")
            sys.exit(1)

    if cmd == "outline":
        if len(sys.argv) < 4:
            print('Usage: phase2_main.py outline <chapter_number> "<direction>"')
            sys.exit(1)
        ch = _require_int(sys.argv[2], "chapter_number")
        direction = " ".join(sys.argv[3:])
        cmd_outline(ch, direction)

    elif cmd == "approve":
        if len(sys.argv) < 3:
            print("Usage: phase2_main.py approve <chapter_number>")
            sys.exit(1)
        cmd_approve(_require_int(sys.argv[2], "chapter_number"))

    elif cmd == "expand":
        if len(sys.argv) < 3:
            print("Usage: phase2_main.py expand <chapter_number>")
            sys.exit(1)
        cmd_expand(_require_int(sys.argv[2], "chapter_number"))

    elif cmd == "validate":
        if len(sys.argv) < 3:
            print("Usage: phase2_main.py validate <chapter_number>")
            sys.exit(1)
        cmd_validate(_require_int(sys.argv[2], "chapter_number"))

    elif cmd == "update":
        if len(sys.argv) < 3:
            print("Usage: phase2_main.py update <chapter_number>")
            sys.exit(1)
        cmd_update(_require_int(sys.argv[2], "chapter_number"))

    elif cmd == "metrics":
        cmd_metrics()

    elif cmd == "forecast":
        cmd_forecast()

    elif cmd == "set_tension":
        if len(sys.argv) < 3:
            print("Usage: phase2_main.py set_tension <value>")
            sys.exit(1)
        cmd_set_tension(_require_float(sys.argv[2], "tension"))

    elif cmd == "set_importance":
        if len(sys.argv) < 4:
            print('Usage: phase2_main.py set_importance "<thread_name>" <1-5>')
            sys.exit(1)
        cmd_set_importance(sys.argv[2], _require_int(sys.argv[3], "importance"))

    elif cmd == "set_emotion":
        if len(sys.argv) < 5:
            print('Usage: phase2_main.py set_emotion "<character>" <dimension> <0.0-1.0>')
            sys.exit(1)
        cmd_set_emotion(sys.argv[2], sys.argv[3],
                        _require_float(sys.argv[4], "value"))

    else:
        print(f"Unknown command: {cmd}\n")
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
