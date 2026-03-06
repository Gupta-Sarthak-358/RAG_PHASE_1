from phase1 import config
from phase1.file_processor import get_processed_sorted
from phase1.canon.merger.core import load_canon

def generate_snapshot():
    state = load_canon()
    chars = state.get("characters", {})
    threads = state.get("plot_threads", {})
    processed = get_processed_sorted()
    latest_chapter = processed[-1] if processed else 0
    
    print("=== CANON ENGINE: STORY SNAPSHOT ===\n")
    print(f"Latest Processed Chapter: {latest_chapter}")
    print(f"Total Characters Tracked: {len(chars)}")
    
    print("\n[ Active Conflicts & Threads ]")
    active_threads = 0
    for tname, tdata in threads.items():
        if tdata.get("status") not in ["resolved", "archived"]:
            active_threads += 1
            print(f"- {tname} (Since Ch {tdata.get('introduced')})")
            print(f"  {tdata.get('description')}")
    if active_threads == 0:
        print("  None.")
        
    print("\n[ Power Factions & Political Situation ]")
    active_chars = []
    for cid, cdata in chars.items():
        if cdata.get("status") in ["alive", "active"]:
            active_chars.append(cdata.get("display_name", cid))
    print(f"Known Active Key Figures ({len(active_chars)}): {', '.join(active_chars)}")
    print("\nSnapshot generated.")
