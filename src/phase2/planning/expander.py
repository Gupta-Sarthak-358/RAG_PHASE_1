"""
Pass 2: expand an approved outline into a full chapter draft.
Scene-by-scene LLM expansion with RAG context and emotional targets.
"""

from __future__ import annotations

import json
import os

from phase1 import config
from phase2 import config as p2
from phase1.model_loader import ModelLoader
from phase2.state.emotional_state import EmotionalState
from phase2.planning.outline_planner import load_outline
from io_utils import load_json, save_json


# ──────────────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────────────




def _save_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def draft_path(chapter: int) -> str:
    return os.path.join(p2.DRAFTS_DIR, f"chapter_{chapter:03d}_draft.txt")


# ──────────────────────────────────────────────────────────────────
# Prompt builders
# ──────────────────────────────────────────────────────────────────

def _tension_description(opening: float, delta: float) -> str:
    level = opening + delta
    if level >= 0.8:
        return "extremely high tension — crisis point"
    if level >= 0.6:
        return "high tension — urgent, pressing"
    if level >= 0.4:
        return "moderate tension — things are building"
    if level >= 0.2:
        return "low tension — reflective, measured"
    return "very low tension — calm, establishing"


def _emotional_targets(scene: dict, emo: EmotionalState) -> str:
    shifts = scene.get("emotional_shifts", {})
    if not shifts:
        return "No specific emotional shifts this scene."
    lines = []
    for char, dims in shifts.items():
        current = emo.get_dims(char)
        parts = []
        for dim, delta in dims.items():
            old = current.get(dim, p2.EMOTIONAL_DEFAULT)
            new = max(0.0, min(1.0, old + delta))
            direction = "increase" if delta > 0 else "decrease"
            parts.append(f"{dim}: {direction} ({old:.2f}→{new:.2f})")
        lines.append(f"  {char}: {', '.join(parts)}")
    return "\n".join(lines)


def _get_rag_context(query: str, top_k: int = 2) -> str:
    try:
        from phase1.retriever import Retriever
        r = Retriever()
        hits = r.query(query, top_k=top_k)
        if hits:
            return "\n---\n".join(h["text"][:400] for h in hits)
    except FileNotFoundError:
        pass
    return ""


def _character_context(story_state: dict, names: list[str]) -> str:
    chars = story_state.get("characters", {})
    lines = []
    for name in names:
        if name in chars:
            c = chars[name]
            lines.append(
                f"  {name} [{c.get('status','?')}]: "
                f"{(c.get('description') or '')[:150]}")
    return "\n".join(lines) if lines else "(no character data)"


def _scene_prompt(
    chapter: int,
    scene: dict,
    outline: dict,
    story_state: dict,
    emo: EmotionalState,
    previous_ending: str,
) -> str:
    scene_num = scene.get("scene_number", 1)
    total     = outline.get("scene_count", len(outline.get("scenes", [])))
    pov       = scene.get("pov_character", "unknown")
    setting   = scene.get("setting", "unspecified")
    summary   = scene.get("summary", "")
    notes     = scene.get("notes", "")

    # ── Audit Fix #9: Normalize POV name through alias table ─────
    try:
        from phase1.canon.merger.character_manager import CharacterManager
        cm = CharacterManager()
        pov_resolved = cm.resolve_char_id(pov)
        # resolve_char_id returns an ID or None; map back to display name if resolved
        if pov_resolved and pov_resolved in story_state.get("characters", {}):
            canonical = story_state["characters"][pov_resolved].get("display_name", pov)
            pov = canonical
    except Exception:
        pass  # fallback to raw pov if alias system unavailable

    opening_t = outline.get("opening_tension", 0.5)
    cumulative_delta = sum(
        s.get("tension_delta", 0)
        for s in outline.get("scenes", [])[:scene_num])

    # characters mentioned in this scene
    involved = [pov]
    for char in scene.get("emotional_shifts", {}):
        if char not in involved:
            involved.append(char)

    rag = _get_rag_context(summary, top_k=p2.RAG_TOP_K_EXPANDER)

    return (
        f"[INST] You are writing scene {scene_num} of {total} "
        f"for Chapter {chapter}.\n\n"

        f"Scene summary: {summary}\n"
        f"POV character: {pov}\n"
        f"Setting: {setting}\n"
        f"Notes: {notes}\n\n"

        f"Tension: {_tension_description(opening_t, cumulative_delta)}\n\n"

        f"Emotional targets:\n{_emotional_targets(scene, emo)}\n\n"

        f"Character context:\n{_character_context(story_state, involved)}\n\n"

        + (f"Relevant story context:\n{rag}\n\n" if rag else "")
        + (f"Previous scene ended with:\n\"{previous_ending}\"\n\n"
           if previous_ending else "")
        +
        f"Write this scene in approximately {p2.SCENE_WORD_TARGET} words. "
        f"Stay in {pov}'s perspective. "
        f"Hit the emotional targets naturally through action and dialogue. "
        f"Do not summarize — write full prose. "
        f"Do not add author notes.\n\n"
        f"Scene: [/INST]"
    )


# ──────────────────────────────────────────────────────────────────
# Expansion logic
# ──────────────────────────────────────────────────────────────────

def _last_sentences(text: str, n: int | None = None) -> str:
    """Return last *n* sentences of *text*."""
    sentences = [s.strip() for s in text.replace("\n", " ").split(".")
                 if s.strip()]
    return ". ".join(sentences[-n:]) + "." if sentences else ""


def expand_chapter(chapter: int) -> str | None:
    """
    Expand an approved outline into a full chapter draft.
    Saves to drafts/ directory.  Returns the full text or None.
    """
    outline = load_outline(chapter)
    if outline is None:
        print(f"  No outline found for chapter {chapter}")
        return None

    if outline.get("status") not in ("approved", "pending"):
        print(f"  Outline status is '{outline.get('status')}' — "
              f"expected 'approved' or 'pending'")
        # proceed anyway — user may want to expand a pending outline

    story_state = load_json(config.STORY_STATE_FILE, {})
    emo = EmotionalState()

    scenes = outline.get("scenes", [])
    if not scenes:
        print("  Outline has no scenes")
        return None

    full_text_parts: list[str] = []
    previous_ending = ""

    for i, scene in enumerate(scenes):
        scene_num = scene.get("scene_number", i + 1)
        print(f"  Expanding scene {scene_num}/{len(scenes)} …")

        prompt = _scene_prompt(
            chapter, scene, outline, story_state, emo, previous_ending)

        raw = ModelLoader.safe_generate(
            p2.PHASE2_MODEL_NAME,
            prompt,
            max_tokens=p2.PHASE2_MAX_TOKENS,
            temperature=p2.EXPANSION_TEMPERATURE,
        )

        # Clean up common LLM artifacts
        text = raw.strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]

        full_text_parts.append(text)
        previous_ending = _last_sentences(text, 2)

    full_draft = "\n\n---\n\n".join(full_text_parts)

    # mark outline as expanded
    outline["status"] = "expanded"
    from phase2.planning.outline_planner import outline_path
    save_json(outline_path(chapter), outline)

    # save draft
    path = draft_path(chapter)
    _save_text(path, full_draft)
    word_count = len(full_draft.split())
    print(f"  Draft saved → {path}  ({word_count} words)")

    return full_draft
