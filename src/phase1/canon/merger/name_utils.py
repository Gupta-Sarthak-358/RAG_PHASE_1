import re
from .core import _load, _save
from phase1 import config

_TITLE_PREFIXES = {
    "princess", "prince", "lady", "lord", "master",
    "captain", "commander", "konoha", "ninja", "shinobi"
}

_HONORIFIC_SUFFIXES = {
    "-sama", "-kun", "-chan", "-hime", "-sensei", "-senpai", "-dono"
}

FORCE_SEPARATE = {
    frozenset(["akane yanagi", "kana yanagi"])
}

def normalize_name(name: str) -> str:
    name = name.lower().strip()
    for h in _HONORIFIC_SUFFIXES:
        if name.endswith(h):
            name = name[:-len(h)]
    words = name.split()
    words = [w for w in words if w not in _TITLE_PREFIXES]
    return " ".join(words)

def split_name(name: str) -> tuple:
    parts = name.split()
    if not parts:
        return "", None
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else None
    return first, last

def same_character(name_a: str, name_b: str) -> bool:
    a = normalize_name(name_a)
    b = normalize_name(name_b)
    first_a, last_a = split_name(a)
    first_b, last_b = split_name(b)
    if not first_a or not first_b:
        return False
    if first_a != first_b:
        return False
    if last_a is None or last_b is None:
        return True
    return last_a == last_b

def load_id_counter() -> int:
    data = _load(config.ID_COUNTER_FILE, {"next_id": 1})
    return data.get("next_id", 1)

def save_id_counter(next_id: int):
    _save(config.ID_COUNTER_FILE, {"next_id": next_id})

def next_char_id(characters: dict) -> str:
    n = load_id_counter()
    used = set()
    for cid in characters:
        m = re.match(r"char_(\d+)$", cid)
        if m:
            used.add(int(m.group(1)))
    while n in used:
        n += 1
    save_id_counter(n + 1)
    return f"char_{n:04d}"

def add_alias(entry: dict, name: str) -> bool:
    name_lower = name.lower().strip()
    for existing in entry.get("aliases", []):
        if existing.lower().strip() == name_lower:
            return False
    entry.setdefault("aliases", []).append(name.strip())
    return True
