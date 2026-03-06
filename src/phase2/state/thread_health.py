"""
Track plot-thread health with deterministic heuristics.
Resolution pressure, dormancy detection, narrative-position transitions.
No LLM calls.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy

from phase2 import config as p2
from logger import get_logger
log = get_logger(__name__)
from io_utils import load_json, save_json


# ──────────────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────────────

# I/O now via io_utils (atomic writes, no duplication)


# ──────────────────────────────────────────────────────────────────
# Default entry
# ──────────────────────────────────────────────────────────────────

def _new_entry(name: str, introduced: int, importance: int = None,
               status: str = "active") -> dict:
    return {
        "thread_name":           name,
        "status":                status,
        "importance":            importance or p2.DEFAULT_IMPORTANCE,
        "chapters_since_touched": 0,
        "resolution_pressure":   0.0,
        "escalation_level":      0,
        "narrative_position":    "setup",
        "last_touched_chapter":  introduced,
        "introduced_chapter":    introduced,
        "history":               [{"chapter": introduced, "action": "introduced",
                                   "detail": ""}],
    }


# ──────────────────────────────────────────────────────────────────
# Heuristic calculations
# ──────────────────────────────────────────────────────────────────

def _dormancy_threshold(importance: int) -> int:
    return p2.DORMANCY_THRESHOLDS.get(importance, 10)


def _calc_pressure(since: int, importance: int) -> float:
    threshold = _dormancy_threshold(importance)
    return round(min(1.0, since / (threshold * p2.PRESSURE_DIVISOR)), 3)


def _update_narrative_position(entry: dict) -> None:
    """Transition narrative_position based on escalation + pressure."""
    esc  = entry["escalation_level"]
    pres = entry["resolution_pressure"]
    pos  = entry["narrative_position"]

    if entry["status"] == "resolved":
        return

    if pos == "setup" and esc >= 1:
        entry["narrative_position"] = "escalating"
    elif pos == "escalating" and esc >= 2:
        entry["narrative_position"] = "complication"
    elif pos == "complication" and pres > p2.CONVERGENCE_PRESSURE:
        entry["narrative_position"] = "convergence"
    elif pos == "convergence" and pres > p2.RESOLUTION_WINDOW_PRESSURE:
        entry["narrative_position"] = "resolution_window"


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

class ThreadHealthTracker:
    """Manages thread_health_state.json."""

    def __init__(self):
        raw = load_json(p2.THREAD_HEALTH_FILE, {"threads": {}, "current_chapter": 0})
        self.threads: dict[str, dict] = raw.get("threads", {})
        self.current_chapter: int     = raw.get("current_chapter", 0)

    def save(self) -> None:
        save_json(p2.THREAD_HEALTH_FILE,
              {"threads": self.threads, "current_chapter": self.current_chapter})

    # ── init from Phase 1 ───────────────────────────────────────

    def init_from_story_state(self, story_state: dict) -> int:
        """Import plot threads from story_state.json.  Returns count added."""
        chapters = story_state.get("metadata", {}).get("chapters_processed", [])
        latest = max(chapters) if chapters else 0
        self.current_chapter = latest
        added = 0

        for tname, tdata in story_state.get("plot_threads", {}).items():
            if tname in self.threads:
                continue

            introduced = tdata.get("introduced", 1)
            status_raw = (tdata.get("status") or "active").lower()
            status = "resolved" if status_raw == "resolved" else "active"

            # figure out last-touched chapter from updates
            last_ch = introduced
            for u in tdata.get("updates", []):
                c = u.get("chapter", 0)
                if c > last_ch:
                    last_ch = c

            entry = _new_entry(tname, introduced, status=status)
            entry["last_touched_chapter"] = last_ch
            entry["chapters_since_touched"] = max(0, latest - last_ch)
            entry["resolution_pressure"] = _calc_pressure(
                entry["chapters_since_touched"], entry["importance"])

            # Audit Fix #5: stable tier-based escalation heuristic
            # (avoids over-escalating threads with many minor updates)
            n_updates = len(tdata.get("updates", []))
            if n_updates <= 2:
                entry["escalation_level"] = 0
            elif n_updates <= 4:
                entry["escalation_level"] = 1
            elif n_updates <= 7:
                entry["escalation_level"] = 2
            else:
                entry["escalation_level"] = 3

            _update_narrative_position(entry)

            # dormancy check
            threshold = _dormancy_threshold(entry["importance"])
            if entry["chapters_since_touched"] > threshold and status != "resolved":
                entry["status"] = "dormant"

            self.threads[tname] = entry
            added += 1

        self.save()
        return added

    # ── per-chapter update ───────────────────────────────────────

    def advance_chapter(self, chapter: int,
                        touched: list[str],
                        resolved: list[str] | None = None,
                        new_threads: list[dict] | None = None) -> list[str]:
        """
        Update all threads for a new chapter.

        Parameters
        ----------
        touched   : thread names that appeared / were advanced
        resolved  : thread names resolved this chapter
        new_threads : list of {"name": str, "description": str, "importance": int}

        Returns warnings list.
        """
        resolved = resolved or []
        new_threads = new_threads or []
        warnings: list[str] = []
        self.current_chapter = chapter

        # add new threads
        for nt in new_threads:
            name = nt.get("name", "").strip()
            if not name:
                continue
            if name not in self.threads:
                imp = nt.get("importance", p2.DEFAULT_IMPORTANCE)
                self.threads[name] = _new_entry(name, chapter, importance=imp)

        # update every thread
        for tname, entry in self.threads.items():
            if entry["status"] == "resolved":
                # check for unexpected resurrection
                if tname in touched and tname not in resolved:
                    warnings.append(
                        f"Thread '{tname}' was resolved but touched in ch {chapter}")
                continue

            if tname in touched:
                entry["chapters_since_touched"] = 0
                entry["last_touched_chapter"] = chapter
                entry["history"].append(
                    {"chapter": chapter, "action": "advanced", "detail": ""})
                if entry["status"] == "dormant":
                    entry["status"] = "active"
            else:
                entry["chapters_since_touched"] += 1

            # recalculate pressure
            entry["resolution_pressure"] = _calc_pressure(
                entry["chapters_since_touched"], entry["importance"])

            # dormancy check
            threshold = _dormancy_threshold(entry["importance"])
            if (entry["chapters_since_touched"] > threshold
                    and entry["status"] == "active"):
                entry["status"] = "dormant"
                warnings.append(
                    f"Thread '{tname}' (importance {entry['importance']}) "
                    f"went dormant after {entry['chapters_since_touched']} chapters")
                log.warning(w)

            _update_narrative_position(entry)

        # resolve threads
        for tname in resolved:
            if tname in self.threads:
                self.threads[tname]["status"] = "resolved"
                self.threads[tname]["narrative_position"] = "setup"  # reset
                self.threads[tname]["resolution_pressure"] = 0.0
                self.threads[tname]["history"].append(
                    {"chapter": chapter, "action": "resolved", "detail": ""})

        self.save()
        return warnings

    # ── escalation (called manually or by outline planner) ───────

    def escalate(self, thread_name: str, chapter: int) -> None:
        if thread_name in self.threads:
            entry = self.threads[thread_name]
            entry["escalation_level"] = min(3, entry["escalation_level"] + 1)
            entry["history"].append(
                {"chapter": chapter, "action": "escalated",
                 "detail": f"→ level {entry['escalation_level']}"})
            _update_narrative_position(entry)
            self.save()

    # ── queries ──────────────────────────────────────────────────

    def get_active(self) -> list[dict]:
        return [deepcopy(e) for e in self.threads.values()
                if e["status"] in ("active", "dormant")]

    def get_high_pressure(self, threshold: float = 0.5) -> list[dict]:
        return sorted(
            [deepcopy(e) for e in self.threads.values()
             if e["resolution_pressure"] >= threshold
             and e["status"] != "resolved"],
            key=lambda e: -e["resolution_pressure"])

    def get_dormant(self) -> list[dict]:
        return [deepcopy(e) for e in self.threads.values()
                if e["status"] == "dormant"]

    def get_all(self) -> dict[str, dict]:
        return deepcopy(self.threads)
