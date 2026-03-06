"""
Visible telemetry panel.  Pure reporting — no logic, no mutations.
Reads all Phase 2 state files and prints a formatted dashboard.
"""

from __future__ import annotations

import json
import os

from phase1 import config
from phase2 import config as p2
from phase2.state.thread_health import ThreadHealthTracker
from phase2.state.tension_model import TensionTracker
from phase2.state.emotional_state import EmotionalState
from io_utils import load_json


# ──────────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────────

def _bar(value: float, width: int = 20) -> str:
    filled = int(round(value * width))
    return "█" * filled + "░" * (width - filled)


def _trend_arrow(trend: str) -> str:
    return {"rising": "↑", "falling": "↓", "stable": "→"}.get(trend, "?")


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def display(planned_tension: float | None = None) -> str:
    """Build and return the full metrics panel as a string.
    Also prints it to stdout."""

    tension = TensionTracker()
    tracker = ThreadHealthTracker()
    emo     = EmotionalState()

    # ── story state metadata ─────────────────────────────────────
    story_state = load_json(config.STORY_STATE_FILE, {})
    chapters_done = story_state.get("metadata", {}).get("chapters_processed", [])

    lines: list[str] = []
    lines.append("")
    lines.append("╔══════════════════════════════════════════════════════════╗")
    lines.append("║             N A R R A T I V E   M E T R I C S          ║")
    lines.append("╚══════════════════════════════════════════════════════════╝")

    # ── ARC PHASE ────────────────────────────────────────────────
    lines.append("")
    lines.append(f"  Arc Phase       : {tension.phase.upper()}")
    lines.append(f"  Chapters Done   : {len(chapters_done)}")

    # ── TENSION ──────────────────────────────────────────────────
    lines.append("")
    lines.append("  ── Tension ──────────────────────────────────────────")
    lines.append(f"  Current         : {_bar(tension.current)} {tension.current:.2f}")
    if planned_tension is not None:
        lines.append(
            f"  Planned         : {_bar(planned_tension)} {planned_tension:.2f}")
    lo, hi = tension.get_bounds()
    lines.append(f"  Allowed Range   : [{lo:.2f} – {hi:.2f}]")
    lines.append(f"  Trend           : {_trend_arrow(tension.trend)} {tension.trend}")
    lines.append(f"  Since Last Spike: {tension.state.get('chapters_since_last_spike', '?')} chapters")
    lines.append(f"  Consec. Spikes  : {tension.state.get('consecutive_spikes', 0)}")

    # ── THREAD HEALTH TABLE ──────────────────────────────────────
    lines.append("")
    lines.append("  ── Thread Health ────────────────────────────────────")
    lines.append(f"  {'Thread':<28} {'Imp':>3} {'Pres':>5} {'Dorm':>5} "
                 f"{'Esc':>3} {'Position':<18} {'Status':<8}")
    lines.append("  " + "─" * 80)

    all_threads = tracker.get_all()
    sorted_threads = sorted(all_threads.values(),
                            key=lambda t: (-t["importance"],
                                           -t["resolution_pressure"]))
    for t in sorted_threads:
        name = t["thread_name"][:27]
        lines.append(
            f"  {name:<28} {t['importance']:>3} "
            f"{t['resolution_pressure']:>5.2f} "
            f"{t['chapters_since_touched']:>5} "
            f"{t['escalation_level']:>3} "
            f"{t['narrative_position']:<18} "
            f"{t['status']:<8}")

    dormant = tracker.get_dormant()
    if dormant:
        lines.append(f"\n  ⚠ {len(dormant)} dormant thread(s)")

    # ── EMOTIONAL SHIFT SUMMARY ──────────────────────────────────
    lines.append("")
    lines.append("  ── Emotional Baselines (non-default) ────────────────")
    baselines = emo.get_all_baselines()
    shown = 0
    for name in sorted(baselines):
        dims = baselines[name]
        non_default = {d: v for d, v in dims.items()
                       if abs(v - p2.EMOTIONAL_DEFAULT) > 0.02}
        if non_default:
            parts = [f"{d}={v:.2f}" for d, v in non_default.items()]
            lines.append(f"  {name:<24} {', '.join(parts)}")
            shown += 1
            if shown >= 15:
                lines.append(f"  … and {len(baselines) - shown} more")
                break
    if shown == 0:
        lines.append("  (all characters at baseline)")

    # ── SCENE COUNT from latest outline ──────────────────────────
    lines.append("")
    latest_outline = None
    if chapters_done:
        next_ch = max(chapters_done) + 1
        opath = os.path.join(p2.OUTLINES_DIR,
                             f"chapter_{next_ch:03d}_outline.json")
        latest_outline = load_json(opath)
    if latest_outline:
        lines.append(
            f"  Latest Outline  : Chapter {latest_outline.get('chapter_number')}")
        lines.append(
            f"  Scene Count     : {latest_outline.get('scene_count', '?')}")
        flags = latest_outline.get("risk_flags", [])
        lines.append(f"  Risk Flags      : {len(flags)}")
        for fl in flags[:5]:
            lines.append(f"    • {fl}")

    # ── CONTINUITY RISK ──────────────────────────────────────────
    conflict_log = load_json(config.CONFLICT_LOG_FILE, [])
    lines.append("")
    lines.append(f"  Continuity Risk : {len(conflict_log)} conflict(s) logged")
    if conflict_log:
        for c in conflict_log[-3:]:
            lines.append(f"    Ch {c.get('chapter','?')}: {c.get('detail','')[:70]}")

    lines.append("")
    lines.append("═" * 60)

    output = "\n".join(lines)
    print(output)
    return output
