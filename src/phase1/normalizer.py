"""
Normalization layer between JSON extraction and canon merge.
Pure Python. No LLM calls. Deterministic.

Sits here in the pipeline:

    LLM extraction → JSON parse → evidence check
         → NORMALIZER → merge into canon database

Handles:
  - Character name cleaning  (parentheticals, annotations)
  - Fuzzy character matching against existing database
  - Ability deduplication    (noise words + fuzzy)
  - Event deduplication      (fuzzy, within batch)
  - Relationship event dedup (fuzzy, within batch)
  - Thread deduplication     (fuzzy, against existing)
"""

import re
from copy import deepcopy
from difflib import SequenceMatcher

from phase1 import config

from logger import get_logger
log = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Fuzzy matching — rapidfuzz if available, stdlib fallback
# ═══════════════════════════════════════════════════════════════════

try:
    from rapidfuzz import fuzz as _rfuzz

    def _fuzzy_ratio(a: str, b: str) -> float:
        """Return similarity 0–100 using rapidfuzz."""
        return _rfuzz.ratio(a, b)

except ImportError:

    def _fuzzy_ratio(a: str, b: str) -> float:
        """Stdlib fallback using SequenceMatcher. Slower but works."""
        return SequenceMatcher(None, a, b).ratio() * 100


# ═══════════════════════════════════════════════════════════════════
# Name cleaning
# ═══════════════════════════════════════════════════════════════════

def clean_name(name: str) -> str:
    """
    Remove parenthetical annotations and extra whitespace.
    Preserves capitalisation for display.

    "Kana (his mother)"  → "Kana"
    "Kaguya [sealed]"    → "Kaguya"
    "  Akane   Uzumaki " → "Akane Uzumaki"
    """
    if not name:
        return ""
    name = re.sub(r"\(.*?\)", "", name)   # (his mother)
    name = re.sub(r"\[.*?\]", "", name)   # [sealed]
    name = re.sub(r"\{.*?\}", "", name)   # {note}
    return " ".join(name.split()).strip()


def normalize_for_comparison(text: str) -> str:
    """
    Aggressive normalisation for matching only.
    Not stored — only used for comparison.

    "Princess Kaguya!"  → "princess kaguya"
    "Kana (his mother)" → "kana"
    """
    text = clean_name(text).lower()
    text = re.sub(r"[^a-z\s]", "", text)
    return " ".join(text.split()).strip()


# ═══════════════════════════════════════════════════════════════════
# Character fuzzy matching
# ═══════════════════════════════════════════════════════════════════

def _match_to_existing(
    name: str,
    existing_chars: dict,
) -> str | None:
    """
    Fuzzy-match a cleaned name to an existing character.
    Returns the canonical display_name or None.

    Short names (< 4 chars) are skipped.
    Short names (< 6 chars) use a stricter threshold.
    """
    norm = normalize_for_comparison(name)
    if not norm or len(norm) < 4:
        return None

    threshold = config.FUZZY_NAME_THRESHOLD
    if len(norm) < 6:
        threshold = 95

    best_name: str | None = None
    best_score: float = 0

    for cdata in existing_chars.values():
        all_names = (
            [cdata.get("display_name", "")]
            + cdata.get("aliases", [])
        )
        for known in all_names:
            known_norm = normalize_for_comparison(known)
            if not known_norm:
                continue

            # split names
            parts1 = norm.split()
            parts2 = known_norm.split()

            first1 = parts1[0]
            first2 = parts2[0]

            # HARD RULE: different first names → not same character
            if first1 != first2:
                continue

            score = _fuzzy_ratio(norm, known_norm)
            if score > best_score:
                best_score = score
                best_name = cdata.get("display_name", known)

    if best_score >= threshold:
        return best_name
    return None


def _resolve_name(
    name: str,
    existing_chars: dict,
) -> str:
    """Clean a name, then try to match it to an existing character.
    Returns the best available name string."""
    cleaned = clean_name(name)
    if not cleaned:
        return name

    if existing_chars:
        match = _match_to_existing(cleaned, existing_chars)
        if match and match != cleaned:
            log.info(f"    ⊳ fuzzy matched: "
                  f"'{cleaned}' → '{match}'")
            return match

    return cleaned


# ═══════════════════════════════════════════════════════════════════
# Ability normalisation + dedup
# ═══════════════════════════════════════════════════════════════════

_ABILITY_NOISE = frozenset(config.ABILITY_NOISE_WORDS)


def normalize_ability(name: str) -> str:
    """
    Normalise an ability name for comparison.

    "Shadow Clone Technique" → "shadow clone"
    "Rasengan no Jutsu"      → "rasengan"
    "Fire Style: Fireball"   → "fire style: fireball"
    """
    if not name:
        return ""
    name = name.lower().strip()
    words = [w for w in name.split() if w not in _ABILITY_NOISE]
    return " ".join(words).strip()


def dedupe_abilities(abilities: list[str]) -> list[str]:
    """
    Remove duplicate abilities from a list.
    Uses normalised comparison + fuzzy matching.

    Keeps the first occurrence (original spelling).
    """
    if not abilities:
        return []

    result: list[str] = []
    seen: list[str] = []

    for ability in abilities:
        if not ability or not ability.strip():
            continue
        norm = normalize_ability(ability)
        if not norm:
            continue

        is_dupe = False
        for s in seen:
            if norm == s:
                is_dupe = True
                break
            if _fuzzy_ratio(norm, s) >= config.FUZZY_ABILITY_THRESHOLD:
                is_dupe = True
                break

        if not is_dupe:
            result.append(ability)
            seen.append(norm)

    return result


# ═══════════════════════════════════════════════════════════════════
# Event deduplication (within a single extraction batch)
# ═══════════════════════════════════════════════════════════════════

def _dedupe_events_batch(events: list[dict]) -> list[dict]:
    """
    Remove near-duplicate major_events within one extraction.

    "Akane confesses love to Kaguya"
    "Akane admits love to Kaguya"
    → keeps only the first
    """
    if len(events) <= 1:
        return events

    result: list[dict] = []

    for ev in events:
        text = normalize_for_comparison(ev.get("event", ""))
        if not text:
            continue

        is_dupe = False
        for existing in result:
            ex_text = normalize_for_comparison(
                existing.get("event", ""))
            if _fuzzy_ratio(text, ex_text) > config.FUZZY_EVENT_THRESHOLD:
                is_dupe = True
                break

        if is_dupe:
            log.info(f"    ⊳ deduped event: "
                  f"'{ev.get('event', '')[:60]}'")
        else:
            result.append(ev)

    return result


def _dedupe_rel_events_batch(events: list[dict]) -> list[dict]:
    """
    Remove near-duplicate relationship_events within one extraction.
    Only dedupes when BOTH the character pair AND description match.
    """
    if len(events) <= 1:
        return events

    result: list[dict] = []

    for ev in events:
        chars = tuple(sorted(
            normalize_for_comparison(c)
            for c in ev.get("characters", [])))
        desc = normalize_for_comparison(
            ev.get("description", ""))

        is_dupe = False
        for existing in result:
            ex_chars = tuple(sorted(
                normalize_for_comparison(c)
                for c in existing.get("characters", [])))
            if chars != ex_chars:
                continue
            ex_desc = normalize_for_comparison(
                existing.get("description", ""))
            if _fuzzy_ratio(desc, ex_desc) > config.FUZZY_EVENT_THRESHOLD:
                is_dupe = True
                break

        if is_dupe:
            log.info(f"    ⊳ deduped rel event: "
                  f"'{ev.get('description', '')[:60]}'")
        else:
            result.append(ev)

    return result


# ═══════════════════════════════════════════════════════════════════
# Thread deduplication
# ═══════════════════════════════════════════════════════════════════

def _fuzzy_find_thread(
    name: str,
    existing_threads: dict,
) -> str | None:
    """
    Fuzzy-match a thread name to an existing thread.
    Returns canonical thread name or None.

    "Kirigakure preparing attack" → "Attack from Kirigakure"
    """
    norm = normalize_for_comparison(name)
    if not norm or len(norm) < 4:
        return None

    best_name: str | None = None
    best_score: float = 0

    for tname in existing_threads:
        tname_norm = normalize_for_comparison(tname)
        if not tname_norm:
            continue
        score = _fuzzy_ratio(norm, tname_norm)
        if score > best_score:
            best_score = score
            best_name = tname

    if best_score >= config.FUZZY_THREAD_THRESHOLD:
        return best_name
    return None


# ═══════════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════════

def normalize_extraction(
    extraction: dict,
    story_state: dict,
) -> dict:
    """
    Clean extraction data before it reaches the merger.

    Pure Python.  No LLM calls.  Deterministic.

    Steps:
      1. Clean character names  (remove annotations)
      2. Fuzzy-match names to existing characters
      3. Dedupe abilities per character
      4. Clean names in relationship_events
      5. Clean names in emotional_deltas
      6. Dedupe major_events within batch
      7. Dedupe relationship_events within batch
      8. Match new threads to existing (fuzzy)
      9. Canonicalise thread_progression names
    """
    result = deepcopy(extraction)
    existing_chars = story_state.get("characters", {})
    existing_threads = story_state.get("plot_threads", {})

    # ── 1. new_characters ────────────────────────────────────────
    for char in result.get("new_characters", []):
        original = char.get("name", "")
        resolved = _resolve_name(original, existing_chars)
        if resolved != original.strip():
            char["name"] = resolved

        abilities = char.get("abilities")
        if abilities:
            before = len(abilities)
            char["abilities"] = dedupe_abilities(abilities)
            after = len(char["abilities"])
            if after < before:
                log.info(f"    ⊳ deduped {before - after} "
                      f"ability(ies) for {char.get('name', '?')}")

        for rel in char.get("relationships") or []:
            rc = rel.get("character", "")
            if rc:
                rel["character"] = _resolve_name(
                    rc, existing_chars)

    # ── 2. character_updates ─────────────────────────────────────
    for upd in result.get("character_updates", []):
        original = upd.get("name", "")
        resolved = _resolve_name(original, existing_chars)
        if resolved != original.strip():
            upd["name"] = resolved

        abilities = upd.get("new_abilities")
        if abilities:
            before = len(abilities)
            upd["new_abilities"] = dedupe_abilities(abilities)
            after = len(upd["new_abilities"])
            if after < before:
                log.info(f"    ⊳ deduped {before - after} "
                      f"ability(ies) for {upd.get('name', '?')}")

        for rel in upd.get("new_relationships") or []:
            rc = rel.get("character", "")
            if rc:
                rel["character"] = _resolve_name(
                    rc, existing_chars)

    # ── 3. relationship_events ───────────────────────────────────
    for event in result.get("relationship_events", []):
        chars = event.get("characters", [])
        event["characters"] = [
            _resolve_name(c, existing_chars) for c in chars
        ]

    # ── 4. emotional_deltas ──────────────────────────────────────
    raw_deltas = result.get("emotional_deltas", {})
    clean_deltas: dict = {}
    for char, dims in raw_deltas.items():
        resolved = _resolve_name(char, existing_chars)
        clean_deltas[resolved] = dims
    result["emotional_deltas"] = clean_deltas

    # ── 5. Dedupe major_events ───────────────────────────────────
    events = result.get("major_events", [])
    if len(events) > 1:
        result["major_events"] = _dedupe_events_batch(events)

    # ── 6. Dedupe relationship_events ────────────────────────────
    rel_events = result.get("relationship_events", [])
    if len(rel_events) > 1:
        result["relationship_events"] = _dedupe_rel_events_batch(
            rel_events)

    # ── 7. Thread dedup: new_plot_threads ────────────────────────
    new_threads = result.get("new_plot_threads", [])
    thread_prog = list(result.get("thread_progression", []))
    clean_threads: list[dict] = []

    for thread in new_threads:
        tname = thread.get("name", "")
        match = _fuzzy_find_thread(tname, existing_threads)
        if match:
            log.info(f"    ⊳ thread '{tname}' matches existing "
                  f"'{match}' → progression")
            thread_prog.append({
                "thread_name": match,
                "status_change": "advanced",
                "justification": thread.get(
                    "description", ""),
            })
        else:
            clean_threads.append(thread)

    result["new_plot_threads"] = clean_threads

    # ── 8. Canonicalise thread_progression names ─────────────────
    for prog in thread_prog:
        tname = prog.get("thread_name", "")
        if not tname:
            continue
        match = _fuzzy_find_thread(tname, existing_threads)
        if match and match != tname:
            log.info(f"    ⊳ thread name: '{tname}' → '{match}'")
            prog["thread_name"] = match

    result["thread_progression"] = thread_prog

    return result


# ═══════════════════════════════════════════════════════════════════
# Global Normalization pass
# ═══════════════════════════════════════════════════════════════════

def run_global_normalization():
    """
    Loads the canonical file databases, identifies character duplicates 
    using fuzzy matching, merges their data components (abilities, 
    relationships, updates), updates relationship target IDs globally, 
    and saves the cleaned databases back to disk.
    """
    from canon_merger import load_canon, save_canon, dedupe
    
    state = load_canon()
    chars = state.get("characters", {})
    if not chars:
        print("No characters to normalize.")
        return
        
    print(f"\nStarting global normalization of {len(chars)} characters...")
    
    merged_count = 0
    cids = list(chars.keys())
    id_mapping = {}
    
    for i in range(len(cids)):
        cid1 = cids[i]
        if cid1 not in chars: continue
        
        c1 = chars[cid1]
        name1 = c1.get("display_name", "")
        
        for j in range(i+1, len(cids)):
            cid2 = cids[j]
            if cid2 not in chars: continue
            
            c2 = chars[cid2]
            name2 = c2.get("display_name", "")
            
            is_match = False
            for n2 in [name2] + c2.get("aliases", []):
                for n1 in [name1] + c1.get("aliases", []):
                    norm1 = normalize_for_comparison(n1)
                    norm2 = normalize_for_comparison(n2)
                    if not norm1 or not norm2:
                        continue

                    # split names
                    parts1 = norm1.split()
                    parts2 = norm2.split()

                    first1 = parts1[0]
                    first2 = parts2[0]

                    # HARD RULE: first names must match
                    if first1 != first2:
                        continue

                    threshold = config.FUZZY_NAME_THRESHOLD if len(norm1) >= 6 and len(norm2) >= 6 else 95

                    if _fuzzy_ratio(norm1, norm2) >= threshold:
                        is_match = True
                        break
                if is_match: break
                
            if is_match:
                log.info(f"  ⊳ Merging '{name2}' ({cid2}) INTO '{name1}' ({cid1})")
                
                c1["aliases"].extend([name2] + c2.get("aliases", []))
                c1["aliases"] = dedupe(c1["aliases"])
                
                c1["abilities"].extend(c2.get("abilities", []))
                c1["abilities"] = dedupe_abilities(c1["abilities"])
                
                c1["updates"].extend(c2.get("updates", []))
                c1["updates"].sort(key=lambda x: x.get("chapter", 9999))
                
                for target_id, rel_data in c2.get("relationships", {}).items():
                    if target_id not in c1.setdefault("relationships", {}):
                        c1["relationships"][target_id] = rel_data
                        
                id_mapping[cid2] = cid1
                del chars[cid2]
                merged_count += 1

    refs_updated = 0
    for cid, c in chars.items():
        rels = c.get("relationships", {})
        new_rels = {}
        for target_id, rel_data in list(rels.items()):
            if target_id in id_mapping:
                new_rels[id_mapping[target_id]] = rel_data
                refs_updated += 1
            else:
                new_rels[target_id] = rel_data
        c["relationships"] = new_rels

    print(f"\nGlobal normalization complete.")
    print(f"  Merged {merged_count} duplicate characters.")
    print(f"  Updated {refs_updated} relationship references.\n")
    
    save_canon(state)
