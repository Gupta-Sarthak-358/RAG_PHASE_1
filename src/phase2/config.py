"""
Phase 2 configuration.  Imports Phase 1 config and adds new settings.
No Phase 1 modifications required.
"""

import os
from phase1 import config  # Phase 1 — paths, model settings, etc.

# ──────────────────────────────────────────────────────────────────
# Phase 2 Model (Narrative Engine - Mistral)
# ──────────────────────────────────────────────────────────────────
PHASE2_MODEL_NAME = "mistral-7b-instruct"
PHASE2_MODEL_PATH = os.environ.get(
    "PHASE2_MODEL_PATH",
    os.path.join(config._ROOT, "models", "mistral-7b-instruct-v0.2.Q4_K_M.gguf"),
)
PHASE2_TEMPERATURE = 0.7
PHASE2_MAX_TOKENS = 2500
PHASE2_TOP_P = 0.92

# ──────────────────────────────────────────────────────────────────
# Directories
# ──────────────────────────────────────────────────────────────────
OUTLINES_DIR    = os.path.join(config.OUTPUT_DIR, "outlines")
DRAFTS_DIR      = os.path.join(config.OUTPUT_DIR, "drafts")
VALIDATIONS_DIR = os.path.join(config.OUTPUT_DIR, "validations")

for _d in (OUTLINES_DIR, DRAFTS_DIR, VALIDATIONS_DIR):
    os.makedirs(_d, exist_ok=True)

# ──────────────────────────────────────────────────────────────────
# State files
# ──────────────────────────────────────────────────────────────────
THREAD_HEALTH_FILE  = os.path.join(config.OUTPUT_DIR, "thread_health_state.json")
TENSION_STATE_FILE  = os.path.join(config.OUTPUT_DIR, "tension_state.json")
EMOTIONAL_STATE_FILE = os.path.join(config.OUTPUT_DIR, "emotional_state.json")

# ──────────────────────────────────────────────────────────────────
# Thread health
# ──────────────────────────────────────────────────────────────────
DORMANCY_THRESHOLDS: dict[int, int] = {
    5: 3,
    4: 5,
    3: 8,
    2: 12,
    1: 20,
}
DEFAULT_IMPORTANCE       = 3
PRESSURE_DIVISOR         = 2.0   # pressure = since_touched / (threshold * divisor)
CONVERGENCE_PRESSURE     = 0.6
RESOLUTION_WINDOW_PRESSURE = 0.8

# ──────────────────────────────────────────────────────────────────
# Tension model
# ──────────────────────────────────────────────────────────────────
SPIKE_THRESHOLD          = 0.15
STAGNATION_WINDOW        = 4
STAGNATION_DELTA         = 0.05
MIN_CHAPTERS_BEFORE_CLIMAX = 5
COOLDOWN_MIN_DROP        = 0.10
DEFAULT_INITIAL_TENSION  = 0.30

# ──────────────────────────────────────────────────────────────────
# Emotional model
# ──────────────────────────────────────────────────────────────────
EMOTIONAL_DIMENSIONS     = ("hope", "fear", "anger", "trust", "grief")
EMOTIONAL_DEFAULT        = 0.5
MAX_EMOTIONAL_DELTA      = 0.30
TRIGGER_EVENT_THRESHOLD  = 0.20

# ──────────────────────────────────────────────────────────────────
# Generation
# ──────────────────────────────────────────────────────────────────
OUTLINE_TEMPERATURE      = 0.15
EXPANSION_TEMPERATURE    = 0.30
SCENE_WORD_TARGET        = 350
VALIDATOR_TEMPERATURE    = 0.10

# ──────────────────────────────────────────────────────────────────
# Forecasting
# ──────────────────────────────────────────────────────────────────
FORECAST_HORIZON         = 3   # chapters ahead

# ---------------------------------------------------------------------------
# RAG retrieval knobs (Priority 5 — moved from hardcoded values)
# ---------------------------------------------------------------------------
RAG_TOP_K_OUTLINE   = 3   # scene-level RAG hits for the outline planner
RAG_TOP_K_EXPANDER  = 2   # RAG hits per scene during expansion
CONTINUITY_SENTENCES = 2  # trailing sentences carried forward between scenes
