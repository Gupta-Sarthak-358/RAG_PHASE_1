
"""
Evidence-anchored extraction with optimized prompt and retry logic.

Fix 1: Trimmed prompt — schema stays, essay removed.
Fix 2: Skip retry when JSON parses and validates on first attempt.
Fix 5: Whitespace-normalized evidence matching.
"""

import json
import os
import re
from datetime import datetime, timezone

from phase1 import config
from phase1.model_loader import ModelLoader

from logger import get_logger
log = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Schema — kept in full, instructions trimmed (Fix 1)
# ═══════════════════════════════════════════════════════════════════

EXTRACTION_SCHEMA = """{
  "chapter_number": <int>,
  "new_characters": [
    {
      "name": "<exact name from text>",
      "description": "<string>",
      "status": "<alive|dead|unknown>",
      "abilities": ["<string>"],
      "relationships": [
        {"character": "<string>", "relationship": "<ally|enemy|mentor|student|friend|romantic|family|rival>"}
      ],
      "evidence": "<exact sentence from chapter>"
    }
  ],
  "character_updates": [
    {
      "name": "<exact name from text>",
      "status": "<string or null>",
      "new_abilities": ["<string>"],
      "new_relationships": [
        {"character": "<string>", "relationship": "<ally|enemy|mentor|student|friend|romantic|family|rival>"}
      ],
      "detail": "<string>",
      "evidence": "<exact sentence from chapter>"
    }
  ],
  "major_events": [
    {"event": "<what happened>", "evidence": "<exact sentence from chapter>"}
  ],
  "new_plot_threads": [
    {"name": "<string>", "description": "<string>"}
  ],
  "resolved_plot_threads": ["<string>"],
  "relationship_events": [
    {
      "characters": ["<name_1>", "<name_2>"],
      "event_type": "<met|confession|kiss|argument|alliance|betrayal|trust_gain|trust_loss|romantic_progression|cooperation>",
      "description": "<what happened>",
      "evidence": "<exact sentence from chapter>"
    }
  ],
  "emotional_deltas": {
    "<character_name>": {
      "<hope|fear|anger|trust|grief>": <float between -0.3 and 0.3 (do not use + sign)>,
      "evidence": "<exact sentence from chapter>"
    }
  },
  "thread_progression": [
    {
      "thread_name": "<string>",
      "status_change": "<advanced|escalated|complicated|stalled|resolved>",
      "justification": "<short string>"
    }
  ]
}"""

REQUIRED_KEYS = [
    "chapter_number",
    "new_characters",
    "character_updates",
    "major_events",
    "new_plot_threads",
    "resolved_plot_threads",
    "relationship_events",
    "emotional_deltas",
    "thread_progression",
]

_LIST_KEYS = {
    "new_characters", "character_updates", "major_events",
    "new_plot_threads", "resolved_plot_threads",
    "relationship_events", "thread_progression",
}

_DICT_KEYS = {"emotional_deltas"}


# ═══════════════════════════════════════════════════════════════════
# Prompt — Fix 1: trimmed instructions, same schema
# ═══════════════════════════════════════════════════════════════════

def _build_prompt(chapter_number: int, chapter_text: str) -> str:
    return (
        f"You are a structured data extraction engine.\n"
        f"Read the chapter and output ONE JSON object that matches this schema.\n\n"
        f"{EXTRACTION_SCHEMA}\n\n"
        f"STRICT RULES:\n"
        f"- Return ONLY one JSON object.\n"
        f"- Do NOT include explanations.\n"
        f"- Do NOT validate or correct the JSON.\n"
        f"- Do NOT output multiple JSON blocks.\n"
        f"- Do NOT output text before or after the JSON.\n"
        f"- If any text appears outside the JSON object, the result will be discarded.\n\n"
        f"Extraction rules:\n"
        f"- Do not invent characters or events.\n"
        f"- Use character names exactly as they appear in the text.\n"
        f"- Evidence must be an exact quote from the chapter.\n"
        f"- If no evidence exists for an item, do not include it.\n"
        f"- If a field has no data, return [] or {{}}.\n"
        f"- Do not combine multiple people into one character.\n"
        f"- Abilities must be short technique names (max 6 words). Do not include explanations.\n"
        f"- Escape all internal quotes within strings using \\\" to ensure valid JSON.\n"
        f"- Relationship types must be one of: ally, enemy, mentor, student, friend, romantic, family, rival.\n"
        f"- chapter_number must be {chapter_number}.\n\n"
        f"--- BEGIN CHAPTER {chapter_number} ---\n"
        f"{chapter_text}\n"
        f"--- END CHAPTER {chapter_number} ---\n"
    )


# ═══════════════════════════════════════════════════════════════════
# JSON repair pipeline  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _try_parse(text: str) -> dict | None:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _bracket_extract(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            if in_string:
                escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    last = text.rfind("}")
    if last > start:
        return text[start : last + 1]
    return None


def _repair_json_string(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    text = re.sub(r",\s*(\])", r"\1", text)
    text = re.sub(r",\s*(\})", r"\1", text)
    double_count = len(re.findall(r'(?<![\\])"', text))
    single_count = len(re.findall(r"(?<![\\])'", text))
    if single_count > double_count:
        text = re.sub(r"'([^']*?)'(\s*[:,\]\}\[])", r'"\1"\2', text)
        text = re.sub(r"([:,\[\{])\s*'([^']*?)'", r'\1"\2"', text)
    def _esc(m):
        inner = m.group(1).replace("\n", "\\n").replace("\r", "\\r")
        return f'"{inner}"'
    text = re.sub(
        r'"((?:[^"\\]|\\.)*)(?:\n)((?:[^"\\]|\\.)*)"', _esc, text)
    text = re.sub(r"(\})\s*(\{)", r"\1,\2", text)
    text = re.sub(r"(\])\s*(\[)", r"\1,\2", text)
    text = re.sub(r'(\})\s*(")', r"\1,\2", text)
    text = re.sub(r'(\])\s*(")', r"\1,\2", text)
    return text


def _extract_from_fences(text: str) -> dict | None:
    for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text):
        result = _try_parse(block.strip())
        if result:
            return result
        repaired = _repair_json_string(block.strip())
        result = _try_parse(repaired)
        if result:
            return result
    return None


def _extract_json(
    raw: str, chapter_number: int, attempt: int,
) -> dict | None:
    """Full JSON extraction pipeline.  Returns (dict, parse_method)."""
    tag = f"ch{chapter_number}/attempt{attempt + 1}"

    result = _try_parse(raw)
    if result:
        log.info(f"    [{tag}] JSON parsed directly ✓")
        return result

    bracketed = _bracket_extract(raw)
    if bracketed:
        result = _try_parse(bracketed)
        if result:
            log.info(f"    [{tag}] JSON parsed via bracket extraction ✓")
            return result
        repaired = _repair_json_string(bracketed)
        result = _try_parse(repaired)
        if result:
            log.info(f"    [{tag}] JSON parsed via bracket + repair ✓")
            return result

    result = _extract_from_fences(raw)
    if result:
        log.info(f"    [{tag}] JSON parsed from fenced block ✓")
        return result

    repaired_full = _repair_json_string(raw)
    bracketed_full = _bracket_extract(repaired_full)
    if bracketed_full:
        result = _try_parse(bracketed_full)
        if result:
            log.info(f"    [{tag}] JSON parsed via full-text repair ✓")
            return result

    log.warning(f"    [{tag}] all JSON parse strategies failed ✗")
    return None


# ═══════════════════════════════════════════════════════════════════
# Failure logging  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _log_extraction_failure(
    chapter_number: int, attempt: int, raw_output: str,
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = (f"chapter_{chapter_number:03d}"
                f"_attempt{attempt + 1}_{timestamp}.txt")
    path = os.path.join(config.EXTRACTION_FAILURE_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"=== EXTRACTION FAILURE LOG ===\n")
        f.write(f"Chapter  : {chapter_number}\n")
        f.write(f"Attempt  : {attempt + 1}\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"Raw length: {len(raw_output)} chars\n")
        f.write(f"{'=' * 50}\n\n")
        f.write(raw_output)
    return path


# ═══════════════════════════════════════════════════════════════════
# Character name validation  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _is_valid_character_name(name: str) -> tuple[bool, str]:
    if not name or not name.strip():
        return False, "empty name"
    clean = name.strip()
    if len(clean) <= 1:
        return False, "single character, not a name"
    if "," in clean:
        return False, "contains comma (multiple names)"
    if re.search(r"\band\b", clean, re.IGNORECASE):
        return False, "contains 'and' (multiple names)"
    lower = clean.lower()
    words = clean.split()
    for prefix in config.NAME_REJECT_PREFIXES:
        if lower.startswith(prefix):
            return False, f"starts with '{prefix.strip()}'"
    if len(words) > config.NAME_MAX_WORDS:
        return False, f"too many words ({len(words)})"
    if len(words) == 1 and lower in config.NAME_PURE_ROLES:
        return False, "role/rank word, not a name"
    word_set = {w.lower().rstrip("s") for w in words}
    word_set |= {w.lower() for w in words}
    bad = word_set & config.NAME_REJECT_WORDS
    if bad:
        return False, f"contains role/group word: '{bad.pop()}'"
    if len(words) > 1 and clean == clean.lower():
        return False, "all lowercase multi-word (likely description)"
    return True, ""


# ═══════════════════════════════════════════════════════════════════
# Evidence verification — Fix 5: whitespace normalization
# ═══════════════════════════════════════════════════════════════════

def _normalize_whitespace(text: str) -> str:
    """
    Collapse all whitespace (newlines, tabs, multiple spaces)
    into single spaces.  Strip outer quotes and trim.
    This handles dialogue split across lines:
      "I love you,"\\nAkane said.
    becomes:
      "i love you," akane said.
    """
    text = text.lower().strip()
    text = text.strip("\"'""''«»")
    # Replace any whitespace sequence with single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _verify_evidence(
    evidence: str, chapter_text: str,
) -> tuple[bool, str]:
    """
    Verify that evidence appears in the chapter.

    Fix 5: both evidence and chapter are whitespace-normalized
    before comparison.  No fuzzy matching needed for line breaks.

    Returns (verified, method):
      (True,  "exact")  — normalized substring match
      (True,  "fuzzy")  — 75%+ significant words found
      (False, "empty")  — no evidence provided
      (False, "short")  — too short to verify
      (False, "failed") — not found
    """
    if not evidence or not evidence.strip():
        return False, "empty"

    ev = _normalize_whitespace(evidence)
    ct = _normalize_whitespace(chapter_text)

    ev_words = ev.split()
    if len(ev_words) < config.EVIDENCE_MIN_WORDS:
        return False, "short"

    # ── exact substring (post-normalization) ─────────────────────
    if ev in ct:
        return True, "exact"

    # ── fuzzy: word overlap ──────────────────────────────────────
    significant = [w for w in ev_words if len(w) > 2]
    if not significant:
        return False, "short"

    found = sum(1 for w in significant if w in ct)
    ratio = found / len(significant)

    if ratio >= config.EVIDENCE_FUZZY_THRESHOLD:
        return True, "fuzzy"

    return False, "failed"


def _name_in_text(name: str, text_lower: str) -> bool:
    """Fallback: check if name appears in chapter text."""
    if not name:
        return False
    if name.lower() in text_lower:
        return True
    return any(
        part.lower() in text_lower
        for part in name.split()
        if len(part) > 2
    )


# ═══════════════════════════════════════════════════════════════════
# Validation  (unchanged from previous version)
# ═══════════════════════════════════════════════════════════════════

def _validate(data: dict, chapter_number: int) -> bool:
    if not isinstance(data, dict):
        return False

    for key in REQUIRED_KEYS:
        if key not in data:
            if key == "chapter_number":
                data[key] = chapter_number
            elif key in _DICT_KEYS:
                data[key] = {}
            else:
                data[key] = []

    data["chapter_number"] = chapter_number

    for key in _LIST_KEYS:
        if not isinstance(data.get(key), list):
            data[key] = []
    for key in _DICT_KEYS:
        if not isinstance(data.get(key), dict):
            data[key] = {}

    # ── normalize major_events: string → dict ────────────────────
    raw_events = data.get("major_events", [])
    clean_events: list[dict] = []
    for ev in raw_events:
        if isinstance(ev, str) and ev.strip():
            clean_events.append({
                "event": ev.strip(), "evidence": "",
            })
        elif isinstance(ev, dict):
            event_str = str(ev.get("event", "")).strip()
            evidence = str(ev.get("evidence", "")).strip()
            if event_str:
                clean_events.append({
                    "event": event_str, "evidence": evidence,
                })
    data["major_events"] = clean_events

    # ── validate relationship_events ─────────────────────────────
    clean_rel: list[dict] = []
    for entry in data.get("relationship_events", []):
        if not isinstance(entry, dict):
            continue
        chars = entry.get("characters",
                          entry.get("between", []))
        if not (isinstance(chars, list) and len(chars) == 2
                and all(isinstance(c, str) and c.strip()
                        for c in chars)):
            continue
        cleaned: dict = {}
        cleaned["characters"] = [c.strip() for c in chars]
        evt = str(entry.get(
            "event_type", entry.get("type", "")
        )).strip().lower()
        cleaned["event_type"] = evt
        cleaned["description"] = str(
            entry.get("description", "")).strip() or evt
        cleaned["evidence"] = str(
            entry.get("evidence", "")).strip()
        clean_rel.append(cleaned)
    data["relationship_events"] = clean_rel

    # ── validate emotional_deltas ────────────────────────────────
    clean_emo: dict = {}
    raw_emo = data.get("emotional_deltas", {})
    if isinstance(raw_emo, dict):
        for char_name, dims in raw_emo.items():
            if not isinstance(dims, dict):
                continue
            clamped: dict[str, float] = {}
            evidence = str(dims.get("evidence", "")).strip()
            for dim, delta in dims.items():
                if dim == "evidence":
                    continue
                if dim not in config.EMOTIONAL_DIMENSIONS:
                    continue
                try:
                    val = float(delta)
                except (ValueError, TypeError):
                    continue
                clamped[dim] = round(
                    max(-config.MAX_EMOTIONAL_DELTA,
                        min(config.MAX_EMOTIONAL_DELTA, val)), 3)
            if clamped:
                result = dict(clamped)
                if evidence:
                    result["evidence"] = evidence
                clean_emo[str(char_name).strip()] = result
    data["emotional_deltas"] = clean_emo

    # ── validate thread_progression ──────────────────────────────
    clean_tp: list[dict] = []
    for entry in data.get("thread_progression", []):
        if not isinstance(entry, dict):
            continue
        sc = str(entry.get("status_change", "")).strip().lower()
        if sc not in config.VALID_THREAD_STATUSES:
            continue
        entry["status_change"] = sc
        entry["thread_name"] = (
            str(entry.get("thread_name", "")).strip())
        entry["justification"] = (
            str(entry.get("justification", "")).strip())
        if entry["thread_name"]:
            clean_tp.append(entry)
    data["thread_progression"] = clean_tp

    return True


# ═══════════════════════════════════════════════════════════════════
# Hallucination filter — evidence-first  (unchanged logic)
# ═══════════════════════════════════════════════════════════════════

def _filter_hallucinations(
    data: dict, chapter_text: str,
) -> dict:
    text_lower = chapter_text.lower()

    # ── new_characters ───────────────────────────────────────────
    clean: list[dict] = []
    for char in data.get("new_characters", []):
        name = char.get("name", "")
        evidence = char.get("evidence", "")

        valid, reason = _is_valid_character_name(name)
        if not valid:
            log.warning(f"    ✗ rejected character: "
                  f"'{name}' ({reason})")
            continue

        if evidence:
            ok, method = _verify_evidence(evidence, chapter_text)
            if ok:
                if method == "fuzzy":
                    log.info(f"    ~ evidence fuzzy-matched: {name}")
                clean.append(char)
                continue
            else:
                log.warning(f"    ✗ evidence not found for character: "
                      f"'{name}' → \"{evidence[:60]}\"")
                continue

        if _name_in_text(name, text_lower):
            log.warning(f"    ~ no evidence for '{name}', "
                  f"accepted via name-in-text")
            clean.append(char)
        else:
            log.warning(f"    ✗ no evidence, name not in text: "
                  f"'{name}'")

    data["new_characters"] = clean

    # ── character_updates ────────────────────────────────────────
    clean_upd: list[dict] = []
    for upd in data.get("character_updates", []):
        name = upd.get("name", "")
        evidence = upd.get("evidence", "")

        valid, reason = _is_valid_character_name(name)
        if not valid:
            log.warning(f"    ✗ rejected update: "
                  f"'{name}' ({reason})")
            continue

        if evidence:
            ok, method = _verify_evidence(evidence, chapter_text)
            if ok:
                if method == "fuzzy":
                    log.info(f"    ~ update evidence fuzzy-matched: "
                          f"{name}")
                clean_upd.append(upd)
                continue
            else:
                log.warning(f"    ✗ evidence not found for update: "
                      f"'{name}' → \"{evidence[:60]}\"")
                continue

        if _name_in_text(name, text_lower):
            log.warning(f"    ~ no evidence for update '{name}', "
                  f"accepted via name-in-text")
            clean_upd.append(upd)
        else:
            log.warning(f"    ✗ no evidence, name not in text: "
                  f"'{name}'")

    data["character_updates"] = clean_upd

    # ── major_events ─────────────────────────────────────────────
    clean_ev: list[dict] = []
    for ev in data.get("major_events", []):
        event_str = ev.get("event", "")
        evidence = ev.get("evidence", "")

        if evidence:
            ok, method = _verify_evidence(evidence, chapter_text)
            if ok:
                if method == "fuzzy":
                    log.info(f"    ~ event evidence fuzzy-matched: "
                          f"'{event_str[:50]}'")
                clean_ev.append(ev)
            else:
                log.warning(f"    ✗ event evidence not found: "
                      f"'{event_str[:50]}' → "
                      f"\"{evidence[:60]}\"")
        else:
            clean_ev.append(ev)

    data["major_events"] = clean_ev

    # ── relationship_events ──────────────────────────────────────
    clean_rel: list[dict] = []
    for event in data.get("relationship_events", []):
        chars = event.get("characters", [])
        evidence = event.get("evidence", "")

        if len(chars) != 2:
            continue

        v0, r0 = _is_valid_character_name(chars[0])
        v1, r1 = _is_valid_character_name(chars[1])
        if not v0:
            log.warning(f"    ✗ rejected rel name: "
                  f"'{chars[0]}' ({r0})")
            continue
        if not v1:
            log.warning(f"    ✗ rejected rel name: "
                  f"'{chars[1]}' ({r1})")
            continue

        if evidence:
            ok, method = _verify_evidence(evidence, chapter_text)
            if ok:
                if method == "fuzzy":
                    log.info(f"    ~ rel evidence fuzzy-matched: "
                          f"{chars[0]} & {chars[1]}")
                clean_rel.append(event)
                continue
            else:
                log.warning(f"    ✗ rel evidence not found: "
                      f"{chars[0]} & {chars[1]} → "
                      f"\"{evidence[:60]}\"")
                continue

        if (_name_in_text(chars[0], text_lower)
                and _name_in_text(chars[1], text_lower)):
            clean_rel.append(event)
        else:
            log.warning(f"    ✗ no evidence, names not in text: "
                  f"{chars[0]} & {chars[1]}")

    data["relationship_events"] = clean_rel

    # ── emotional_deltas ─────────────────────────────────────────
    clean_emo: dict = {}
    for char, dims in data.get("emotional_deltas", {}).items():
        valid, reason = _is_valid_character_name(char)
        if not valid:
            log.warning(f"    ✗ rejected emo delta: "
                  f"'{char}' ({reason})")
            continue

        evidence = dims.get("evidence", "") if isinstance(
            dims, dict) else ""

        if evidence:
            ok, method = _verify_evidence(evidence, chapter_text)
            if ok:
                if method == "fuzzy":
                    log.info(f"    ~ emo evidence fuzzy-matched: "
                          f"{char}")
                clean_emo[char] = dims
                continue
            else:
                log.warning(f"    ✗ emo evidence not found: "
                      f"'{char}' → \"{evidence[:60]}\"")
                continue

        if _name_in_text(char, text_lower):
            clean_emo[char] = dims
        else:
            log.warning(f"    ✗ no evidence, name not in text: "
                  f"'{char}'")

    data["emotional_deltas"] = clean_emo

    return data


# ═══════════════════════════════════════════════════════════════════
# Public API — Fix 2: skip retry when first attempt succeeds
# ═══════════════════════════════════════════════════════════════════

def extract_chapter(
    chapter_number: int, chapter_text: str,
) -> dict | None:
    words = chapter_text.split()
    if len(words) > config.MAX_CHAPTER_WORDS:
        log.warning(
            f"    ⚠ chapter has {len(words)} words — "
            f"truncating to {config.MAX_CHAPTER_WORDS}")
        chapter_text = " ".join(words[: config.MAX_CHAPTER_WORDS])

    prompt = _build_prompt(chapter_number, chapter_text)

    for attempt in range(2):
        if attempt:
            log.info("    Retrying extraction …")

        raw = ModelLoader.safe_generate(
            config.PHASE1_MODEL_NAME,
            prompt + "\\n\\nReturn ONLY valid JSON. No explanation. Follow the schema exactly.",
            max_tokens=config.PHASE1_MAX_TOKENS,
            temperature=config.PHASE1_TEMPERATURE
        )
        data = _extract_json(raw, chapter_number, attempt)

        if data is None:
            path = _log_extraction_failure(
                chapter_number, attempt, raw)
            log.info(f"    raw output logged → {path}")
            continue

        if not _validate(data, chapter_number):
            log.warning(f"    validation failed (attempt {attempt + 1})")
            path = _log_extraction_failure(
                chapter_number, attempt, raw)
            log.info(f"    raw output logged → {path}")
            continue

        data = _filter_hallucinations(data, chapter_text)

        # ── Fix 2: if we got here, extraction succeeded ──────────
        # No need for a second attempt.
        return data

    log.error(f"    ERROR: extraction failed for chapter {chapter_number}")
    log.error(f"    failure logs in {config.EXTRACTION_FAILURE_DIR}/")
    return None
