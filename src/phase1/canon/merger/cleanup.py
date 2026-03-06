"""
Deterministic merge of per-chapter extractions into story_state.json.

Character identity  : stable non-semantic IDs  (char_NNNN)
Alias matching      : exact → first-name → title/honorific-stripped → word overlap
Relationships       : static dict {char_id → current_status} + timeline events
Emotional deltas    : bounded, no tracker
Thread progression  : status_change per chapter

No model calls — pure dictionary logic.
"""

import json
import os
import re
from datetime import datetime, timezone

from phase1 import config
from phase1.normalizer import normalize_ability, dedupe_abilities
from io_utils import load_json, save_json

# ═══════════════════════════════════════════════════════════════════
# I/O helpers
# ═══════════════════════════════════════════════════════════════════




def _empty_state() -> dict:
    return {
        "characters": {},
        "events": [],
        "plot_threads": {},
        "relationship_events": [],
        "emotional_deltas": {},
        "metadata": {
            "last_updated": None,
            "chapters_processed": [],
        },
    }


def load_canon() -> dict:
    state = _empty_state()
    chars = load_json(config.CHARACTERS_FILE, {})
    abils = load_json(config.ABILITIES_FILE, {})
    rels  = load_json(config.RELATIONSHIPS_FILE, {})
    upds  = load_json(config.UPDATES_FILE, {})

    new_chars = {}
    for cid, c in chars.items():
        base = dict(c)
        base["abilities"] = abils.get(cid, [])
        base["relationships"] = rels.get(cid, {})
        base["updates"] = upds.get(cid, [])
        new_chars[cid] = base

    state["characters"] = new_chars
    return state


def save_canon(state: dict):
    chars_out = {}
    abils_out = {}
    rels_out = {}
    upds_out = {}

    for cid, c in state.get("characters", {}).items():
        chars_out[cid] = {
            "display_name": c.get("display_name"),
            "aliases": c.get("aliases", []),
            "first_appearance": c.get("first_appearance"),
            "status": c.get("status"),
            "description": c.get("description"),
        }
        abils_out[cid] = c.get("abilities", [])
        rels_out[cid] = c.get("relationships", {})
        upds_out[cid] = c.get("updates", [])

    save_json(config.CHARACTERS_FILE, chars_out)
    save_json(config.ABILITIES_FILE, abils_out)
    save_json(config.RELATIONSHIPS_FILE, rels_out)
    save_json(config.UPDATES_FILE, upds_out)



# ═══════════════════════════════════════════════════════════════════
# Conflict logger
# ═══════════════════════════════════════════════════════════════════

def _log(conflict_list: list, *, kind: str, chapter: int, **fields):
    entry = {
        "type": kind,
        "chapter": chapter,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    entry.update(fields)
    conflict_list.append(entry)


# ═══════════════════════════════════════════════════════════════════
# Name normalisation + variant generation  (unchanged)
# ═══════════════════════════════════════════════════════════════════

_TITLE_PREFIXES = {
    "princess", "prince", "lady", "lord", "master",
    "captain", "commander", "konoha", "ninja", "shinobi"
}

_HONORIFIC_SUFFIXES = {
    "-sama", "-kun", "-chan", "-hime", "-sensei", "-senpai", "-dono"
}


def _normalize_name(name: str) -> str:
    name = name.lower().strip()

    # remove hyphen honorifics
    for h in _HONORIFIC_SUFFIXES:
        if name.endswith(h):
            name = name[:-len(h)]

    words = name.split()

    # remove title prefixes
    words = [w for w in words if w not in _TITLE_PREFIXES]

    return " ".join(words)


def _split_name(name: str) -> tuple[str, str | None]:
    parts = name.split()
    if not parts:
        return "", None
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else None
    return first, last


def _same_character(name_a: str, name_b: str) -> bool:
    a = _normalize_name(name_a)
    b = _normalize_name(name_b)

    first_a, last_a = _split_name(a)
    first_b, last_b = _split_name(b)
    
    if not first_a or not first_b:
        return False

    # first name must match
    if first_a != first_b:
        return False

    # if either name is single-word → allow merge
    if last_a is None or last_b is None:
        return True

    # if both have surnames they must match
    return last_a == last_b


# ═══════════════════════════════════════════════════════════════════
# Stable ID generation  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _load_id_counter() -> int:
    data = load_json(config.ID_COUNTER_FILE, {"next_id": 1})
    return data.get("next_id", 1)


def _save_id_counter(next_id: int):
    save_json(config.ID_COUNTER_FILE, {"next_id": next_id})


def _next_char_id(characters: dict) -> str:
    n = _load_id_counter()
    used: set[int] = set()
    for cid in characters:
        m = re.match(r"char_(\d+)$", cid)
        if m:
            used.add(int(m.group(1)))
    while n in used:
        n += 1
    _save_id_counter(n + 1)
    return f"char_{n:04d}"


# ═══════════════════════════════════════════════════════════════════
# Character lookup  (unchanged)
# ═══════════════════════════════════════════════════════════════════

FORCE_SEPARATE = {
    frozenset(["akane yanagi", "kana yanagi"])
}


def _find_character_id(
    name: str, characters: dict,
) -> tuple[str | None, bool]:
    if not name or not name.strip():
        return None, False

    matches: set[str] = set()
    
    for cid, cdata in characters.items():
        all_names = [cdata.get("display_name", "")] + cdata.get("aliases", [])
        
        for known in all_names:
            if not known:
                continue
                
            # Manual override prevention
            pair = frozenset([name.lower().strip(), known.lower().strip()])
            if pair in FORCE_SEPARATE:
                continue
                
            known_norm = _normalize_name(known)
            if not known_norm:
                continue

            # Check if first names match before attempting merge
            first_a, _ = _split_name(_normalize_name(name))
            first_b, _ = _split_name(known_norm)
            
            # The one line that prevents most bugs
            if not first_a or not first_b or first_a != first_b:
                continue

            if _same_character(name, known):
                matches.add(cid)
                break
                
    if len(matches) == 1:
        return matches.pop(), False
    if len(matches) > 1:
        print(f"    ⚠ Ambiguous match for '{name}': {sorted(matches)}")
        return None, True
        
    return None, False


def _resolve_char_id(
    name: str, characters: dict, chapter: int,
) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    cid, ambiguous = _find_character_id(name, characters)
    if cid:
        _add_alias(characters[cid], name)
        return cid
    if ambiguous:
        print(f"    → creating separate entry for "
              f"ambiguous name '{name}'")
    new_id = _next_char_id(characters)
    characters[new_id] = {
        "id": new_id,
        "display_name": name,
        "aliases": [name],
        "first_appearance": chapter,
        "status": "unknown",
        "description": "",
        "abilities": [],
        "relationships": {},
        "updates": [],
    }
    return new_id


# ═══════════════════════════════════════════════════════════════════
# Alias management  (unchanged)
# ═══════════════════════════════════════════════════════════════════


def dedupe(items):
    return list(dict.fromkeys(items))

def _dedupe_list(items):
    seen = set()
    result = []
    for i in items:
        key = i.lower()
        if key not in seen:
            seen.add(key)
            result.append(i)
    return result

def _add_alias(entry: dict, name: str) -> bool:
    name_lower = name.lower().strip()
    for existing in entry.get("aliases", []):
        if existing.lower().strip() == name_lower:
            return False
    entry.setdefault("aliases", []).append(name.strip())
    return True


# ═══════════════════════════════════════════════════════════════════
# Format detection
# ═══════════════════════════════════════════════════════════════════

def _is_stable_format(characters: dict) -> bool:
    if not characters:
        return True
    return all(re.match(r"char_\d+$", k) for k in characters)


def _ensure_display_name_format(state: dict) -> None:
    chars = state.get("characters", {})
    if not chars:
        return
    sample = next(iter(chars.values()), None)
    if sample and "display_name" in sample:
        return
    new_chars: dict[str, dict] = {}
    for name, cdata in chars.items():
        temp_id = re.sub(
            r"[^a-z0-9]+", "_",
            " ".join(name.lower().strip().split()))
        temp_id = re.sub(r"_+", "_", temp_id).strip("_") or "unknown"
        while temp_id in new_chars:
            temp_id += "_dup"
        entry = dict(cdata)
        entry["canonical_id"] = temp_id
        entry["display_name"] = name
        entry["aliases"] = [name]
        new_chars[temp_id] = entry
    state["characters"] = new_chars
    print(f"    ↻ converted {len(new_chars)} character(s) to "
          f"display_name format")


# ═══════════════════════════════════════════════════════════════════
# Relationship classification
# ═══════════════════════════════════════════════════════════════════

def _classify_label_to_type(label: str) -> str | None:
    """
    Classify a freeform label to a static REL_TYPE.
    Returns the type string or None if not a static type.
    """
    lower = label.lower().strip()
    if not lower:
        return None

    # Direct match
    if lower in config.REL_TYPES:
        return lower

    # Known label mapping
    if lower in config.REL_LABEL_TO_TYPE:
        return config.REL_LABEL_TO_TYPE[lower]

    # Keyword fallback
    _kw = {
        "family": [
            "father", "mother", "brother", "sister",
            "son", "daughter", "parent", "sibling",
            "uncle", "aunt", "cousin", "clan",
            "grandfather", "grandmother",
        ],
        "romantic": [
            "romantic", "love", "fiance", "spouse",
            "wife", "husband", "girlfriend", "boyfriend",
        ],
        "mentor": ["sensei", "teacher", "instructor", "trainer"],
        "student": ["student", "apprentice", "pupil", "disciple"],
        "enemy": ["enemy", "nemesis", "foe", "antagonist"],
        "rival": ["rival", "competitor"],
        "friend": ["friend", "friendship"],
    }
    for rel_type, keywords in _kw.items():
        if any(kw in lower for kw in keywords):
            return rel_type

    return None


def _classify_label_to_event(label: str) -> str:
    """
    Classify a freeform label to a REL_EVENT_TYPE.
    Always returns a valid event type (defaults to "cooperation").
    """
    lower = label.lower().strip()
    if not lower:
        return "cooperation"

    # Direct match
    if lower in config.REL_EVENT_TYPES:
        return lower

    # Keyword classification (ordered: specific → general)
    _kw = {
        "kiss": ["kiss"],
        "confession": ["confess", "confession", "admit feeling",
                        "declare"],
        "romantic_progression": [
            "romantic", "love", "affection", "intimate",
            "dating", "courting",
        ],
        "betrayal": ["betray", "traitor", "backstab", "deceiv"],
        "argument": [
            "argument", "fight", "confront", "conflict",
            "disagree", "clash", "tension", "dispute",
        ],
        "alliance": ["alliance", "allied", "unite"],
        "trust_gain": ["trust", "bond", "respect", "faith"],
        "trust_loss": ["distrust", "suspicion", "doubt",
                       "lost trust"],
        "met": ["met", "meet", "encounter", "introduc"],
        "cooperation": [
            "work", "cooperat", "collaborat", "mission",
            "plan", "together", "team", "help",
        ],
    }
    for event_type, keywords in _kw.items():
        if any(kw in lower for kw in keywords):
            return event_type

    return "cooperation"


# ═══════════════════════════════════════════════════════════════════
# Relationship repetition system
# ═══════════════════════════════════════════════════════════════════

def _ensure_rel_entry(characters: dict, from_cid: str, to_cid: str) -> dict | None:
    """
    Get or create the relationship record from from_cid → to_cid.
    Uses the new {state, history, signals} format.
    Returns the rel dict, or None if from_cid doesn't exist.
    """
    if from_cid not in characters:
        return None
    cdata = characters[from_cid]
    rels = cdata.setdefault("relationships", {})
    if not isinstance(rels, dict):
        rels = {}
        cdata["relationships"] = rels

    if to_cid not in rels:
        rels[to_cid] = {
            "state": "neutral",
            "history": [],
            "signals": {},
        }
    else:
        # Migrate old {current_status, since_chapter} format on the fly
        entry = rels[to_cid]
        if "current_status" in entry and "signals" not in entry:
            rels[to_cid] = {
                "state": entry.get("current_status", "neutral"),
                "history": [],
                "signals": {},
            }

    return rels[to_cid]


def _compute_rel_state(signals: dict, history: list) -> str:
    """
    Derive relationship state from accumulated signals.
    Applies threshold rules in priority order.
    Returns 'neutral' if no threshold is met.
    """
    total_interactions = len(history)
    if total_interactions < config.REL_MIN_INTERACTIONS:
        return "neutral"

    for event_type, (threshold, resulting_state) in config.REL_SIGNAL_THRESHOLDS.items():
        if signals.get(event_type, 0) >= threshold:
            return resulting_state

    return "neutral"


def _record_rel_event(
    characters: dict,
    from_cid: str,
    to_cid: str,
    event_type: str,
    chapter: int,
) -> None:
    """
    Record a relationship event, update signal counts, and re-derive state.
    Both directions are updated (from→to and to→from).
    """
    for a, b in [(from_cid, to_cid), (to_cid, from_cid)]:
        entry = _ensure_rel_entry(characters, a, b)
        if entry is None:
            continue

        entry["history"].append({"chapter": chapter, "event": event_type})
        entry["signals"][event_type] = entry["signals"].get(event_type, 0) + 1
        entry["state"] = _compute_rel_state(entry["signals"], entry["history"])


def _set_static_relationship(
    characters: dict,
    from_cid: str,
    to_cid: str,
    rel_type: str,
    chapter: int,
) -> None:
    """Set a static relationship with priority-based upgrades.

    Rules:
      - Family is permanent (never overwritten except by family)
      - Enemy (betrayal) always applies
      - Otherwise only upgrade (higher priority replaces lower)
    """
    if from_cid not in characters:
        return

    cdata = characters[from_cid]
    rels = cdata.get("relationships", {})
    if not isinstance(rels, dict):
        rels = {}
        cdata["relationships"] = rels

    existing = rels.get(to_cid)
    if existing:
        old_type = existing.get("current_status", "")
        old_pri = config.REL_PRIORITY.get(old_type, 0)
        new_pri = config.REL_PRIORITY.get(rel_type, 0)

        # Family is permanent
        if old_type == "family" and rel_type != "family":
            return

        # Enemy (betrayal) always applies
        if rel_type == "enemy":
            pass

        # Otherwise only upgrade
        elif new_pri <= old_pri:
            return

    rels[to_cid] = {
        "current_status": rel_type,
        "since_chapter": chapter,
    }


# ═══════════════════════════════════════════════════════════════════
# Relationship format migration
# ═══════════════════════════════════════════════════════════════════

def _needs_relationship_migration(state: dict) -> bool:
    """Detect old-format relationships or events."""
    for cdata in state.get("characters", {}).values():
        if isinstance(cdata.get("relationships"), list):
            return True
    for e in state.get("relationship_events", []):
        if "between" in e and "characters" not in e:
            return True
    return False


def _migrate_relationship_format(state: dict) -> bool:
    """
    One-time migration:
    1. Character relationships: list → dict with controlled types
    2. relationship_events: old {between, type} → new {characters, event_type}
    3. Non-REL_TYPE labels → converted to events
    """
    if not _needs_relationship_migration(state):
        return False

    migrated_chars = 0
    migrated_events = 0

    # ── 1. Migrate character relationship lists ──────────────────
    for cid, cdata in state.get("characters", {}).items():
        rels = cdata.get("relationships", {})
        if not isinstance(rels, list):
            continue

        new_rels: dict[str, dict] = {}
        first_ch = cdata.get("first_appearance", 1)

        for r in rels:
            target = r.get("character", "")
            label = r.get("relationship", "")
            if not target:
                continue

            rel_type = _classify_label_to_type(label)

            if rel_type:
                # Known static type → store
                new_rels[target] = {
                    "current_status": rel_type,
                    "since_chapter": first_ch,
                }
            else:
                # Unknown label → convert to timeline event
                event_type = _classify_label_to_event(label)
                event = {
                    "chapter": first_ch,
                    "characters": sorted([cid, target]),
                    "event_type": event_type,
                    "description": label,
                }
                if not _relationship_event_exists(state, event):
                    state["relationship_events"].append(event)
                    print(f"    ⚠ '{label}' ({cid}→{target}) "
                          f"converted to event '{event_type}'")

        cdata["relationships"] = new_rels
        migrated_chars += 1

    # ── 2. Migrate old-format relationship_events ────────────────
    old_events = state.get("relationship_events", [])
    new_events: list[dict] = []

    for e in old_events:
        if "between" in e and "characters" not in e:
            new_event = {
                "chapter": e.get("chapter", 0),
                "characters": sorted(e.get("between", [])),
                "event_type": _classify_label_to_event(
                    e.get("type", "")),
                "description": e.get("type", ""),
            }
            new_events.append(new_event)
            migrated_events += 1
        elif "characters" in e:
            # Already new format — keep as-is
            new_events.append(e)
        else:
            new_events.append(e)

    state["relationship_events"] = new_events

    if migrated_chars or migrated_events:
        print(f"    ↻ migrated relationships: "
              f"{migrated_chars} character(s), "
              f"{migrated_events} event(s)")

    return True


# ═══════════════════════════════════════════════════════════════════
# Status sets
# ═══════════════════════════════════════════════════════════════════

_DEAD_STATUSES = {"dead", "deceased", "killed"}
_ALIVE_STATUSES = {
    "alive", "active", "injured", "wounded",
    "recovering", "healthy",
}

_STATUS_PRIORITY = {
    "alive": 6, "active": 5, "healthy": 5,
    "injured": 4, "wounded": 4, "recovering": 4,
    "unknown": 2,
    "dead": 1, "deceased": 1, "killed": 1,
}


# ═══════════════════════════════════════════════════════════════════
# Relationship event dedup
# ═══════════════════════════════════════════════════════════════════

def _relationship_event_exists(state: dict, event: dict) -> bool:
    """Dedup: same chapter + characters + event_type."""
    new_chars = event.get("characters",
                          event.get("between", []))
    new_evt = event.get("event_type",
                        event.get("type", ""))

    for e in state.get("relationship_events", []):
        e_chars = e.get("characters", e.get("between", []))
        e_evt = e.get("event_type", e.get("type", ""))
        if (e.get("chapter") == event.get("chapter")
                and e_chars == new_chars
                and e_evt == new_evt):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════
# Merge: new characters
# ═══════════════════════════════════════════════════════════════════

def _merge_new_characters(
    state: dict, extraction: dict, conflicts: list,
):
    chapter = extraction["chapter_number"]
    chars = state["characters"]

    for char in extraction.get("new_characters", []):
        name = (char.get("name") or "").strip()
        if not name:
            continue

        cid, ambiguous = _find_character_id(name, chars)

        if cid:
            entry = chars[cid]
            added = _add_alias(entry, name)
            if added:
                print(f"    + alias '{name}' → {cid} "
                      f"({entry.get('display_name', '')})")
            entry["updates"].append({
                "chapter": chapter,
                "detail": (f"Re-introduced as '{name}': "
                           f"{char.get('description', '')}"),
            })
        else:
            if ambiguous:
                print(f"    → creating separate entry for "
                      f"ambiguous name '{name}'")
            new_id = _next_char_id(chars)

            # Process relationships through classification
            pending_static: list[tuple[str, str]] = []
            for rel in char.get("relationships") or []:
                rc = (rel.get("character") or "").strip()
                label = (rel.get("relationship") or "").strip()
                if not rc:
                    continue
                target_id = _resolve_char_id(rc, chars, chapter)

                rel_type = _classify_label_to_type(label)
                if rel_type:
                    # Explicit static type (family, mentor, etc.) — record directly
                    pending_static.append((target_id, rel_type))
                elif label:
                    # Dynamic/unknown label → log as event for signal tracking
                    event_type = _classify_label_to_event(label)
                    event = {
                        "chapter": chapter,
                        "characters": sorted([new_id, target_id]),
                        "event_type": event_type,
                        "description": label,
                    }
                    if not _relationship_event_exists(state, event):
                        state["relationship_events"].append(event)
                        print(f"    ⚠ Unknown relationship label "
                              f"'{label}' converted to event "
                              f"'{event_type}'")

            chars[new_id] = {
                "id": new_id,
                "display_name": name,
                "aliases": [name],
                "first_appearance": chapter,
                "status": char.get("status", "unknown"),
                "description": char.get("description", ""),
                "abilities": dedupe(char.get("abilities") or []),
                "relationships": {},
                "updates": [{
                    "chapter": chapter,
                    "detail": (f"First appearance: "
                               f"{char.get('description', '')}"),
                }],
            }

            # Apply static relationships (character now exists in chars)
            for target_id, rel_type in pending_static:
                _set_static_relationship(chars, new_id, target_id, rel_type, chapter)


# ═══════════════════════════════════════════════════════════════════
# Merge: character updates
# ═══════════════════════════════════════════════════════════════════

def _merge_character_updates(
    state: dict, extraction: dict, conflicts: list,
):
    chapter = extraction["chapter_number"]
    chars = state["characters"]

    for upd in extraction.get("character_updates", []):
        name = (upd.get("name") or "").strip()
        if not name:
            continue

        cid = _resolve_char_id(name, chars, chapter)
        cs = chars[cid]
        _add_alias(cs, name)

        # Ensure relationships is a dict
        if not isinstance(cs.get("relationships"), dict):
            cs["relationships"] = {}

        # ── status contradiction check (dead→alive only) ─────────
        new_status = (upd.get("status") or "").strip().lower()
        if new_status:
            old_status = (
                cs.get("status") or "unknown").strip().lower()
            if (old_status in _DEAD_STATUSES
                    and new_status in _ALIVE_STATUSES):
                _log(
                    conflicts,
                    kind="status_contradiction",
                    chapter=chapter,
                    character=cs["display_name"],
                    character_id=cid,
                    old_status=old_status,
                    new_status=new_status,
                    detail=(
                        f"'{cs['display_name']}' ({cid}) was "
                        f"'{old_status}' but appears as "
                        f"'{new_status}' in ch {chapter}"
                    ),
                )
            cs["status"] = new_status

        # ── abilities (normalised dedup) ─────────────────────────
        new_abilities = upd.get("new_abilities") or []
        if new_abilities:
            for ability in new_abilities:
                if not ability:
                    continue
                cs["abilities"].append(ability)
            cs["abilities"] = dedupe(cs["abilities"])

        # ── new relationships → classify and route ───────────────
        for rel in upd.get("new_relationships") or []:
            rc = (rel.get("character") or "").strip()
            label = (rel.get("relationship") or "").strip()
            if not rc or not label:
                continue
            rel_cid = _resolve_char_id(rc, chars, chapter)

            rel_type = _classify_label_to_type(label)

            if rel_type:
                # Explicitly-stated static relationship (family, mentor, etc.)
                _set_static_relationship(chars, cid, rel_cid, rel_type, chapter)
            else:
                # Dynamic/unknown label → log as event, let repetition derive state
                event_type = _classify_label_to_event(label)
                event = {
                    "chapter": chapter,
                    "characters": sorted([cid, rel_cid]),
                    "event_type": event_type,
                    "description": label,
                }
                if not _relationship_event_exists(state, event):
                    state["relationship_events"].append(event)
                    print(f"    ⚠ Unknown relationship label "
                          f"'{label}' converted to event "
                          f"'{event_type}'")
                _record_rel_event(chars, cid, rel_cid, event_type, chapter)

        # ── update record ────────────────────────────────────────
        detail = (upd.get("detail") or "").strip()
        if detail:
            cs["updates"].append({
                "chapter": chapter, "detail": detail,
            })


# ═══════════════════════════════════════════════════════════════════
# Merge: events  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _merge_events(
    state: dict, extraction: dict, conflicts: list,
):
    """Handle both old string format and new dict-with-evidence format."""
    chapter = extraction["chapter_number"]
    for ev in extraction.get("major_events", []):
        event_str = ""
        evidence = ""

        if isinstance(ev, str):
            event_str = ev.strip()
        elif isinstance(ev, dict):
            event_str = str(ev.get("event", "")).strip()
            evidence = str(ev.get("evidence", "")).strip()

        if not event_str:
            continue

        entry: dict = {"chapter": chapter, "event": event_str}
        if evidence:
            entry["evidence"] = evidence

        state["events"].append(entry)


# ═══════════════════════════════════════════════════════════════════
# Thread name matching  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _find_thread_name(name: str, threads: dict) -> str | None:
    if name in threads:
        return name
    name_lower = name.lower().strip()
    for tname in threads:
        if tname.lower().strip() == name_lower:
            return tname
    name_words = {w.lower() for w in name.split() if len(w) > 3}
    if name_words:
        best: str | None = None
        best_overlap = 0
        for tname in threads:
            twords = {w.lower() for w in tname.split()
                      if len(w) > 3}
            overlap = len(name_words & twords)
            if overlap > best_overlap:
                best_overlap = overlap
                best = tname
        if best is not None and best_overlap > 0:
            return best
    return None


# ═══════════════════════════════════════════════════════════════════
# Merge: new plot threads  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _merge_new_threads(
    state: dict, extraction: dict, conflicts: list,
):
    chapter = extraction["chapter_number"]
    for thread in extraction.get("new_plot_threads", []):
        tname = (thread.get("name") or "").strip()
        if not tname:
            continue
        existing = _find_thread_name(tname, state["plot_threads"])
        if existing:
            tdata = state["plot_threads"][existing]
            if tdata["status"] == "resolved":
                _log(
                    conflicts,
                    kind="resolved_thread_reappears",
                    chapter=chapter,
                    thread=existing,
                    detail=(f"Thread '{existing}' was resolved but "
                            f"reappears in chapter {chapter}"),
                )
                tdata["status"] = "reopened"
            tdata["updates"].append({
                "chapter": chapter,
                "detail": thread.get("description", ""),
            })
        else:
            state["plot_threads"][tname] = {
                "introduced": chapter,
                "status": "unresolved",
                "description": thread.get("description", ""),
                "updates": [{
                    "chapter": chapter,
                    "detail": thread.get("description", ""),
                }],
            }


# ═══════════════════════════════════════════════════════════════════
# Merge: resolved plot threads  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _merge_resolved_threads(
    state: dict, extraction: dict, conflicts: list,
):
    chapter = extraction["chapter_number"]
    for tname in extraction.get("resolved_plot_threads", []):
        tname = (tname or "").strip()
        if not tname:
            continue
        existing = _find_thread_name(tname, state["plot_threads"])
        if existing:
            state["plot_threads"][existing]["status"] = "resolved"
            state["plot_threads"][existing]["updates"].append(
                {"chapter": chapter, "detail": "Resolved"})
        else:
            state["plot_threads"][tname] = {
                "introduced": chapter,
                "status": "resolved",
                "description": "(resolved; no prior tracking)",
                "updates": [{
                    "chapter": chapter, "detail": "Resolved",
                }],
            }


# ═══════════════════════════════════════════════════════════════════
# Merge: relationship events (timeline)
# ═══════════════════════════════════════════════════════════════════

def _merge_relationship_events(
    state: dict, extraction: dict, conflicts: list,
):
    chapter = extraction["chapter_number"]
    chars = state["characters"]

    for raw in extraction.get("relationship_events", []):
        char_names = raw.get("characters", [])
        if len(char_names) != 2:
            continue

        resolved: list[str] = []
        for name in char_names:
            name = (name or "").strip()
            if not name:
                break
            resolved.append(_resolve_char_id(name, chars, chapter))
        if len(resolved) != 2:
            continue

        raw_evt = raw.get("event_type", "")
        event_type = _classify_label_to_event(str(raw_evt))

        description = raw.get("description", "") or str(raw_evt)

        event: dict = {
            "chapter": chapter,
            "characters": sorted(resolved),
            "event_type": event_type,
            "description": description,
        }

        # Preserve evidence if present
        evidence = raw.get("evidence", "")
        if evidence:
            event["evidence"] = evidence

        if _relationship_event_exists(state, event):
            continue

        state["relationship_events"].append(event)

        # Record the event and let the repetition system derive state
        _record_rel_event(chars, resolved[0], resolved[1], event_type, chapter)



# ═══════════════════════════════════════════════════════════════════
# Merge: emotional deltas  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _merge_emotional_deltas(
    state: dict, extraction: dict, conflicts: list,
):
    chapter = extraction["chapter_number"]
    raw_deltas = extraction.get("emotional_deltas", {})
    chars = state["characters"]

    for name, dims in raw_deltas.items():
        name = (name or "").strip()
        if not name or not isinstance(dims, dict):
            continue

        cid = _resolve_char_id(name, chars, chapter)

        # Separate evidence from dimension data
        evidence = str(dims.get("evidence", "")).strip()

        clamped: dict[str, float] = {}
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

        if not clamped:
            continue

        if cid not in state["emotional_deltas"]:
            state["emotional_deltas"][cid] = []
        state["emotional_deltas"][cid] = [
            e for e in state["emotional_deltas"][cid]
            if e.get("chapter") != chapter
        ]

        entry: dict = {"chapter": chapter, "deltas": clamped}
        if evidence:
            entry["evidence"] = evidence

        state["emotional_deltas"][cid].append(entry)


# ═══════════════════════════════════════════════════════════════════
# Merge: thread progression  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def _merge_thread_progression(
    state: dict, extraction: dict, conflicts: list,
):
    chapter = extraction["chapter_number"]
    for prog in extraction.get("thread_progression", []):
        tname = (prog.get("thread_name") or "").strip()
        status_change = (
            prog.get("status_change") or "").strip().lower()
        justification = (
            prog.get("justification") or "").strip()
        if (not tname
                or status_change not in config.VALID_THREAD_STATUSES):
            continue
        existing = _find_thread_name(tname, state["plot_threads"])
        if existing is None:
            state["plot_threads"][tname] = {
                "introduced": chapter,
                "status": "unresolved",
                "description": justification,
                "updates": [],
            }
            existing = tname
        thread = state["plot_threads"][existing]
        already = any(
            u.get("chapter") == chapter
            and u.get("status_change") == status_change
            for u in thread.get("updates", [])
        )
        if already:
            continue
        thread["updates"].append({
            "chapter": chapter,
            "detail": justification,
            "status_change": status_change,
            "justification": justification,
        })
        if status_change == "resolved":
            if thread["status"] == "resolved":
                _log(
                    conflicts,
                    kind="thread_already_resolved",
                    chapter=chapter,
                    thread=existing,
                    detail=(f"Thread '{existing}' marked resolved "
                            f"again in chapter {chapter}"),
                )
            thread["status"] = "resolved"


# ═══════════════════════════════════════════════════════════════════
# Purge chapter data  (updated for new relationship_events format)
# ═══════════════════════════════════════════════════════════════════

def purge_chapter(chapter: int) -> None:
    if not os.path.exists(config.STORY_STATE_FILE):
        return

    state = _load(config.STORY_STATE_FILE, _empty_state())
    for key, default in _empty_state().items():
        state.setdefault(key, default)

    state["events"] = [
        e for e in state.get("events", [])
        if e.get("chapter") != chapter
    ]

    for cdata in state.get("characters", {}).values():
        cdata["updates"] = [
            u for u in cdata.get("updates", [])
            if u.get("chapter") != chapter
        ]

    state["relationship_events"] = [
        e for e in state.get("relationship_events", [])
        if e.get("chapter") != chapter
    ]

    for cid in list(state.get("emotional_deltas", {})):
        state["emotional_deltas"][cid] = [
            e for e in state["emotional_deltas"][cid]
            if e.get("chapter") != chapter
        ]
        if not state["emotional_deltas"][cid]:
            del state["emotional_deltas"][cid]

    for tdata in state.get("plot_threads", {}).values():
        tdata["updates"] = [
            u for u in tdata.get("updates", [])
            if u.get("chapter") != chapter
        ]
        if tdata.get("status") == "resolved":
            still_resolved = any(
                u.get("status_change") == "resolved"
                or "resolved" in (u.get("detail") or "").lower()
                for u in tdata.get("updates", [])
            )
            if not still_resolved:
                tdata["status"] = "unresolved"

    processed = state.get("metadata", {}).get(
        "chapters_processed", [])
    if chapter in processed:
        processed.remove(chapter)

    _save(config.STORY_STATE_FILE, state)
    print(f"    ↻ purged chapter {chapter} data from story_state")


# ═══════════════════════════════════════════════════════════════════
# Purge specific characters  (updated for dict relationships)
# ═══════════════════════════════════════════════════════════════════

def purge_characters(char_ids: list[str]) -> dict:
    state = _load(config.STORY_STATE_FILE, _empty_state())
    for key, default in _empty_state().items():
        state.setdefault(key, default)

    id_set = set(char_ids)
    removed: list[str] = []
    not_found: list[str] = []

    for cid in char_ids:
        if cid in state["characters"]:
            name = state["characters"][cid].get(
                "display_name", cid)
            del state["characters"][cid]
            removed.append(f"{cid} ({name})")
        else:
            not_found.append(cid)

    # Clean emotional_deltas
    for cid in id_set:
        state.get("emotional_deltas", {}).pop(cid, None)

    # Clean relationship_events (both formats)
    before_re = len(state.get("relationship_events", []))
    state["relationship_events"] = [
        e for e in state.get("relationship_events", [])
        if not (set(e.get("characters",
                          e.get("between", []))) & id_set)
    ]
    after_re = len(state["relationship_events"])

    # Clean character relationship dicts/lists
    for cdata in state.get("characters", {}).values():
        rels = cdata.get("relationships", {})
        if isinstance(rels, dict):
            for purged_id in id_set:
                rels.pop(purged_id, None)
        elif isinstance(rels, list):
            cdata["relationships"] = [
                r for r in rels
                if r.get("character") not in id_set
            ]

    _save(config.STORY_STATE_FILE, state)

    return {
        "removed": removed,
        "not_found": not_found,
        "relationship_events_cleaned": before_re - after_re,
        "remaining_characters": len(state["characters"]),
    }


# ═══════════════════════════════════════════════════════════════════
# Auto-cleanup  (unchanged logic, updated for new format)
# ═══════════════════════════════════════════════════════════════════

def auto_cleanup() -> dict:
    state = _load(config.STORY_STATE_FILE, _empty_state())
    for key, default in _empty_state().items():
        state.setdefault(key, default)

    invalid_ids: list[str] = []
    reasons: list[str] = []

    for cid, cdata in state.get("characters", {}).items():
        name = cdata.get("display_name", "")
        valid, reason = _validate_character_name(name)
        if not valid:
            invalid_ids.append(cid)
            reasons.append(
                f"  ✗ {cid:<12} \"{name}\"  — {reason}")

    conflicts_cleaned = clean_conflict_log(
        ["relationship_contradiction"])

    if not invalid_ids and conflicts_cleaned == 0:
        print("  No invalid entries found.")
        return {
            "removed": [],
            "remaining": len(state.get("characters", {})),
            "conflicts_cleaned": 0,
        }

    if reasons:
        print("\n  Invalid character entries found:\n")
        for r in reasons:
            print(r)
        print()

    result = {}
    if invalid_ids:
        result = purge_characters(invalid_ids)
    else:
        result = {
            "removed": [],
            "remaining_characters": len(
                state.get("characters", {})),
        }
    result["conflicts_cleaned"] = conflicts_cleaned
    return result


def _validate_character_name(name: str) -> tuple[bool, str]:
    if not name or not name.strip():
        return False, "empty name"
    clean = name.strip()
    if len(clean) <= 1:
        return False, "single character"
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
# Conflict log cleanup  (unchanged)
# ═══════════════════════════════════════════════════════════════════

def clean_conflict_log(
    types_to_remove: list[str] | None = None,
) -> int:
    if types_to_remove is None:
        types_to_remove = ["relationship_contradiction"]
    remove_set = set(types_to_remove)
    conflicts = _load(config.CONFLICT_LOG_FILE, [])
    if not isinstance(conflicts, list):
        return 0
    before = len(conflicts)
    cleaned = [
        c for c in conflicts
        if c.get("type") not in remove_set
    ]
    after = len(cleaned)
    removed = before - after
    if removed > 0:
        _save(config.CONFLICT_LOG_FILE, cleaned)
        print(f"    ↻ removed {removed} stale conflict entries")
    return removed


# ═══════════════════════════════════════════════════════════════════
# Migration: stable IDs  (updated for dict relationships)
# ═══════════════════════════════════════════════════════════════════

_MERGE_GROUPS = [
    {
        "old_ids": {
            "akane", "akane_uzumaki", "akane_yanagi",
            "akane_yanagi_uzumaki",
        },
        "display_name": "Akane Yanagi/Uzumaki",
        "extra_aliases": [],
    },
    {
        "old_ids": {
            "kaguya", "kaguya_otsutsuki", "princess_kaguya",
        },
        "display_name": "Kaguya Otsutsuki",
        "extra_aliases": ["Rabbit Goddess"],
    },
]


def _merge_entries(
    entries: list[dict],
    display_name: str,
    extra_aliases: list[str],
) -> dict:
    first_app = min(
        e.get("first_appearance", 999_999) for e in entries)

    best_status = "unknown"
    best_pri = 0
    for e in entries:
        s = (e.get("status") or "unknown").lower()
        p = _STATUS_PRIORITY.get(s, 0)
        if p > best_pri:
            best_pri = p
            best_status = s

    best_desc = max(
        (e.get("description") or "" for e in entries),
        key=len, default="")

    abilities: list[str] = []
    seen_ab: set[str] = set()
    for e in entries:
        for a in e.get("abilities", []):
            key = a.lower().strip()
            if key and key not in seen_ab:
                seen_ab.add(key)
                abilities.append(a)

    aliases: list[str] = []
    seen_al: set[str] = set()
    for e in entries:
        for a in ([e.get("display_name", "")]
                  + e.get("aliases", [])):
            norm = _normalize_name(a)
            if norm and norm not in seen_al:
                seen_al.add(norm)
                aliases.append(a.strip())
    for a in extra_aliases:
        norm = _normalize_name(a)
        if norm and norm not in seen_al:
            seen_al.add(norm)
            aliases.append(a)
    dn_norm = _normalize_name(display_name)
    if dn_norm and dn_norm not in seen_al:
        aliases.append(display_name)

    # Merge relationships (handle both old list and new dict)
    merged_rels: dict[str, dict] = {}
    for e in entries:
        rels = e.get("relationships", {})
        if isinstance(rels, dict):
            for target, rdata in rels.items():
                if target not in merged_rels:
                    merged_rels[target] = rdata
        elif isinstance(rels, list):
            for r in rels:
                target = r.get("character", "")
                label = r.get("relationship", "")
                if target and target not in merged_rels:
                    rt = _classify_label_to_type(label)
                    merged_rels[target] = {
                        "current_status": rt or "ally",
                        "since_chapter": e.get(
                            "first_appearance", 1),
                    }

    updates: list[dict] = []
    for e in entries:
        updates.extend(e.get("updates", []))
    updates.sort(key=lambda u: u.get("chapter", 0))

    return {
        "display_name": display_name,
        "aliases": aliases,
        "first_appearance": first_app,
        "status": best_status,
        "description": best_desc,
        "abilities": abilities,
        "relationships": merged_rels,
        "updates": updates,
    }


def _update_references(
    state: dict, mapping: dict[str, str],
) -> int:
    count = 0

    # Character relationship dicts/lists
    for cdata in state.get("characters", {}).values():
        rels = cdata.get("relationships", {})
        if isinstance(rels, dict):
            new_rels: dict[str, dict] = {}
            for target, rdata in rels.items():
                new_target = mapping.get(target, target)
                if new_target != target:
                    count += 1
                new_rels[new_target] = rdata
            cdata["relationships"] = new_rels
        elif isinstance(rels, list):
            for rel in rels:
                old = rel.get("character", "")
                if old in mapping:
                    rel["character"] = mapping[old]
                    count += 1

    # relationship_events (both formats)
    for event in state.get("relationship_events", []):
        chars_key = ("characters" if "characters" in event
                     else "between")
        new_chars = []
        for ref in event.get(chars_key, []):
            if ref in mapping:
                new_chars.append(mapping[ref])
                count += 1
            elif re.match(r"char_\d+$", ref):
                new_chars.append(ref)
            else:
                found, _ = _find_character_id(
                    ref, state["characters"])
                if found:
                    new_chars.append(found)
                    count += 1
                else:
                    new_chars.append(ref)
        event["characters"] = sorted(new_chars)
        event.pop("between", None)

    # emotional_deltas
    old_emo = dict(state.get("emotional_deltas", {}))
    new_emo: dict[str, list] = {}
    for old_key, entries in old_emo.items():
        new_key = mapping.get(old_key, old_key)
        if new_key != old_key:
            count += 1
        if new_key not in new_emo:
            new_emo[new_key] = []
        new_emo[new_key].extend(entries)
    for key in new_emo:
        by_ch: dict[int, dict] = {}
        for entry in new_emo[key]:
            ch = entry.get("chapter", 0)
            if ch not in by_ch:
                by_ch[ch] = entry
        new_emo[key] = sorted(
            by_ch.values(), key=lambda e: e.get("chapter", 0))
    state["emotional_deltas"] = new_emo

    return count


def migrate_to_stable_ids() -> dict | None:
    if not os.path.exists(config.STORY_STATE_FILE):
        print("No story_state.json found.")
        return None

    state = load_canon()
    for key, default in _empty_state().items():
        state.setdefault(key, default)

    chars = state.get("characters", {})
    if _is_stable_format(chars):
        print("Characters already use stable IDs.")
        return None

    _ensure_display_name_format(state)
    chars = state["characters"]
    count_before = len(chars)

    id_mapping: dict[str, str] = {}
    new_chars: dict[str, dict] = {}
    next_num = 1
    merge_log: list[str] = []

    for group in _MERGE_GROUPS:
        found_ids = [
            oid for oid in group["old_ids"] if oid in chars]
        if not found_ids:
            continue
        new_id = f"char_{next_num:04d}"
        next_num += 1
        found_entries = [chars[oid] for oid in found_ids]
        merged = _merge_entries(
            found_entries,
            group["display_name"],
            group.get("extra_aliases", []),
        )
        merged["id"] = new_id
        new_chars[new_id] = merged
        for oid in found_ids:
            id_mapping[oid] = new_id
        merge_log.append(
            f"  MERGED {found_ids} → {new_id}  "
            f"\"{group['display_name']}\"")

    for old_id in sorted(chars):
        if old_id in id_mapping:
            continue
        new_id = f"char_{next_num:04d}"
        next_num += 1
        entry = dict(chars[old_id])
        entry.pop("canonical_id", None)
        entry["id"] = new_id
        entry.setdefault("aliases", [])
        dn = entry.get("display_name", "")
        if dn:
            _add_alias(entry, dn)
        # Ensure relationships is a dict
        if isinstance(entry.get("relationships"), list):
            old_rels = entry["relationships"]
            new_rels: dict[str, dict] = {}
            for r in old_rels:
                t = r.get("character", "")
                l = r.get("relationship", "")
                if t:
                    rt = _classify_label_to_type(l)
                    new_rels[t] = {
                        "current_status": rt or "ally",
                        "since_chapter": entry.get(
                            "first_appearance", 1),
                    }
            entry["relationships"] = new_rels
        new_chars[new_id] = entry
        id_mapping[old_id] = new_id

    state["characters"] = new_chars
    count_after = len(new_chars)
    refs_updated = _update_references(state, id_mapping)

    _save_id_counter(next_num)
    state["metadata"]["last_updated"] = (
        datetime.now(timezone.utc).isoformat())
    save_canon(state)

    print("\n╔══════════════════════════════════════════════════╗")
    print("║        CHARACTER  ID  MIGRATION  COMPLETE       ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"\n  Characters before : {count_before}")
    print(f"  Characters after  : {count_after}")
    print(f"  References updated: {refs_updated}")

    if merge_log:
        print("\n  ── Merges ──")
        for line in merge_log:
            print(line)

    print("\n  ── Full ID mapping ──")
    for old, new in sorted(id_mapping.items(),
                           key=lambda kv: kv[1]):
        dn = new_chars.get(new, {}).get("display_name", "?")
        print(f"    {old:<35} → {new}  ({dn})")

    print()

    return {
        "before": count_before,
        "after": count_after,
        "refs_updated": refs_updated,
        "mapping": id_mapping,
    }


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def merge_chapter(extraction: dict) -> dict:
    state = load_canon()

    chars = state.get("characters", {})
    if chars and not _is_stable_format(chars):
        print("  ✗ Characters are not in stable-ID format.")
        print("    Run:  python main.py migrate")
        return state

    # ── Normalisation layer ──────────────────────────────────────
    from phase1.normalizer import normalize_extraction
    extraction = normalize_extraction(extraction, state)

    if _needs_relationship_migration(state):
        _migrate_relationship_format(state)

    conflicts: list = _load(config.CONFLICT_LOG_FILE, [])
    prev_len = len(conflicts)

    _merge_new_characters(state, extraction, conflicts)
    _merge_character_updates(state, extraction, conflicts)
    _merge_events(state, extraction, conflicts)
    _merge_new_threads(state, extraction, conflicts)
    _merge_resolved_threads(state, extraction, conflicts)
    _merge_relationship_events(state, extraction, conflicts)
    _merge_emotional_deltas(state, extraction, conflicts)
    _merge_thread_progression(state, extraction, conflicts)

    ch = extraction["chapter_number"]
    if ch not in state["metadata"]["chapters_processed"]:
        state["metadata"]["chapters_processed"].append(ch)
        state["metadata"]["chapters_processed"].sort()
    state["metadata"]["last_updated"] = (
        datetime.now(timezone.utc).isoformat())

    save_canon(state)
    _save(config.CONFLICT_LOG_FILE, conflicts)

    new = len(conflicts) - prev_len
    if new:
        print(f"    ⚠ {new} new conflict(s) logged")

    return state
