"""
Two-pass planner: Pass 1.
Builds a constrained outline prompt, calls Mistral, validates
the result against thread-health / tension / emotional rules.
Returns a structured outline dict with risk flags.
"""

from __future__ import annotations

import json
import os
import re

from phase1 import config
from phase2 import config as p2
from phase1.model_loader import ModelLoader
from io_utils import load_json, save_json
from phase2.state.thread_health import ThreadHealthTracker
from phase2.state.tension_model import TensionTracker
from phase2.state.emotional_state import EmotionalState


# ──────────────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────────────




def outline_path(chapter: int) -> str:
    return os.path.join(p2.OUTLINES_DIR, f"chapter_{chapter:03d}_outline.json")


# ──────────────────────────────────────────────────────────────────
# Context builders
# ──────────────────────────────────────────────────────────────────

def _recent_events(story_state: dict, n: int = 5) -> str:
    events = story_state.get("events", [])
    if not events:
        return "(no events recorded)"
    tail = events[-n * 3:]          # last few chapters may each have several events
    lines = []
    for e in tail:
        lines.append(f"  Ch {e.get('chapter', '?')}: {e.get('event', '')}")
    return "\n".join(lines[-15:])   # cap at 15 lines


def _character_summary(story_state: dict, limit: int = 12) -> str:
    chars = story_state.get("characters", {})
    # pick characters by number of updates (most active first)
    ranked = sorted(chars.items(),
                    key=lambda kv: -len(kv[1].get("updates", [])))[:limit]
    lines = []
    for name, c in ranked:
        status = c.get("status", "unknown")
        desc   = (c.get("description") or "")[:120]
        lines.append(f"  {name} [{status}]: {desc}")
    return "\n".join(lines) if lines else "(no characters)"


def _thread_summary(tracker: ThreadHealthTracker) -> str:
    active = tracker.get_active()
    if not active:
        return "(no active threads)"
    lines = []
    for t in sorted(active, key=lambda e: -e["resolution_pressure"]):
        lines.append(
            f"  • {t['thread_name']}  imp={t['importance']}  "
            f"pressure={t['resolution_pressure']:.2f}  "
            f"pos={t['narrative_position']}  "
            f"dormant_for={t['chapters_since_touched']}ch")
    return "\n".join(lines)


def _emotional_summary(emo: EmotionalState) -> str:
    baselines = emo.get_all_baselines()
    if not baselines:
        return "(no emotional data)"
    lines = []
    for name in sorted(baselines):
        dims = baselines[name]
        parts = [f"{d}={v:.2f}" for d, v in dims.items() if v != p2.EMOTIONAL_DEFAULT]
        if parts:
            lines.append(f"  {name}: {', '.join(parts)}")
    return "\n".join(lines[:10]) if lines else "(all at baseline)"


def _high_pressure_names(tracker: ThreadHealthTracker) -> str:
    hp = tracker.get_high_pressure(0.4)
    if not hp:
        return "none"
    return ", ".join(t["thread_name"] for t in hp[:5])


# ──────────────────────────────────────────────────────────────────
# Outline JSON schema shown to model
# ──────────────────────────────────────────────────────────────────

OUTLINE_SCHEMA = """{
  "chapter_number": <int>,
  "scene_count": <int>,
  "opening_tension": <float>,
  "closing_tension": <float>,
  "scenes": [
    {
      "scene_number": <int>,
      "summary": "<string>",
      "pov_character": "<string>",
      "setting": "<string>",
      "emotional_shifts": {"<character>": {"<dimension>": <float delta>}},
      "thread_interactions": ["<thread name>"],
      "tension_delta": <float>,
      "notes": "<string>"
    }
  ],
  "threads_advanced": ["<thread name>"],
  "threads_to_resolve": ["<thread name>"],
  "risk_flags": ["<string>"]
}"""


# ──────────────────────────────────────────────────────────────────
# Prompt builder
# ──────────────────────────────────────────────────────────────────

def _build_prompt(
    chapter: int,
    direction: str,
    story_state: dict,
    tracker: ThreadHealthTracker,
    tension: TensionTracker,
    emo: EmotionalState,
    rag_context: str,
) -> str:
    lo, hi = tension.get_bounds()
    return (
        "[INST] You are a story outline planner. "
        "Given the current story state and constraints, produce a "
        "scene-by-scene outline for the next chapter.\n\n"

        f"Chapter number: {chapter}\n"
        f"Author direction: \"{direction}\"\n\n"

        f"Current tension: {tension.current:.2f}  "
        f"Arc phase: {tension.phase}  Trend: {tension.trend}\n"
        f"Allowed tension range for this chapter: [{lo:.2f}, {hi:.2f}]\n\n"

        "Active plot threads (sorted by pressure):\n"
        f"{_thread_summary(tracker)}\n\n"

        "Key characters:\n"
        f"{_character_summary(story_state)}\n\n"

        "Character emotional baselines (non-default only):\n"
        f"{_emotional_summary(emo)}\n\n"

        "Recent events:\n"
        f"{_recent_events(story_state)}\n\n"

        "Relevant story context:\n"
        f"{rag_context}\n\n"

        "Produce a JSON outline matching this schema:\n"
        f"{OUTLINE_SCHEMA}\n\n"

        "Rules:\n"
        f"- closing_tension MUST be between {lo:.2f} and {hi:.2f}\n"
        f"- Each emotional shift delta must be between -{p2.MAX_EMOTIONAL_DELTA} "
        f"and +{p2.MAX_EMOTIONAL_DELTA}\n"
        f"- Address at least one high-pressure thread: {_high_pressure_names(tracker)}\n"
        "- Do NOT resolve threads unless the author direction explicitly says so\n"
        "- 3 to 6 scenes\n"
        "- Return ONLY the JSON object\n"
        "[/INST]"
    )


# ──────────────────────────────────────────────────────────────────
# JSON extraction (reused pattern from Phase 1)
# ──────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


# ──────────────────────────────────────────────────────────────────
# Post-LLM validation & risk flagging
# ──────────────────────────────────────────────────────────────────

def _validate_outline(
    outline: dict,
    chapter: int,
    tension: TensionTracker,
    emo: EmotionalState,
) -> list[str]:
    """Return list of risk-flag strings.  Mutates outline minimally."""
    flags: list[str] = []
    outline["chapter_number"] = chapter

    # ── tension bounds ───────────────────────────────────────────
    closing = outline.get("closing_tension", tension.current)
    ok, issues = tension.validate_planned(closing)
    flags.extend(issues)

    # ── emotional checks ─────────────────────────────────────────
    all_shifts: dict[str, dict[str, float]] = {}
    for scene in outline.get("scenes", []):
        for char, dims in scene.get("emotional_shifts", {}).items():
            if char not in all_shifts:
                all_shifts[char] = {}
            for dim, delta in dims.items():
                all_shifts[char][dim] = all_shifts[char].get(dim, 0) + delta

    ok_e, e_issues = emo.validate_planned_shifts(all_shifts)
    flags.extend(e_issues)

    # ── scene count sanity ───────────────────────────────────────
    scenes = outline.get("scenes", [])
    if len(scenes) < 1:
        flags.append("Outline has no scenes")
    if len(scenes) > 8:
        flags.append(f"Outline has {len(scenes)} scenes — consider trimming")

    # ── merge flags from model + our flags ───────────────────────
    existing = outline.get("risk_flags", [])
    outline["risk_flags"] = list(set(existing + flags))

    return flags


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def generate_outline(chapter: int, direction: str) -> dict | None:
    """
    Generate a constrained scene-by-scene outline.
    Saves to outlines/ directory.  Returns the outline dict or None.
    """
    # Load all state
    story_state = load_json(config.STORY_STATE_FILE, {})
    tracker     = ThreadHealthTracker()
    tension     = TensionTracker()
    emo         = EmotionalState()

    # RAG context (best-effort; skip if index missing)
    rag_context = "(no index available)"
    try:
        from phase1.retriever import Retriever
        r = Retriever()
        hits = r.query(direction, top_k=p2.RAG_TOP_K_OUTLINE)
        if hits:
            rag_context = "\n---\n".join(
                f"[Ch {h['chapter']}] {h['text'][:300]}" for h in hits)
    except FileNotFoundError:
        pass

    prompt = _build_prompt(
        chapter, direction, story_state, tracker, tension, emo, rag_context)

    # ── LLM call (retry once) ───────────────────────────────────
    outline = None
    for attempt in range(2):
        if attempt:
            print("  Retrying outline generation …")
        raw = ModelLoader.safe_generate(
            p2.PHASE2_MODEL_NAME,
            prompt,
            max_tokens=p2.PHASE2_MAX_TOKENS,
            temperature=p2.OUTLINE_TEMPERATURE)
        outline = _extract_json(raw)
        if outline is not None:
            break
        print(f"  JSON parse failed (attempt {attempt + 1})")

    if outline is None:
        print("  ERROR: outline generation failed")
        return None

    # ── validate & flag ──────────────────────────────────────────
    flags = _validate_outline(outline, chapter, tension, emo)

    outline.setdefault("opening_tension", tension.current)
    outline.setdefault("status", "pending")
    outline["direction"] = direction

    # ── save ─────────────────────────────────────────────────────
    path = outline_path(chapter)
    save_json(path, outline)
    print(f"  Outline saved → {path}")

    if flags:
        print(f"  ⚠ {len(flags)} risk flag(s):")
        for f in flags:
            print(f"    • {f}")

    return outline


def load_outline(chapter: int) -> dict | None:
    path = outline_path(chapter)
    if not os.path.exists(path):
        return None
    return load_json(path)


def approve_outline(chapter: int) -> bool:
    path = outline_path(chapter)
    outline = load_json(path)
    if outline is None:
        return False
    outline["status"] = "approved"
    save_json(path, outline)
    return True
