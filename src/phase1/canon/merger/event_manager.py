class EventManager:
    def __init__(self, state, conflicts):
        self.state = state
        self.conflicts = conflicts
        self.events = state.setdefault("events", [])

    def update(self, extraction):
        chapter = extraction["chapter_number"]
        for ev in extraction.get("major_events", []):
            event_str = ""
            evidence = ""
            if isinstance(ev, str): event_str = ev.strip()
            elif isinstance(ev, dict):
                event_str = str(ev.get("event", "")).strip()
                evidence = str(ev.get("evidence", "")).strip()
            if not event_str: continue
            entry = {"chapter": chapter, "event": event_str}
            if evidence: entry["evidence"] = evidence
            self.events.append(entry)
