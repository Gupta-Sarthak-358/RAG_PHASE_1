import json
import os
import re
import tempfile
from datetime import datetime, timezone

from phase1 import config
from io_utils import load_json, save_json

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

def log_conflict(conflict_list: list, kind: str, chapter: int, **fields):
    entry = {
        "type": kind,
        "chapter": chapter,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    entry.update(fields)
    conflict_list.append(entry)

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

def clean_conflict_log(types_to_remove: list = None) -> int:
    if types_to_remove is None:
        types_to_remove = ["relationship_contradiction"]
    remove_set = set(types_to_remove)
    conflicts = load_json(config.CONFLICT_LOG_FILE, [])
    if not isinstance(conflicts, list): return 0
    before = len(conflicts)
    cleaned = [c for c in conflicts if c.get("type") not in remove_set]
    after = len(cleaned)
    removed = before - after
    if removed > 0:
        save_json(config.CONFLICT_LOG_FILE, cleaned)
    return removed

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
