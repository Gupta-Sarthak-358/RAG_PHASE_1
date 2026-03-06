"""
Lightweight 3-chapter projection.
Tension trajectory, escalating threads, resolution pressure,
collision probability.  Pure heuristics — no LLM calls.
"""

from __future__ import annotations

from copy import deepcopy

from phase2 import config as p2
from phase2.state.thread_health import ThreadHealthTracker
from phase2.state.tension_model import TensionTracker


# ──────────────────────────────────────────────────────────────────
# Projection helpers
# ──────────────────────────────────────────────────────────────────

def _project_tension(tracker: TensionTracker, horizon: int) -> list[dict]:
    """Project tension values by extending recent trend."""
    current = tracker.current
    trend   = tracker.trend
    hist    = tracker.history

    # average delta over last 3 data points
    recent_deltas = [h.get("delta", 0) for h in hist[-3:]] if hist else [0]
    avg_delta = sum(recent_deltas) / len(recent_deltas)

    projections = []
    t = current
    for i in range(1, horizon + 1):
        t = round(max(0.0, min(1.0, t + avg_delta)), 3)
        phase = tracker.state["arc_phase"]  # simplified — keep current phase
        if t >= 0.80:
            phase = "climax"
        elif t >= 0.60:
            phase = "pre_climax"
        elif t < 0.30:
            phase = "setup"
        projections.append({
            "chapter_offset": i,
            "projected_tension": t,
            "projected_phase": phase,
            "delta_used": round(avg_delta, 3),
        })
    return projections


def _project_threads(
    tracker: ThreadHealthTracker, horizon: int
) -> dict[str, list[dict]]:
    """Project thread pressure forward."""
    escalating:  list[dict] = []
    nearing_res: list[dict] = []
    all_threads = tracker.get_all()

    for tname, entry in all_threads.items():
        if entry["status"] == "resolved":
            continue

        imp  = entry["importance"]
        since = entry["chapters_since_touched"]
        threshold = p2.DORMANCY_THRESHOLDS.get(imp, 10)

        # project pressure at each future chapter
        future_pressures = []
        for i in range(1, horizon + 1):
            future_since = since + i
            pres = min(1.0, future_since / (threshold * p2.PRESSURE_DIVISOR))
            future_pressures.append(round(pres, 3))

        # will it escalate? (pressure crosses 0.6)
        if entry["resolution_pressure"] < 0.6 and any(p >= 0.6 for p in future_pressures):
            ch_offset = next(i + 1 for i, p in enumerate(future_pressures) if p >= 0.6)
            escalating.append({
                "thread": tname,
                "importance": imp,
                "current_pressure": entry["resolution_pressure"],
                "escalates_in": ch_offset,
            })

        # nearing forced resolution (pressure > 0.85)
        if any(p >= 0.85 for p in future_pressures):
            ch_offset = next(i + 1 for i, p in enumerate(future_pressures) if p >= 0.85)
            nearing_res.append({
                "thread": tname,
                "importance": imp,
                "current_pressure": entry["resolution_pressure"],
                "critical_in": ch_offset,
            })

    return {"escalating": escalating, "nearing_resolution": nearing_res}


def _collision_probability(tracker: ThreadHealthTracker, horizon: int) -> dict:
    """
    Detect if multiple high-importance threads will need attention
    in the same window — a narrative collision risk.
    """
    threads = tracker.get_all()
    # count how many high-importance threads (>=4) are at pressure >= 0.5
    # and will cross 0.7 within the horizon
    hotspots: dict[int, list[str]] = {}  # offset → [thread names]

    for tname, entry in threads.items():
        if entry["status"] == "resolved":
            continue
        if entry["importance"] < 3:
            continue

        since = entry["chapters_since_touched"]
        threshold = p2.DORMANCY_THRESHOLDS.get(entry["importance"], 10)

        for i in range(1, horizon + 1):
            pres = min(1.0, (since + i) / (threshold * p2.PRESSURE_DIVISOR))
            if pres >= 0.7:
                hotspots.setdefault(i, []).append(tname)
                break

    collisions = {offset: names for offset, names in hotspots.items()
                  if len(names) >= 2}

    if collisions:
        worst = max(collisions.items(), key=lambda kv: len(kv[1]))
        return {
            "risk": "high" if len(worst[1]) >= 3 else "moderate",
            "details": collisions,
            "note": (f"{len(worst[1])} threads converge around "
                     f"+{worst[0]} chapter(s)"),
        }
    return {"risk": "low", "details": {}, "note": "No collisions detected"}


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def forecast(horizon: int | None = None) -> dict:
    """
    Generate a lightweight projection.  Returns structured dict and
    prints a human-readable summary.
    """
    horizon = horizon or p2.FORECAST_HORIZON
    tension = TensionTracker()
    tracker = ThreadHealthTracker()

    ten_proj  = _project_tension(tension, horizon)
    thr_proj  = _project_threads(tracker, horizon)
    collision = _collision_probability(tracker, horizon)

    result = {
        "horizon": horizon,
        "tension_trajectory": ten_proj,
        "thread_projections": thr_proj,
        "collision_risk": collision,
    }

    # ── pretty print ─────────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print(f"║          F O R E C A S T   ({horizon}-chapter horizon)           ║")
    print("╚══════════════════════════════════════════════════════════╝")

    print("\n  ── Tension Trajectory ──")
    for tp in ten_proj:
        print(f"    +{tp['chapter_offset']} ch:  {tp['projected_tension']:.2f}  "
              f"({tp['projected_phase']})")

    print("\n  ── Threads Likely to Escalate ──")
    esc = thr_proj["escalating"]
    if esc:
        for e in esc:
            print(f"    • {e['thread']} (imp={e['importance']}, "
                  f"pressure={e['current_pressure']:.2f}) → "
                  f"escalates in {e['escalates_in']} ch")
    else:
        print("    (none)")

    print("\n  ── Threads Nearing Forced Resolution ──")
    nr = thr_proj["nearing_resolution"]
    if nr:
        for n in nr:
            print(f"    ⚠ {n['thread']} (imp={n['importance']}, "
                  f"pressure={n['current_pressure']:.2f}) → "
                  f"critical in {n['critical_in']} ch")
    else:
        print("    (none)")

    print(f"\n  ── Collision Risk: {collision['risk'].upper()} ──")
    print(f"    {collision['note']}")
    if collision["details"]:
        for offset, names in collision["details"].items():
            print(f"    +{offset} ch: {', '.join(names)}")

    conf = result.get("forecast_confidence", "moderate")
    conf_icon = {"high": "✓", "moderate": "~", "low": "⚠"}.get(conf, "~")
    print(f"\n  ── Forecast Confidence: {conf.upper()} {conf_icon} ──")
    if conf == "low":
        print("    ⚠ High tension volatility detected — forecast is advisory only.")

    print()
    return result
