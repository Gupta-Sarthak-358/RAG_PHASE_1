from phase1 import config
from .core import log_conflict

class RelationshipManager:
    def __init__(self, state, conflicts):
        self.state = state
        self.conflicts = conflicts

    def classify_label_to_type(self, label: str) -> str:
        lower = label.lower().strip()
        if not lower: return None
        if lower in config.REL_TYPES: return lower
        if lower in config.REL_LABEL_TO_TYPE: return config.REL_LABEL_TO_TYPE[lower]
        _kw = {
            "family": ["father", "mother", "brother", "sister", "son", "daughter", "parent", "sibling", "uncle", "aunt", "cousin", "clan", "grandfather", "grandmother"],
            "romantic": ["romantic", "love", "fiance", "spouse", "wife", "husband", "girlfriend", "boyfriend"],
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

    def classify_label_to_event(self, label: str) -> str:
        lower = label.lower().strip()
        if not lower: return "cooperation"
        if lower in config.REL_EVENT_TYPES: return lower
        _kw = {
            "kiss": ["kiss"],
            "confession": ["confess", "confession", "admit feeling", "declare"],
            "romantic_progression": ["romantic", "love", "affection", "intimate", "dating", "courting"],
            "betrayal": ["betray", "traitor", "backstab", "deceiv"],
            "argument": ["argument", "fight", "confront", "conflict", "disagree", "clash", "tension", "dispute"],
            "alliance": ["alliance", "allied", "unite"],
            "trust_gain": ["trust", "bond", "respect", "faith"],
            "trust_loss": ["distrust", "suspicion", "doubt", "lost trust"],
            "met": ["met", "meet", "encounter", "introduc"],
            "cooperation": ["work", "cooperat", "collaborat", "mission", "plan", "together", "team", "help"],
        }
        for event_type, keywords in _kw.items():
            if any(kw in lower for kw in keywords):
                return event_type
        return "cooperation"

    def ensure_rel_entry(self, chars: dict, from_cid: str, to_cid: str):
        if from_cid not in chars: return None
        cdata = chars[from_cid]
        rels = cdata.setdefault("relationships", {})
        if not isinstance(rels, dict):
            rels = {}
            cdata["relationships"] = rels
        if to_cid not in rels:
            rels[to_cid] = {"state": "neutral", "history": [], "signals": {}}
        else:
            entry = rels[to_cid]
            if "current_status" in entry and "signals" not in entry:
                rels[to_cid] = {"state": entry.get("current_status", "neutral"), "history": [], "signals": {}}
        return rels[to_cid]

    def compute_rel_state(self, signals: dict, history: list) -> str:
        if len(history) < config.REL_MIN_INTERACTIONS: return "neutral"
        for event_type, (threshold, resulting_state) in config.REL_SIGNAL_THRESHOLDS.items():
            if signals.get(event_type, 0) >= threshold:
                return resulting_state
        return "neutral"

    def record_rel_event(self, chars: dict, from_cid: str, to_cid: str, event_type: str, chapter: int):
        for a, b in [(from_cid, to_cid), (to_cid, from_cid)]:
            entry = self.ensure_rel_entry(chars, a, b)
            if entry is None: continue
            entry["history"].append({"chapter": chapter, "event": event_type})
            entry["signals"][event_type] = entry["signals"].get(event_type, 0) + 1
            entry["state"] = self.compute_rel_state(entry["signals"], entry["history"])

    def set_static_relationship(self, chars: dict, from_cid: str, to_cid: str, rel_type: str, chapter: int):
        if from_cid not in chars: return
        cdata = chars[from_cid]
        rels = cdata.setdefault("relationships", {})
        existing = rels.get(to_cid)
        if existing:
            old_type = existing.get("current_status", "")
            old_pri = config.REL_PRIORITY.get(old_type, 0)
            new_pri = config.REL_PRIORITY.get(rel_type, 0)
            if old_type == "family" and rel_type != "family": return
            if rel_type == "enemy": pass
            elif new_pri <= old_pri: return
        rels[to_cid] = {"current_status": rel_type, "since_chapter": chapter}

    def relationship_event_exists(self, event: dict) -> bool:
        new_chars = event.get("characters", event.get("between", []))
        new_evt = event.get("event_type", event.get("type", ""))
        for e in self.state.get("relationship_events", []):
            e_chars = e.get("characters", e.get("between", []))
            e_evt = e.get("event_type", e.get("type", ""))
            if (e.get("chapter") == event.get("chapter") and e_chars == new_chars and e_evt == new_evt and e.get("intensity") == event.get("intensity") and e.get("visibility") == event.get("visibility")):
                return True
        return False

    def process_relationship(self, from_cid, rel_dict, chapter, char_manager):
        rc = (rel_dict.get("character") or "").strip()
        label = (rel_dict.get("relationship") or "").strip()
        if not rc or not label: return
        rel_cid = char_manager.resolve_char_id(rc, chapter)
        rel_type = self.classify_label_to_type(label)
        if rel_type:
            self.set_static_relationship(char_manager.chars, from_cid, rel_cid, rel_type, chapter)
        else:
            event_type = self.classify_label_to_event(label)
            event = {
                "chapter": chapter,
                "characters": sorted([from_cid, rel_cid]),
                "event_type": event_type,
                "description": label,
            }
            if not self.relationship_event_exists(event):
                self.state.setdefault("relationship_events", []).append(event)
                print(f"    ⚠ Unknown relationship label '{label}' converted to event '{event_type}'")
            self.record_rel_event(char_manager.chars, from_cid, rel_cid, event_type, chapter)

    def update(self, extraction, char_manager):
        chapter = extraction["chapter_number"]
        for raw in extraction.get("relationship_events", []):
            char_names = raw.get("characters", [])
            if len(char_names) != 2: continue
            resolved = []
            for name in char_names:
                name = (name or "").strip()
                if not name: break
                resolved.append(char_manager.resolve_char_id(name, chapter))
            if len(resolved) != 2: continue
            raw_evt = raw.get("event_type", "")
            event_type = self.classify_label_to_event(str(raw_evt))
            description = raw.get("description", "") or str(raw_evt)
            event = {
                "chapter": chapter,
                "characters": sorted(resolved),
                "event_type": event_type,
                "description": description,
            }
            evidence = raw.get("evidence", "")
            if evidence: event["evidence"] = evidence
            if self.relationship_event_exists(event): continue
            self.state.setdefault("relationship_events", []).append(event)
            self.record_rel_event(char_manager.chars, resolved[0], resolved[1], event_type, chapter)
