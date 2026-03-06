"""
Central configuration for the canon engine.
All paths, model settings, and tuning knobs live here.
"""

import os

# Project root = 3 levels above this file (src/phase1/config.py)
_PHASE1_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_PHASE1_DIR)
_ROOT = os.path.dirname(_SRC_DIR)

def _p(*parts: str) -> str:
    """Return an absolute path anchored at the project root."""
    return os.path.join(_ROOT, *parts)

# ---------------------------------------------------------------------------
# Model Hardware Settings (Shared)
# ---------------------------------------------------------------------------
MODEL_CONTEXT = 8192
MODEL_THREADS = max(os.cpu_count() - 1, 1)
MODEL_SEED = 42
MODEL_GPU_LAYERS = -1   # -1 = offload all layers to GPU; set to 0 to disable GPU

# ---------------------------------------------------------------------------
# Phase 1 Model (Canon Extraction - Qwen)
# ---------------------------------------------------------------------------
PHASE1_MODEL_NAME = "qwen2.5-7b-instruct"
PHASE1_MODEL_PATH = os.environ.get(
    "PHASE1_MODEL_PATH",
    _p("models", "qwen2.5-7b-instruct-q4_k_m.gguf"),
)
PHASE1_TEMPERATURE = 0.1
PHASE1_MAX_TOKENS = 1200
PHASE1_TOP_P = 0.9

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
CHAPTERS_DIR = os.environ.get("CHAPTERS_DIR", _p("chapters"))
OUTPUT_DIR   = os.environ.get("OUTPUT_DIR",   _p("output"))
INDEX_DIR              = _p("output", "index")
EXTRACTION_FAILURE_DIR = _p("logs", "extraction_failures")

# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------
CANON_DIR           = _p("output", "canon")
CHARACTERS_FILE     = _p("output", "canon", "characters.json")
ABILITIES_FILE      = _p("output", "canon", "abilities.json")
RELATIONSHIPS_FILE  = _p("output", "canon", "relationships.json")
UPDATES_FILE        = _p("output", "canon", "updates.json")

STORY_STATE_FILE    = _p("output", "story_state.json")
CONFLICT_LOG_FILE   = _p("output", "conflict_log.json")
PROCESSED_FILE      = _p("output", "processed_chapters.json")
CANON_SUMMARY_FILE  = _p("output", "Canon_Bible_Summary.txt")
ID_COUNTER_FILE     = _p("output", "id_counter.json")

# ---------------------------------------------------------------------------
# Chunking (for FAISS embeddings)
# ---------------------------------------------------------------------------
CHUNK_SIZE_WORDS = 500
CHUNK_OVERLAP_WORDS = 100

# ---------------------------------------------------------------------------
# Extraction safety
# ---------------------------------------------------------------------------
MAX_CHAPTER_WORDS = 5000

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TOP_K = 5

# ---------------------------------------------------------------------------
# Emotional extraction (Phase 1 storage only)
# ---------------------------------------------------------------------------
EMOTIONAL_DIMENSIONS = ("hope", "fear", "anger", "trust", "grief")
MAX_EMOTIONAL_DELTA = 0.3

# ---------------------------------------------------------------------------
# Thread progression
# ---------------------------------------------------------------------------
VALID_THREAD_STATUSES = (
    "advanced", "escalated", "complicated", "stalled", "resolved",
)

# ---------------------------------------------------------------------------
# Character name validation
# ---------------------------------------------------------------------------
NAME_MAX_WORDS = 3

NAME_REJECT_PREFIXES = (
    "the ", "a ", "an ", "some ", "several ",
    "those ", "these ", "fake ", "unknown ",
)

NAME_REJECT_WORDS = frozenset({
    "group", "team", "ninjas", "shinobi", "leader", "captain",
    "kunoichi", "jonin", "chunin", "genin", "commander", "squad",
    "clan", "forces", "troops", "guards", "villagers", "elders",
    "council", "anbu", "division", "unit", "civilians", "soldiers",
    "agents", "members", "warriors", "assassins", "mercenaries",
    "spies", "scouts", "medics", "fake", "missing", "rogue",
})

NAME_PURE_ROLES = frozenset({
    "jonin", "chunin", "genin", "hokage", "kazekage", "raikage",
    "mizukage", "tsuchikage", "anbu", "sensei", "captain",
    "commander", "elder", "leader", "medic", "sannin",
    "jinchuriki", "kage", "daimyo",
})

# ---------------------------------------------------------------------------
# Relationship system
# ---------------------------------------------------------------------------
REL_TYPES = frozenset({
    "ally", "enemy", "mentor", "student",
    "friend", "romantic", "family", "rival",
})

REL_EVENT_TYPES = frozenset({
    "met", "confession", "kiss", "argument",
    "alliance", "betrayal", "trust_gain", "trust_loss",
    "romantic_progression", "cooperation",
})

REL_LABEL_TO_TYPE: dict[str, str] = {
    "father": "family", "mother": "family", "parent": "family",
    "brother": "family", "sister": "family", "sibling": "family",
    "son": "family", "daughter": "family", "child": "family",
    "uncle": "family", "aunt": "family", "cousin": "family",
    "grandfather": "family", "grandmother": "family",
    "grandson": "family", "granddaughter": "family",
    "relative": "family", "clan member": "family",
    "spouse": "romantic", "wife": "romantic", "husband": "romantic",
    "fiance": "romantic", "fiancee": "romantic",
    "lover": "romantic", "romantic partner": "romantic",
    "girlfriend": "romantic", "boyfriend": "romantic",
    "love interest": "romantic", "beloved": "romantic",
    "teacher": "mentor", "sensei": "mentor",
    "master": "mentor", "instructor": "mentor",
    "apprentice": "student", "pupil": "student",
    "disciple": "student",
    "teammate": "ally", "comrade": "ally",
    "companion": "ally", "allies": "ally",
    "nemesis": "enemy", "foe": "enemy",
    "best friend": "friend", "close friend": "friend",
    "childhood friend": "friend",
    "competitor": "rival",
}

REL_EVENT_PROMOTION: dict[str, str | None] = {
    "confession": "romantic",
    "kiss": "romantic",
    "romantic_progression": "romantic",
    "alliance": "ally",
    "betrayal": "enemy",
    "trust_gain": None,
    "trust_loss": None,
    "met": None,
    "argument": None,
    "cooperation": None,
}

# ---------------------------------------------------------------------------
# Relationship repetition thresholds
# ---------------------------------------------------------------------------
# How many signals of each type are needed before the state changes.
# Events below the threshold are recorded in history but don't change state.
REL_SIGNAL_THRESHOLDS: dict[str, tuple[int, str]] = {
    # event_type            : (min_count, resulting_state)
    "betrayal"              : (1, "enemy"),       # instant flip
    "romantic_progression"  : (2, "romantic"),
    "kiss"                  : (1, "romantic"),     # single kiss = instant
    "confession"            : (1, "romantic"),     # single confession = instant
    "cooperation"           : (2, "ally"),
    "alliance"              : (1, "ally"),         # explicit alliance = instant
    "trust_gain"            : (2, "friend"),
    "argument"              : (3, "conflict"),
    "trust_loss"            : (3, "rival"),
}

# Minimum total interactions before any state change is allowed.
# Prevents met + argument = enemy in a single chapter.
REL_MIN_INTERACTIONS = 2


# ---------------------------------------------------------------------------
# Evidence verification
# ---------------------------------------------------------------------------
EVIDENCE_MIN_WORDS = 3
EVIDENCE_FUZZY_THRESHOLD = 0.6

# ---------------------------------------------------------------------------
# Relationship priority (higher = stronger bond)
# Used to prevent relationship downgrades during merge
# ---------------------------------------------------------------------------
REL_PRIORITY: dict[str, int] = {
    "family": 7,
    "romantic": 6,
    "mentor": 5,
    "student": 5,
    "rival": 4,
    "ally": 3,
    "friend": 2,
    "enemy": 1,
}

# ---------------------------------------------------------------------------
# Fuzzy matching thresholds (0–100 scale)
# ---------------------------------------------------------------------------
FUZZY_NAME_THRESHOLD = 92       # character name matching
FUZZY_ABILITY_THRESHOLD = 85    # ability deduplication
FUZZY_EVENT_THRESHOLD = 80      # event deduplication
FUZZY_THREAD_THRESHOLD = 80     # thread deduplication

# ---------------------------------------------------------------------------
# Ability normalisation (noise words removed before comparison)
# ---------------------------------------------------------------------------
ABILITY_NOISE_WORDS = frozenset({"technique", "jutsu", "no"})

# ---------------------------------------------------------------------------
# Create directories on import
# ---------------------------------------------------------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(INDEX_DIR, exist_ok=True)
os.makedirs(EXTRACTION_FAILURE_DIR, exist_ok=True)
os.makedirs(CANON_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Thread archival (Priority 5 — moved from hardcoded value in thread_manager)
# ---------------------------------------------------------------------------
THREAD_ARCHIVE_THRESHOLD = 20  # chapters of inactivity before auto-archive
