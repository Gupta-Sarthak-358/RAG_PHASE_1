import os
import re
from datetime import datetime, timezone
from phase1 import config
from .core import load_canon, save_canon, _empty_state, _load, _save, dedupe, clean_conflict_log
from .character_manager import CharacterManager
from .relationship_manager import RelationshipManager
from .thread_manager import ThreadManager
from .event_manager import EventManager

class CanonMerger:
    def __init__(self):
        self.state = load_canon()
        self.conflicts = _load(config.CONFLICT_LOG_FILE, [])

    def merge(self, extraction):
        chars = self.state.get("characters", {})
        if chars and not all(re.match(r"char_\d+$", k) for k in chars):
            print("  ✗ Characters are not in stable-ID format.")
            print("    Run:  python main.py migrate")
            return self.state

        from phase1.normalizer import normalize_extraction
        extraction = normalize_extraction(extraction, self.state)

        char_mgr = CharacterManager(self.state, self.conflicts)
        rel_mgr = RelationshipManager(self.state, self.conflicts)
        thread_mgr = ThreadManager(self.state, self.conflicts)
        event_mgr = EventManager(self.state, self.conflicts)

        prev_conflicts = len(self.conflicts)

        char_mgr.update(extraction, rel_mgr)
        rel_mgr.update(extraction, char_mgr)
        thread_mgr.update(extraction)
        event_mgr.update(extraction)

        ch = extraction["chapter_number"]
        processed = self.state.get("metadata", {}).setdefault("chapters_processed", [])
        if ch not in processed:
            processed.append(ch)
            processed.sort()
            
        self.state.setdefault("metadata", {})["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        save_canon(self.state)
        _save(config.CONFLICT_LOG_FILE, self.conflicts)

        new_conflicts = len(self.conflicts) - prev_conflicts
        if new_conflicts > 0:
            print(f"    ⚠ {new_conflicts} new conflict(s) logged")

        return self.state

def merge_chapter(extraction: dict) -> dict:
    merger = CanonMerger()
    return merger.merge(extraction)
