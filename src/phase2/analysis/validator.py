"""
Post-expansion validation.
Checks outline adherence, emotional compliance, thread progression,
and continuity.  Returns a structured report.
No regeneration.  No correction.  Only reporting.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from phase1 import config
from phase2 import config as p2
from phase1.model_loader import ModelLoader
from io_utils import load_json, save_json
from phase2.planning.outline_planner import load_outline
from phase2.state.emotional_state import EmotionalState
from phase2.planning.expander import draft_path


# ──────────────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────────────




def report_path(chapter: int) -> str:
    return os.path.join(p2.VALIDATIONS_DIR,
                        f"chapter_{chapter:03d}_report.json")


def _read_text(path: str) -> str | None:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


# ──────────────────────────────────────────────────────────────────
# Deterministic checks
# ──────────────────────────────────────────────────────────────────

def _check_threads(outline: dict, chapter_text: str) -> dict:
    """Check if threads listed in outline appear in the text."""
    text_lower = chapter_text.lower()
    advanced   = outline.get("threads_advanced", [])
    details: list[str] = []
    all_ok = True

    for tname in advanced:
        # check if thread name (or key words from it) appear in text
        words = [w for w in tname.lower().split() if len(w) > 3]
        found = any(w in text_lower for w in words) if words else False
        if not found:
            details.append(f"Thread '{tname}' planned but not clearly present in text")
            all_ok = False
        else:
            details.append(f"Thread '{tname}' — present ✓")

    return {"pass": all_ok, "details": details}


def _check_emotional_bounds(outline: dict) -> dict:
    """Check that planned emotional deltas are within bounds."""
    violations: list[str] = []
    for scene in outline.get("scenes", []):
        for char, dims in scene.get("emotional_shifts", {}).items():
            for dim, delta in dims.items():
                if abs(delta) > p2.MAX_EMOTIONAL_DELTA:
                    violations.append(
                        f"Scene {scene.get('scene_number')}: "
                        f"{char}.{dim} delta {delta:+.2f} exceeds "
                        f"±{p2.MAX_EMOTIONAL_DELTA}")
    return {"pass": len(violations) == 0, "violations": violations}


def _check_continuity(chapter_text: str, story_state: dict) -> dict:
    """Deterministic continuity checks against canon."""
    text_lower = chapter_text.lower()
    issues: list[str] = []

    for name, cdata in story_state.get("characters", {}).items():
        status = (cdata.get("status") or "").lower()
        name_lower = name.lower()
        # dead character speaking or acting
        if status in ("dead", "deceased", "killed"):
            # crude check: name appears in dialogue-like context
            if name_lower in text_lower:
                # check it's not a memory / flashback reference
                # simple heuristic: if name appears near "said" / "asked" etc.
                for verb in ("said", "asked", "replied", "shouted",
                             "whispered", "walked", "ran", "grabbed"):
                    pattern = rf"\b{re.escape(name_lower)}\b.{{0,30}}\b{verb}\b"
                    if re.search(pattern, text_lower):
                        issues.append(
                            f"Character '{name}' is {status} in canon "
                            f"but appears to act in this chapter")
                        break

    return {"pass": len(issues) == 0, "issues": issues}


# ──────────────────────────────────────────────────────────────────
# LLM-assisted outline adherence check
# ──────────────────────────────────────────────────────────────────

def _check_outline_adherence_llm(outline: dict, chapter_text: str) -> dict:
    """Use LLM to assess how well the draft follows the outline."""
    scene_summaries = "\n".join(
        f"  Scene {s.get('scene_number', i+1)}: {s.get('summary', '?')}"
        for i, s in enumerate(outline.get("scenes", []))
    )

    # Truncate chapter text to fit context
    words = chapter_text.split()
    if len(words) > 3000:
        chapter_text = " ".join(words[:3000]) + "\n[TRUNCATED]"

    prompt = (
        "[INST] You are a story editor checking whether a chapter draft "
        "follows its outline.\n\n"
        f"OUTLINE SCENES:\n{scene_summaries}\n\n"
        f"CHAPTER DRAFT:\n{chapter_text}\n\n"
        "For each scene in the outline, state whether the draft covers it "
        "(YES/PARTIAL/NO) and give a one-line note.\n\n"
        "Return a JSON object:\n"
        '{"scenes": [{"scene": <int>, "covered": "YES|PARTIAL|NO", '
        '"note": "<string>"}], '
        '"overall_adherence": "strong|moderate|weak"}\n\n'
        "Return ONLY the JSON. [/INST]"
    )

    raw = ModelLoader.generate_with_model(
        p2.PHASE2_MODEL_NAME, prompt, max_tokens=1024, temperature=p2.VALIDATOR_TEMPERATURE)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                data = None
        else:
            data = None

    if data is None:
        return {"pass": False, "details": ["LLM adherence check failed to parse"]}

    overall = data.get("overall_adherence", "unknown")
    details = []
    for sc in data.get("scenes", []):
        details.append(
            f"Scene {sc.get('scene')}: {sc.get('covered')} — {sc.get('note', '')}")

    return {"pass": overall in ("strong", "moderate"), "details": details,
            "overall_adherence": overall}


# ──────────────────────────────────────────────────────────────────
# Risk assessment
# ──────────────────────────────────────────────────────────────────

def _overall_risk(checks: dict) -> str:
    fails = sum(1 for v in checks.values() if not v.get("pass", True))
    if fails == 0:
        return "low"
    if fails <= 1:
        return "medium"
    return "high"


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def validate_chapter(chapter: int) -> dict | None:
    """
    Run all validation checks.  Returns the report dict and saves it.
    """
    outline = load_outline(chapter)
    if outline is None:
        print(f"  No outline for chapter {chapter}")
        return None

    # Try draft first, then fall back to chapters/ directory
    chapter_text = _read_text(draft_path(chapter))
    if chapter_text is None:
        # look in Phase 1 chapters directory
        import glob
        pattern = os.path.join(config.CHAPTERS_DIR,
                               f"*{chapter:02d}*") if chapter < 100 else \
                  os.path.join(config.CHAPTERS_DIR, f"*{chapter}*")
        matches = glob.glob(pattern)
        for m in matches:
            if m.endswith(".txt"):
                chapter_text = _read_text(m)
                break

    if chapter_text is None:
        print(f"  No chapter text found for chapter {chapter}")
        return None

    story_state = load_json(config.STORY_STATE_FILE, {})

    print(f"  Running validation on chapter {chapter} …")

    checks = {}

    # 1. Outline adherence (LLM)
    print("    • Outline adherence …")
    checks["outline_adherence"] = _check_outline_adherence_llm(
        outline, chapter_text)

    # 2. Emotional delta compliance
    print("    • Emotional compliance …")
    checks["emotional_delta_compliance"] = _check_emotional_bounds(outline)

    # 3. Thread progression
    print("    • Thread progression …")
    checks["thread_progression"] = _check_threads(outline, chapter_text)

    # 4. Continuity
    print("    • Continuity …")
    checks["continuity"] = _check_continuity(chapter_text, story_state)

    risk = _overall_risk(checks)

    report = {
        "chapter_number": chapter,
        "checks": checks,
        "overall_risk": risk,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    path = report_path(chapter)
    save_json(path, report)
    print(f"  Report saved → {path}  (risk: {risk})")

    return report
