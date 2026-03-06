"""
One-command story recap.

Reads story_state.json and produces a focused briefing:
  - Recent chapter activity (last N chapters)
  - Active plot threads with pressure
  - Key character states
  - Unresolved mysteries / dormant threads
  - Relationship timeline highlights
  - Emotional trajectory

Pure Python.  No LLM calls.  Reads state, prints report.
"""

import json
import os
from datetime import datetime

from phase1 import config
from io_utils import load_json


# ═══════════════════════════════════════════════════════════════════
# I/O
# ═══════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════
# Formatting helpers
# ═══════════════════════════════════════════════════════════════════

def _bar(value: float, width: int = 15) -> str:
    filled = int(round(value * width))
    return "█" * filled + "░" * (width - filled)


def _wrap(text: str, width: int = 72, indent: int = 6) -> str:
    """Simple word-wrap with indent."""
    words = text.split()
    lines: list[str] = []
    current = " " * indent
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current.rstrip())
            current = " " * indent + word
        else:
            current += (" " if current.strip() else "") + word
    if current.strip():
        lines.append(current.rstrip())
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Section builders
# ═══════════════════════════════════════════════════════════════════

def _section_header(state: dict, n: int) -> list[str]:
    chapters = state.get("metadata", {}).get(
        "chapters_processed", [])
    total = len(chapters)
    last_updated = state.get("metadata", {}).get(
        "last_updated", "?")
    char_count = len(state.get("characters", {}))
    thread_count = len(state.get("plot_threads", {}))
    event_count = len(state.get("events", []))

    lines = []
    lines.append("")
    lines.append("╔════════════════════════════════════════"
                 "══════════════════╗")
    lines.append("║              S T O R Y   R E C A P"
                 "                    ║")
    lines.append("╚════════════════════════════════════════"
                 "══════════════════╝")
    lines.append("")
    lines.append(f"  Chapters processed : {total}")
    lines.append(f"  Characters tracked : {char_count}")
    lines.append(f"  Plot threads       : {thread_count}")
    lines.append(f"  Events logged      : {event_count}")
    lines.append(f"  Last updated       : {last_updated}")
    lines.append(f"  Showing last       : {n} chapters")
    return lines


def _section_recent_events(
    state: dict, recent_chapters: set[int],
) -> list[str]:
    lines = []
    lines.append("")
    lines.append("  ━━━ RECENT CHAPTER ACTIVITY ━━━")
    lines.append("")

    events = state.get("events", [])
    recent = [e for e in events
              if e.get("chapter") in recent_chapters]

    if not recent:
        lines.append("    (no events in recent chapters)")
        return lines

    # Group by chapter
    by_ch: dict[int, list[str]] = {}
    for e in recent:
        ch = e.get("chapter", 0)
        text = e.get("event", "")
        if text:
            by_ch.setdefault(ch, []).append(text)

    for ch in sorted(by_ch):
        lines.append(f"  Chapter {ch}:")
        for ev_text in by_ch[ch]:
            lines.append(f"    • {ev_text[:90]}")
        lines.append("")

    return lines


def _section_active_threads(state: dict) -> list[str]:
    lines = []
    lines.append("  ━━━ ACTIVE PLOT THREADS ━━━")
    lines.append("")

    threads = state.get("plot_threads", {})
    active = {
        name: data for name, data in threads.items()
        if data.get("status") not in ("resolved",)
    }

    if not active:
        lines.append("    (no active threads)")
        return lines

    chapters = state.get("metadata", {}).get(
        "chapters_processed", [])
    latest = max(chapters) if chapters else 0

    # Sort by how long since last touched (most stale first)
    def _staleness(item):
        _, data = item
        updates = data.get("updates", [])
        if not updates:
            return 999
        last_ch = max(u.get("chapter", 0) for u in updates)
        return latest - last_ch

    for name, data in sorted(
        active.items(), key=_staleness, reverse=True,
    ):
        updates = data.get("updates", [])
        introduced = data.get("introduced", "?")
        status = data.get("status", "?")
        desc = data.get("description", "")

        last_ch = "?"
        if updates:
            last_ch = max(u.get("chapter", 0) for u in updates)

        stale = ""
        if isinstance(last_ch, int) and latest > 0:
            gap = latest - last_ch
            if gap >= 10:
                stale = "  ⚠ STALE"
            elif gap >= 5:
                stale = "  ⚡ needs attention"

        lines.append(f"  ■ {name}")
        lines.append(f"    Status: {status}  "
                     f"Since: ch {introduced}  "
                     f"Last: ch {last_ch}{stale}")
        if desc:
            lines.append(f"    {desc[:100]}")

        # Show last progression update if available
        prog_updates = [
            u for u in updates if u.get("status_change")
        ]
        if prog_updates:
            last = prog_updates[-1]
            lines.append(
                f"    └ ch {last.get('chapter', '?')}: "
                f"{last.get('status_change', '')} — "
                f"{last.get('justification', '')[:60]}")

        lines.append("")

    return lines


def _section_character_states(
    state: dict, recent_chapters: set[int],
) -> list[str]:
    lines = []
    lines.append("  ━━━ CHARACTER STATES ━━━")
    lines.append("")

    chars = state.get("characters", {})
    if not chars:
        lines.append("    (no characters)")
        return lines

    # Sort: recently active characters first
    def _recent_activity(item):
        _, cdata = item
        updates = cdata.get("updates", [])
        recent = [u for u in updates
                  if u.get("chapter") in recent_chapters]
        return -len(recent)

    shown = 0
    for cid, cdata in sorted(
        chars.items(), key=_recent_activity,
    ):
        if shown >= 20:
            remaining = len(chars) - shown
            if remaining > 0:
                lines.append(f"    ... and {remaining} more")
            break

        name = cdata.get("display_name", cid)
        status = cdata.get("status", "?")
        first = cdata.get("first_appearance", "?")

        # Count recent updates
        updates = cdata.get("updates", [])
        recent_count = len(
            [u for u in updates
             if u.get("chapter") in recent_chapters])

        # Status marker
        marker = ""
        if status in ("dead", "deceased", "killed"):
            marker = " ☠"
        elif status in ("injured", "wounded"):
            marker = " 🩹"
        elif recent_count > 0:
            marker = f" ({recent_count} recent)"

        # Key relationships
        rels = cdata.get("relationships", {})
        rel_parts: list[str] = []
        if isinstance(rels, dict):
            for target_id, rdata in list(rels.items())[:3]:
                target_name = _resolve_display_name(
                    target_id, chars)
                rs = rdata.get("current_status", "?")
                rel_parts.append(f"{target_name}={rs}")

        rel_str = ""
        if rel_parts:
            rel_str = f"  [{', '.join(rel_parts)}]"

        lines.append(
            f"  {cid:<12} {name:<25} "
            f"{status:<10} ch{first}{marker}{rel_str}")

        shown += 1

    lines.append("")
    return lines


def _resolve_display_name(
    char_id: str, characters: dict,
) -> str:
    """Get display_name for a char_id, or return the id itself."""
    if char_id in characters:
        return characters[char_id].get("display_name", char_id)
    return char_id


def _section_unresolved(state: dict) -> list[str]:
    lines = []
    lines.append("  ━━━ UNRESOLVED MYSTERIES & DORMANT THREADS ━━━")
    lines.append("")

    threads = state.get("plot_threads", {})
    chapters = state.get("metadata", {}).get(
        "chapters_processed", [])
    latest = max(chapters) if chapters else 0

    # Find threads that haven't been touched in a while
    dormant: list[tuple[str, dict, int]] = []
    unresolved: list[tuple[str, dict]] = []

    for name, data in threads.items():
        if data.get("status") == "resolved":
            continue

        updates = data.get("updates", [])
        last_ch = 0
        if updates:
            last_ch = max(u.get("chapter", 0) for u in updates)

        gap = latest - last_ch if latest > 0 else 0

        if gap >= 5:
            dormant.append((name, data, gap))
        else:
            unresolved.append((name, data))

    if dormant:
        lines.append("  Dormant (5+ chapters untouched):")
        lines.append("")
        for name, data, gap in sorted(
            dormant, key=lambda x: -x[2],
        ):
            desc = data.get("description", "")[:80]
            lines.append(f"    ⚠ {name}  "
                         f"(silent for {gap} chapters)")
            if desc:
                lines.append(f"      {desc}")
            lines.append("")
    else:
        lines.append("  No dormant threads.")
        lines.append("")

    if unresolved:
        lines.append("  Active unresolved:")
        lines.append("")
        for name, data in unresolved:
            status = data.get("status", "?")
            lines.append(f"    → {name}  [{status}]")
        lines.append("")
    else:
        lines.append("  All threads resolved or dormant.")
        lines.append("")

    return lines


def _section_relationship_highlights(
    state: dict, recent_chapters: set[int],
) -> list[str]:
    lines = []
    lines.append("  ━━━ RECENT RELATIONSHIP CHANGES ━━━")
    lines.append("")

    rel_events = state.get("relationship_events", [])
    recent = [
        e for e in rel_events
        if e.get("chapter") in recent_chapters
    ]

    if not recent:
        lines.append("    (no relationship events recently)")
        lines.append("")
        return lines

    chars = state.get("characters", {})

    for ev in sorted(recent, key=lambda e: e.get("chapter", 0)):
        ch = ev.get("chapter", "?")
        pair = ev.get("characters",
                      ev.get("between", []))
        names = [_resolve_display_name(c, chars)
                 for c in pair]
        evt_type = ev.get("event_type",
                          ev.get("type", "?"))
        desc = ev.get("description", "")

        pair_str = " ↔ ".join(names) if names else "?"
        lines.append(f"    ch {ch}: {pair_str}")
        lines.append(f"           {evt_type}: {desc[:70]}")
        lines.append("")

    return lines


def _section_emotional_snapshot(
    state: dict, recent_chapters: set[int],
) -> list[str]:
    lines = []
    lines.append("  ━━━ EMOTIONAL TRAJECTORY (recent) ━━━")
    lines.append("")

    emo = state.get("emotional_deltas", {})
    chars = state.get("characters", {})

    if not emo:
        lines.append("    (no emotional data)")
        lines.append("")
        return lines

    # Collect recent emotional shifts
    recent_shifts: dict[str, dict[str, float]] = {}

    for cid, entries in emo.items():
        for entry in entries:
            if entry.get("chapter") not in recent_chapters:
                continue
            deltas = entry.get("deltas", {})
            if cid not in recent_shifts:
                recent_shifts[cid] = {}
            for dim, val in deltas.items():
                if dim == "evidence":
                    continue
                recent_shifts[cid][dim] = (
                    recent_shifts[cid].get(dim, 0) + val)

    if not recent_shifts:
        lines.append("    (no recent emotional shifts)")
        lines.append("")
        return lines

    for cid, dims in sorted(recent_shifts.items()):
        name = _resolve_display_name(cid, chars)
        parts: list[str] = []
        for dim in config.EMOTIONAL_DIMENSIONS:
            if dim in dims:
                val = dims[dim]
                arrow = "↑" if val > 0 else "↓" if val < 0 else "→"
                parts.append(f"{dim}{arrow}{val:+.2f}")
        if parts:
            lines.append(f"    {name:<25} {', '.join(parts)}")

    lines.append("")
    return lines


def _section_conflicts(state: dict) -> list[str]:
    lines = []

    conflicts = load_json(config.CONFLICT_LOG_FILE, [])
    if not conflicts:
        return lines

    lines.append("  ━━━ UNRESOLVED CONFLICTS ━━━")
    lines.append("")

    # Show last 5
    for c in conflicts[-5:]:
        ch = c.get("chapter", "?")
        kind = c.get("type", "?")
        detail = c.get("detail", "")[:80]
        lines.append(f"    ch {ch} [{kind}]: {detail}")

    if len(conflicts) > 5:
        lines.append(f"    ... {len(conflicts) - 5} more "
                     f"in conflict_log.json")

    lines.append("")
    return lines


def _section_whats_next(state: dict) -> list[str]:
    """Actionable suggestions based on state analysis."""
    lines = []
    lines.append("  ━━━ WHAT TO FOCUS ON NEXT ━━━")
    lines.append("")

    threads = state.get("plot_threads", {})
    chapters = state.get("metadata", {}).get(
        "chapters_processed", [])
    latest = max(chapters) if chapters else 0

    suggestions: list[str] = []

    # Stale high-priority threads
    for name, data in threads.items():
        if data.get("status") == "resolved":
            continue
        updates = data.get("updates", [])
        last_ch = max(
            (u.get("chapter", 0) for u in updates),
            default=0,
        )
        gap = latest - last_ch if latest > 0 else 0
        if gap >= 8:
            suggestions.append(
                f"Thread '{name}' has been dormant "
                f"for {gap} chapters — "
                f"resolve or advance it")

    # Characters with recent emotional extremes
    emo = state.get("emotional_deltas", {})
    chars = state.get("characters", {})
    for cid, entries in emo.items():
        recent = [e for e in entries
                  if e.get("chapter", 0) >= latest - 3]
        for entry in recent:
            for dim, val in entry.get("deltas", {}).items():
                if dim == "evidence":
                    continue
                if abs(val) >= 0.25:
                    name = _resolve_display_name(cid, chars)
                    direction = ("spiking" if val > 0
                                 else "crashing")
                    suggestions.append(
                        f"{name}'s {dim} is {direction} "
                        f"({val:+.2f}) — "
                        f"follow up on this")
                    break

    # Dead characters still referenced
    for cid, cdata in chars.items():
        status = (cdata.get("status") or "").lower()
        if status in ("dead", "deceased", "killed"):
            updates = cdata.get("updates", [])
            recent = [u for u in updates
                      if u.get("chapter", 0) >= latest - 3]
            if recent:
                name = cdata.get("display_name", cid)
                suggestions.append(
                    f"'{name}' is dead but was referenced "
                    f"recently — flashback or resurrection?")

    if suggestions:
        for s in suggestions[:6]:
            lines.append(f"    → {s}")
    else:
        lines.append("    No urgent items detected.")

    lines.append("")
    return lines


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def generate_recap(n: int = 10) -> str:
    """
    Build and print a full story recap.
    Returns the recap as a string.
    """
    if not os.path.exists(config.STORY_STATE_FILE):
        msg = ("No story_state.json found. "
               "Run 'extract' first.")
        print(msg)
        return msg

    state = load_json(config.STORY_STATE_FILE)

    chapters = state.get("metadata", {}).get(
        "chapters_processed", [])
    recent_chapters = set(sorted(chapters)[-n:])

    lines: list[str] = []

    lines.extend(_section_header(state, n))
    lines.extend(_section_recent_events(state, recent_chapters))
    lines.extend(_section_active_threads(state))
    lines.extend(_section_character_states(
        state, recent_chapters))
    lines.extend(_section_relationship_highlights(
        state, recent_chapters))
    lines.extend(_section_emotional_snapshot(
        state, recent_chapters))
    lines.extend(_section_unresolved(state))
    lines.extend(_section_conflicts(state))
    lines.extend(_section_whats_next(state))

    lines.append("═" * 60)
    lines.append("")

    output = "\n".join(lines)
    print(output)
    return output
