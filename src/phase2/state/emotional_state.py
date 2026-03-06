"""
Track 5 emotional dimensions per character.
Bounded deltas.  Flag large shifts missing trigger tags.
Pure state management — no LLM calls.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy

from phase2 import config as p2
from io_utils import load_json, save_json


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

# I/O now via io_utils (atomic writes, no duplication)


def _default_dims() -> dict[str, float]:
    return {d: p2.EMOTIONAL_DEFAULT for d in p2.EMOTIONAL_DIMENSIONS}


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

class EmotionalState:
    """Manages emotional_state.json."""

    def __init__(self):
        raw = load_json(p2.EMOTIONAL_STATE_FILE, {"characters": {}, "history": []})
        self.characters: dict = raw.get("characters", {})
        self.history: list    = raw.get("history", [])

    # ── persistence ──────────────────────────────────────────────

    def save(self) -> None:
        save_json(p2.EMOTIONAL_STATE_FILE,
              {"characters": self.characters, "history": self.history})

    # ── character management ─────────────────────────────────────

    def ensure(self, name: str) -> None:
        if name not in self.characters:
            self.characters[name] = {
                "dimensions": _default_dims(),
                "last_updated_chapter": None,
            }

    def get_dims(self, name: str) -> dict[str, float]:
        self.ensure(name)
        return deepcopy(self.characters[name]["dimensions"])

    def get_all_baselines(self) -> dict[str, dict[str, float]]:
        return {n: deepcopy(c["dimensions"]) for n, c in self.characters.items()}

    # ── init from Phase 1 state ──────────────────────────────────

    def init_from_story_state(self, story_state: dict) -> int:
        """Create default emotional entries for every known character.
        Returns count of new characters added."""
        added = 0
        for name in story_state.get("characters", {}):
            if name not in self.characters:
                self.ensure(name)
                added += 1
        self.save()
        return added

    # ── apply shifts ─────────────────────────────────────────────

    def apply_shifts(
        self,
        chapter: int,
        shifts: dict[str, dict[str, float]],
        triggering_events: dict[str, str] | None = None,
    ) -> list[str]:
        """Apply emotional deltas.  Returns list of warning strings."""
        triggering_events = triggering_events or {}
        warnings: list[str] = []

        for char, dim_deltas in shifts.items():
            self.ensure(char)
            cd = self.characters[char]
            old = deepcopy(cd["dimensions"])

            for dim, delta in dim_deltas.items():
                if dim not in p2.EMOTIONAL_DIMENSIONS:
                    warnings.append(f"Unknown dimension '{dim}' for {char}")
                    continue

                # clamp delta
                clamped = max(-p2.MAX_EMOTIONAL_DELTA,
                              min(p2.MAX_EMOTIONAL_DELTA, delta))
                if round(abs(clamped), 4) != round(abs(delta), 4):
                    warnings.append(
                        f"{char}.{dim}: delta {delta:+.2f} clamped to {clamped:+.2f}")

                new_val = max(0.0, min(1.0, cd["dimensions"][dim] + clamped))
                cd["dimensions"][dim] = round(new_val, 3)

                # trigger check
                if abs(clamped) > p2.TRIGGER_EVENT_THRESHOLD:
                    if char not in triggering_events:
                        warnings.append(
                            f"{char}.{dim}: shift {clamped:+.2f} needs triggering event")

            cd["last_updated_chapter"] = chapter

            self.history.append({
                "chapter": chapter,
                "character": char,
                "old": old,
                "new": deepcopy(cd["dimensions"]),
                "deltas": dim_deltas,
                "trigger": triggering_events.get(char),
            })

        self.save()
        return warnings

    # ── validation helper ────────────────────────────────────────

    def validate_planned_shifts(
        self, shifts: dict[str, dict[str, float]]
    ) -> tuple[bool, list[str]]:
        """Check planned shifts against constraints.  Non-destructive."""
        warnings: list[str] = []
        for char, dim_deltas in shifts.items():
            for dim, delta in dim_deltas.items():
                if dim not in p2.EMOTIONAL_DIMENSIONS:
                    warnings.append(f"Unknown dimension '{dim}' for {char}")
                if abs(delta) > p2.MAX_EMOTIONAL_DELTA:
                    warnings.append(
                        f"{char}.{dim}: planned {delta:+.2f} exceeds ±{p2.MAX_EMOTIONAL_DELTA}")
        return len(warnings) == 0, warnings
