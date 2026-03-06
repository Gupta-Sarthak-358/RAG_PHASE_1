import os
import json
import glob
import re

log_dir = "/home/satvi/RAG_PHASE_1/logs/extraction_failures"
files = glob.glob(os.path.join(log_dir, "*.txt"))

def get_json_part(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    parts = content.split("==================================================\n\n")
    if len(parts) > 1:
        return parts[1]
    return ""

errors = {}
ok_files = 0
total_files = len(files)

for f in sorted(files):
    j_str = get_json_part(f).strip()
    if not j_str: continue
    
    # Extract from fences if present
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", j_str)
    if match:
        j_str = match.group(1).strip()
        
    try:
        json.loads(j_str)
        ok_files += 1
    except json.JSONDecodeError as e:
        filename = os.path.basename(f)
        chapter = filename.split('_')[1]
        
        # Get context around error
        lines = j_str.split('\n')
        err_line = e.lineno - 1
        
        context_start = max(0, err_line - 2)
        context_end = min(len(lines), err_line + 3)
        context = "\n".join(lines[context_start:context_end])
        
        if chapter not in errors:
            errors[chapter] = []
        errors[chapter].append((filename, str(e), context))

print(f"Total files: {total_files}")
print(f"Valid JSON files: {ok_files}")
print(f"Files with Decode Errors: {total_files - ok_files}")

for chapter, err_list in sorted(errors.items()):
    print(f"\nChapter {chapter}:")
    for filename, err_msg, context in err_list:
        print(f"  {filename} -> {err_msg}")
        print("  Context:")
        for line in context.split('\n'):
            print(f"    {line}")
