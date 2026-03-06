"""
Track narrative tension with hard constraints.
Deterministic arc-phase detection.  Bounds computation for planners.
No LLM calls.
"""

from __future__ import annotations

import json
import os

from phase2 import config as p2
from logger import get_logger
log = get_logger(__name__)
from io_utils import load_json, save_json


# ──────────────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────────────




def _empty_state() -> dict:
    return {
        "current_tension": p2.DEFAULT_INITIAL_TENSION,
        "arc_phase": "setup",
        "chapters_since_last_spike": 0,
        "recent_trend": "stable",
        "consecutive_spikes": 0,
        "history": [],
    }


# ──────────────────────────────────────────────────────────────────
# Arc-phase heuristic (H6)
# ──────────────────────────────────────────────────────────────────

def _detect_phase(tension: float, trend: str, prev_phase: str) -> str:
    if prev_phase == "climax" and tension < 0.80:
        return "cooldown"
    if prev_phase == "cooldown" and trend == "rising":
        return "rising"            # new arc beginning
    if tension >= 0.80:
        return "climax"
    if tension >= 0.60 and trend == "rising":
        return "pre_climax"
    if tension >= 0.30 and trend == "rising":
        return "rising"
    if tension < 0.30:
        return "setup"
    return prev_phase              # keep current if ambiguous


def _detect_trend(history: list[dict], window: int = 3) -> str:
    if len(history) < 2:
        return "stable"
    recent = history[-window:]
    deltas = [h.get("delta", 0.0) for h in recent]
    avg = sum(deltas) / len(deltas)
    if avg > 0.03:
        return "rising"
    if avg < -0.03:
        return "falling"
    return "stable"


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

class TensionTracker:
    """Manages tension_state.json."""

    def __init__(self):
        raw = load_json(p2.TENSION_STATE_FILE)
        self.state: dict = raw if raw else _empty_state()

    def save(self) -> None:
        save_json(p2.TENSION_STATE_FILE, self.state)

    # ── accessors ────────────────────────────────────────────────

    @property
    def current(self) -> float:
        return self.state["current_tension"]

    @property
    def phase(self) -> str:
        return self.state["arc_phase"]

    @property
    def trend(self) -> str:
        return self.state["recent_trend"]

    @property
    def history(self) -> list[dict]:
        return self.state["history"]

    # ── init ─────────────────────────────────────────────────────

    def init(self, tension: float = None) -> None:
        self.state = _empty_state()
        if tension is not None:
            self.state["current_tension"] = round(
                max(0.0, min(1.0, tension)), 2)
        self.save()

    def estimate_initial_tension(self, story_state: dict) -> float:
        """Heuristic: event density + unresolved thread ratio."""
        events  = story_state.get("events", [])
        threads = story_state.get("plot_threads", {})
        chapters = story_state.get("metadata", {}).get("chapters_processed", [])
        if not chapters:
            return p2.DEFAULT_INITIAL_TENSION

        # event density over last 5 chapters
        last_5 = set(chapters[-5:])
        recent  = [e for e in events if e.get("chapter") in last_5]
        density = min(1.0, len(recent) / 10.0)

        # unresolved ratio
        unresolved = sum(1 for t in threads.values()
                         if t.get("status") != "resolved")
        total = max(1, len(threads))
        pressure = unresolved / total

        tension = 0.25 + 0.35 * density + 0.25 * pressure
        return round(min(0.90, tension), 2)

    # ── constraint checking ──────────────────────────────────────

    def get_bounds(self) -> tuple[float, float]:
        """Return (min_allowed, max_allowed) tension for the next chapter."""
        cur = self.current
        hist = self.history

        lo = max(0.0, cur - 0.25)
        hi = min(1.0, cur + 0.25)

        # T2 — no triple spike
        if len(hist) >= 2:
            if all(h.get("delta", 0) > p2.SPIKE_THRESHOLD for h in hist[-2:]):
                hi = min(hi, cur + p2.SPIKE_THRESHOLD)

        # T3 — mandatory cooldown after climax
        if hist and hist[-1].get("phase") == "climax":
            hi = cur - p2.COOLDOWN_MIN_DROP

        # T5 — no premature climax
        if len(hist) < p2.MIN_CHAPTERS_BEFORE_CLIMAX:
            hi = min(hi, 0.80)

        lo = round(max(0.0, lo), 2)
        hi = round(max(lo, min(1.0, hi)), 2)   # ensure hi ≥ lo
        return lo, hi

    def validate_planned(self, planned: float) -> tuple[bool, list[str]]:
        """Check a planned tension value against all hard constraints."""
        lo, hi = self.get_bounds()
        issues: list[str] = []

        if planned < lo:
            issues.append(f"Planned tension {planned:.2f} below floor {lo:.2f}")
        if planned > hi:
            issues.append(f"Planned tension {planned:.2f} above ceiling {hi:.2f}")

        # T4 — stagnation warning (soft)
        if len(self.history) >= p2.STAGNATION_WINDOW:
            recent = self.history[-p2.STAGNATION_WINDOW:]
            if all(abs(h.get("delta", 0)) < p2.STAGNATION_DELTA for h in recent):
                if abs(planned - self.current) < p2.STAGNATION_DELTA:
                    issues.append(
                        f"Stagnation: tension flat for {p2.STAGNATION_WINDOW}+ "
                        f"chapters, planned delta still < {p2.STAGNATION_DELTA}")

        return len(issues) == 0, issues

    # ── recording ────────────────────────────────────────────────

    def record(self, chapter: int, new_tension: float) -> list[str]:
        """Commit a tension value.  Returns warnings."""
        warnings: list[str] = []
        new_tension = round(max(0.0, min(1.0, new_tension)), 3)
        delta = round(new_tension - self.current, 3)

        # spike tracking
        is_spike = delta > p2.SPIKE_THRESHOLD
        if is_spike:
            self.state["consecutive_spikes"] += 1
            self.state["chapters_since_last_spike"] = 0
        else:
            self.state["consecutive_spikes"] = 0
            self.state["chapters_since_last_spike"] += 1

        old_phase = self.state["arc_phase"]
        self.state["current_tension"] = new_tension

        self.state["history"].append({
            "chapter": chapter,
            "tension": new_tension,
            "delta": delta,
            "phase": old_phase,
        })

        self.state["recent_trend"] = _detect_trend(self.history)
        self.state["arc_phase"] = _detect_phase(
            new_tension, self.state["recent_trend"], old_phase)

        # post-record warnings
        valid, issues = self.validate_planned(new_tension)
        warnings.extend(issues)

        self.save()
        return warnings
