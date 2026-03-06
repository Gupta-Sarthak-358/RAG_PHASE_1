#!/usr/bin/env python3
"""Quick import auditor — checks that all source modules can be imported cleanly."""
import sys, importlib

sys.path.insert(0, "src")

modules = [
    "io_utils", "logger",
    "phase1.config",
    "phase1.model_loader",
    "phase1.file_processor",
    "phase1.extractor",
    "phase1.normalizer",
    "phase1.embedder",
    "phase1.retriever",
    "phase1.recap",
    "phase1.snapshot",
    "phase1.summarizer",
    "phase1.canon.merger.core",
    "phase1.canon.merger.cleanup",
    "phase1.canon.merger.character_manager",
    "phase1.canon.merger.relationship_manager",
    "phase1.canon.merger.thread_manager",
    "phase2.config",
    "phase2.planning.outline_planner",
    "phase2.planning.expander",
    "phase2.analysis.validator",
    "phase2.analysis.narrative_metrics",
    "phase2.state.emotional_state",
    "phase2.state.tension_model",
    "phase2.state.thread_health",
    "phase2.analysis.forecasting",
]

errors = []
for m in modules:
    try:
        importlib.import_module(m)
        print(f"  OK  {m}")
    except Exception as e:
        print(f"  ERR {m}: {e}")
        errors.append((m, str(e)))

print(f"\n{'='*60}")
print(f"Result: {len(errors)} error(s) in {len(modules)} modules.")
if errors:
    for m, e in errors:
        print(f"  - {m}: {e}")
