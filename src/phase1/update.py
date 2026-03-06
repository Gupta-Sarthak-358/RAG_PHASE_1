import re
import os

with open('phase 1 rag more.txt', 'r', encoding='utf-8') as f:
    text = f.read()

config_code = re.search(r'## `config\.py`\s+```python\n(.*?)```', text, re.DOTALL).group(1).strip()
canon_merger_code = re.search(r'## `canon_merger\.py`\s+```python\n(.*?)```', text, re.DOTALL).group(1).strip()
main_code = re.search(r'## `main\.py`\s+```python\n(.*?)```', text, re.DOTALL).group(1).strip()

# Fix config.py to include MODEL_GPU_LAYERS
config_code = config_code.replace(
    "MODEL_THREADS = max(os.cpu_count() - 1, 1)",
    "MODEL_THREADS = max(os.cpu_count() - 1, 1)\nMODEL_GPU_LAYERS = int(os.environ.get(\"MODEL_GPU_LAYERS\", 35))"
)

# Fix canon_merger.py - Remove Pass 2 from _find_character_id
canon_merger_code = re.sub(
    r'    # ── Pass 2: significant-word overlap.*?return max\(\.\.\.\)', 
    '', 
    canon_merger_code, 
    flags=re.DOTALL
)
# Actually, the regex needs to specifically target the Pass 2 block before _resolve_char_id
pass2_start = canon_merger_code.find('    # ── Pass 2: significant-word overlap')
pass2_end = canon_merger_code.find('def _resolve_char_id(', pass2_start)
if pass2_start != -1 and pass2_end != -1:
    canon_merger_code = canon_merger_code[:pass2_start] + "    return None, False\n\n\n" + canon_merger_code[pass2_end:]


# Fix canon_merger.py - _relationship_event_exists inclusion of intensity and visibility
rel_exist_old = '''def _relationship_event_exists(state: dict, event: dict) -> bool:
    """Dedup: same chapter + between + type."""
    for e in state.get("relationship_events", []):
        if (e.get("chapter") == event["chapter"]
                and e.get("between") == event["between"]
                and e.get("type") == event["type"]):
            return True
    return False'''

rel_exist_new = '''def _relationship_event_exists(state: dict, event: dict) -> bool:
    """Dedup: same chapter + between + type + intensity + visibility."""
    for e in state.get("relationship_events", []):
        if (e.get("chapter") == event["chapter"]
                and e.get("between") == event["between"]
                and e.get("type") == event["type"]
                and e.get("intensity") == event["intensity"]
                and e.get("visibility") == event["visibility"]):
            return True
    return False'''

canon_merger_code = canon_merger_code.replace(rel_exist_old, rel_exist_new)

# Add Issue 2 (Conflict logging for unknown character updates instead of auto-stubs) back
update_char_old = '''        cid = _resolve_char_id(name, chars, chapter)
        cs = chars[cid]
        _add_alias(cs, name)'''

update_char_new = '''        cid, ambiguous = _find_character_id(name, chars)
        if not cid:
            _log(
                conflicts,
                kind="unknown_character_update",
                chapter=chapter,
                character=name,
                detail=(
                    f"Update extracted for '{name}' in chapter {chapter}, "
                    f"but no such character exists. Update ignored. Manual resolution required."
                ),
            )
            continue
            
        cs = chars[cid]
        _add_alias(cs, name)'''
canon_merger_code = canon_merger_code.replace(update_char_old, update_char_new)


with open('config.py', 'w', encoding='utf-8') as f:
    f.write(config_code)

with open('canon_merger.py', 'w', encoding='utf-8') as f:
    f.write(canon_merger_code)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(main_code)

print("Files updated successfully!")
