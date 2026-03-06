import os
from phase1 import config
from .core import dedupe, _DEAD_STATUSES, _ALIVE_STATUSES, log_conflict
from io_utils import load_json
from .name_utils import normalize_name, split_name, same_character, next_char_id, add_alias

class CharacterManager:
    def __init__(self, state, conflicts):
        self.state = state
        self.conflicts = conflicts
        self.chars = state.setdefault("characters", {})

        self.alias_table_path = os.path.join(config.CANON_DIR, "aliases.json")
        self.alias_table = load_json(self.alias_table_path, {})
        
        self.word_index = {}
        for cid, cdata in self.chars.items():
            self._index_character(cid, cdata)

    def _index_character(self, cid, cdata):
        names = [cdata.get("display_name", "")] + cdata.get("aliases", [])
        for n in names:
            if not n: continue
            norm = normalize_name(n)
            for w in norm.split():
                if len(w) > 3:
                    self.word_index.setdefault(w, set()).add(cid)

    def resolve_char_id(self, name: str, chapter: int) -> str:
        name_clean = (name or "").strip()
        if not name_clean: return ""
        norm_name = normalize_name(name_clean)

        if norm_name in self.alias_table:
            return self.alias_table[norm_name]

        candidates = set()
        for w in norm_name.split():
            if len(w) > 3 and w in self.word_index:
                candidates.update(self.word_index[w])
        
        if not candidates:
            candidates = set(self.chars.keys())

        matches = set()
        for cid in candidates:
            cdata = self.chars[cid]
            for known in [cdata.get("display_name", "")] + cdata.get("aliases", []):
                from .name_utils import FORCE_SEPARATE
                pair = frozenset([name_clean.lower().strip(), known.lower().strip()])
                if pair in FORCE_SEPARATE: continue
                
                if same_character(name_clean, known):
                    matches.add(cid)
                    break

        if len(matches) == 1:
            cid = matches.pop()
            if add_alias(self.chars[cid], name_clean):
                self._index_character(cid, self.chars[cid])
            return cid
            
        if len(matches) > 1:
            print(f"    ⚠ Ambiguous match for '{name_clean}': {sorted(matches)}")
            
        new_id = next_char_id(self.chars)
        self.chars[new_id] = {
            "id": new_id,
            "display_name": name_clean,
            "aliases": [name_clean],
            "first_appearance": chapter,
            "status": "unknown",
            "description": "",
            "abilities": [],
            "relationships": {},
            "updates": [],
        }
        self._index_character(new_id, self.chars[new_id])
        return new_id

    def update(self, extraction, rel_manager):
        chapter = extraction["chapter_number"]

        for char in extraction.get("new_characters", []):
            name = (char.get("name") or "").strip()
            if not name: continue
            cid = self.resolve_char_id(name, chapter)
            entry = self.chars[cid]
            if entry["first_appearance"] == chapter:
                entry["status"] = char.get("status", "unknown")
                entry["description"] = char.get("description", "")
                entry["abilities"] = dedupe(char.get("abilities") or [])
                entry["updates"].append({
                    "chapter": chapter,
                    "detail": f"First appearance: {char.get('description', '')}"
                })
            else:
                entry["updates"].append({
                    "chapter": chapter,
                    "detail": f"Re-introduced as '{name}': {char.get('description', '')}"
                })
            for rel in char.get("relationships") or []:
                rel_manager.process_relationship(cid, rel, chapter, self)

        for upd in extraction.get("character_updates", []):
            name = (upd.get("name") or "").strip()
            if not name: continue
            
            # Using resolve_char_id to verify presence / link gracefully
            cid = self.resolve_char_id(name, chapter)
            cs = self.chars[cid]
            
            new_status = (upd.get("status") or "unknown").strip().lower()
            old_status = (cs.get("status") or "unknown").strip().lower()
            
            if new_status and new_status != "unknown":
                if old_status in _DEAD_STATUSES and new_status in _ALIVE_STATUSES:
                    log_conflict(self.conflicts, kind="status_contradiction", chapter=chapter, 
                                 character=cs["display_name"], character_id=cid, 
                                 old_status=old_status, new_status=new_status,
                                 detail=f"'{cs['display_name']}' was '{old_status}' but appears as '{new_status}' in ch {chapter}")
                cs["status"] = new_status

            new_abilities = upd.get("new_abilities") or []
            if new_abilities:
                cs["abilities"].extend(new_abilities)
                cs["abilities"] = dedupe(cs["abilities"])

            for rel in upd.get("new_relationships") or []:
                rel_manager.process_relationship(cid, rel, chapter, self)

            detail = (upd.get("detail") or "").strip()
            if detail:
                cs["updates"].append({"chapter": chapter, "detail": detail})

        for name, dims in extraction.get("emotional_deltas", {}).items():
            name = (name or "").strip()
            if not name or not isinstance(dims, dict): continue
            cid = self.resolve_char_id(name, chapter)
            evidence = str(dims.get("evidence", "")).strip()
            clamped = {}
            for dim, delta in dims.items():
                if dim == "evidence" or dim not in config.EMOTIONAL_DIMENSIONS: continue
                try: val = float(delta)
                except ValueError: continue
                clamped[dim] = round(max(-config.MAX_EMOTIONAL_DELTA, min(config.MAX_EMOTIONAL_DELTA, val)), 3)
            if not clamped: continue
            
            target = self.state.setdefault("emotional_deltas", {}).setdefault(cid, [])
            self.state["emotional_deltas"][cid] = [e for e in target if e.get("chapter") != chapter]
            
            entry = {"chapter": chapter, "deltas": clamped}
            if evidence: entry["evidence"] = evidence
            self.state["emotional_deltas"][cid].append(entry)
