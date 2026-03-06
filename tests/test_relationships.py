import pytest
import src.phase1.config as config
from src.phase1.canon.merger.relationship_manager import RelationshipManager
from src.phase1.canon.merger.core import _empty_state

def test_compute_rel_state():
    state = _empty_state()
    mgr = RelationshipManager(state, [])
    
    # Below interaction threshold
    assert mgr.compute_rel_state({"trust_gain": 1}, [{"event": "trust_gain"}]) == "neutral"
    
    # Meet threshold (e.g. 2 trust_gain -> friend)
    assert mgr.compute_rel_state(
        {"trust_gain": 2}, 
        [{"event": "trust_gain"}, {"event": "trust_gain"}]
    ) == "friend"
    
    # Instant flip (e.g. betrayal -> enemy)
    assert mgr.compute_rel_state(
        {"betrayal": 1}, 
        [{"event": "met"}, {"event": "betrayal"}]
    ) == "enemy"
