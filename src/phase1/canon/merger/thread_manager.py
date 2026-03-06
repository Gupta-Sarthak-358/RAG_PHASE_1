from phase1 import config
from .core import log_conflict

class ThreadManager:
    def __init__(self, state, conflicts):
        self.state = state
        self.conflicts = conflicts
        self.threads = state.setdefault("plot_threads", {})

    def find_thread_name(self, name: str) -> str:
        if name in self.threads: return name
        name_lower = name.lower().strip()
        for tname in self.threads:
            if tname.lower().strip() == name_lower: return tname
        name_words = {w.lower() for w in name.split() if len(w) > 3}
        if name_words:
            best, best_overlap = None, 0
            for tname in self.threads:
                twords = {w.lower() for w in tname.split() if len(w) > 3}
                overlap = len(name_words & twords)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best = tname
            if best and best_overlap > 0:
                return best
        return None

    def update(self, extraction):
        chapter = extraction["chapter_number"]
        
        for thread in extraction.get("new_plot_threads", []):
            tname = (thread.get("name") or "").strip()
            if not tname: continue
            existing = self.find_thread_name(tname)
            if existing:
                tdata = self.threads[existing]
                if tdata["status"] == "resolved":
                    log_conflict(self.conflicts, kind="resolved_thread_reappears", chapter=chapter,
                                 thread=existing, detail=f"Thread '{existing}' was resolved but reappears in ch {chapter}")
                    tdata["status"] = "reopened"
                tdata["updates"].append({"chapter": chapter, "detail": thread.get("description", "")})
            else:
                self.threads[tname] = {
                    "introduced": chapter,
                    "status": "unresolved",
                    "description": thread.get("description", ""),
                    "updates": [{"chapter": chapter, "detail": thread.get("description", "")}],
                }

        for tname in extraction.get("resolved_plot_threads", []):
            tname = (tname or "").strip()
            if not tname: continue
            existing = self.find_thread_name(tname)
            if existing:
                self.threads[existing]["status"] = "resolved"
                self.threads[existing]["updates"].append({"chapter": chapter, "detail": "Resolved"})
            else:
                self.threads[tname] = {
                    "introduced": chapter,
                    "status": "resolved",
                    "description": "(resolved; no prior tracking)",
                    "updates": [{"chapter": chapter, "detail": "Resolved"}],
                }

        for prog in extraction.get("thread_progression", []):
            tname = (prog.get("thread_name") or "").strip()
            status_change = (prog.get("status_change") or "").strip().lower()
            justification = (prog.get("justification") or "").strip()
            if not tname or status_change not in config.VALID_THREAD_STATUSES: continue
            existing = self.find_thread_name(tname)
            if not existing:
                self.threads[tname] = {
                    "introduced": chapter,
                    "status": "unresolved",
                    "description": justification,
                    "updates": [],
                }
                existing = tname
            thread = self.threads[existing]
            already = any(u.get("chapter") == chapter and u.get("status_change") == status_change for u in thread.get("updates", []))
            if already: continue
            thread["updates"].append({
                "chapter": chapter,
                "detail": justification,
                "status_change": status_change,
                "justification": justification,
            })
            if status_change == "resolved":
                if thread["status"] == "resolved":
                    log_conflict(self.conflicts, kind="thread_already_resolved", chapter=chapter, thread=existing,
                                 detail=f"Thread '{existing}' marked resolved again in ch {chapter}")
                thread["status"] = "resolved"

        # Priority 5: Thread Hygiene (Dormancy)
        for tname, tdata in self.threads.items():
            if tdata.get("status") in ["resolved", "archived"]: continue
            
            last_activity = tdata.get("introduced", 0)
            if tdata.get("updates"):
                last_activity = max(u.get("chapter", 0) for u in tdata["updates"])
                
            if chapter - last_activity > config.THREAD_ARCHIVE_THRESHOLD:
                tdata["status"] = "archived"
                tdata["updates"].append({
                    "chapter": chapter,
                    "detail": "Auto-archived due to prolonged inactivity."
                })
