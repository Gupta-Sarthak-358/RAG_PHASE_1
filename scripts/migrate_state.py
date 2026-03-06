import json
import os
import sys

# Use absolute paths if running from root, otherwise adjust
INPUT = "output/story_state.json"
OUTPUT_DIR = "output/canon"

if not os.path.exists(INPUT):
    print(f"Error: Could not find {INPUT}. Are you running from the repository root?")
    sys.exit(1)

os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(INPUT, "r", encoding="utf-8") as f:
    state = json.load(f)

characters = {}
relationships = {}
abilities = {}
updates = {}

for cid, char in state.get("characters", {}).items():

    characters[cid] = {
        "display_name": char.get("display_name"),
        "aliases": char.get("aliases", []),
        "first_appearance": char.get("first_appearance"),
        "status": char.get("status"),
        "description": char.get("description")
    }

    abilities[cid] = char.get("abilities", [])

    relationships[cid] = char.get("relationships", {})

    updates[cid] = char.get("updates", [])


with open(f"{OUTPUT_DIR}/characters.json","w", encoding="utf-8") as f:
    json.dump(characters, f, indent=2, ensure_ascii=False)

with open(f"{OUTPUT_DIR}/abilities.json","w", encoding="utf-8") as f:
    json.dump(abilities, f, indent=2, ensure_ascii=False)

with open(f"{OUTPUT_DIR}/relationships.json","w", encoding="utf-8") as f:
    json.dump(relationships, f, indent=2, ensure_ascii=False)

with open(f"{OUTPUT_DIR}/updates.json","w", encoding="utf-8") as f:
    json.dump(updates, f, indent=2, ensure_ascii=False)

print("Migration complete. Splitting successful.")
