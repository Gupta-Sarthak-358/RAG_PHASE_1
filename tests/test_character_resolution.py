import pytest
from src.phase1.canon.merger.character_manager import CharacterManager
from src.phase1.canon.merger.core import _empty_state
from phase1 import config

def test_resolve_char_id_exact(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ID_COUNTER_FILE", str(tmp_path / "id_counter.json"))
    state = _empty_state()
    mgr = CharacterManager(state, [])
    mgr.chars["char_0001"] = {
        "id": "char_0001",
        "display_name": "Akane Yanagi",
        "aliases": ["Akane"]
    }
    mgr._index_character("char_0001", mgr.chars["char_0001"])
    
    # Exact match
    cid1 = mgr.resolve_char_id("Akane", 1)
    assert cid1 == "char_0001"
    
    # New character
    cid2 = mgr.resolve_char_id("Kaguya", 1)
    assert cid2 == "char_0002"
    
    # Alias table override
    mgr.alias_table["kaguya otsutsuki"] = "char_0002"
    cid3 = mgr.resolve_char_id("Kaguya Otsutsuki", 1)
    assert cid3 == "char_0002"
