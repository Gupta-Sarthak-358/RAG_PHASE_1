import pytest
from src.phase1.canon.merger.thread_manager import ThreadManager
from src.phase1.canon.merger.core import _empty_state

def test_auto_archive_thread():
    state = _empty_state()
    mgr = ThreadManager(state, [])
    
    # Active thread, last update in chapter 5
    mgr.threads["active_thread"] = {
        "status": "unresolved",
        "introduced": 1,
        "updates": [{"chapter": 5, "detail": "Test update"}]
    }
    
    # Dormant thread, last update in chapter 2
    mgr.threads["dormant_thread"] = {
        "status": "unresolved",
        "introduced": 1,
        "updates": [{"chapter": 2, "detail": "Test update"}]
    }
    
    # Run update at chapter 25 (dormant thread should archive)
    extraction = {
        "chapter_number": 25,
        "new_plot_threads": [],
        "resolved_plot_threads": [],
        "thread_progression": [] # Empty progression
    }
    
    mgr.update(extraction)
    
    assert mgr.threads["active_thread"]["status"] == "unresolved"
    assert mgr.threads["dormant_thread"]["status"] == "archived"
