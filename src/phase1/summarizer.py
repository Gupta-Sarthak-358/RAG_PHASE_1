"""
Read story_state.json → build a structured raw summary →
compress it with Mistral into Canon_Bible_Summary.txt (≤ 3 000 words).
"""

import json
import os

from phase1 import config
config.MODEL_GPU_LAYERS = -1

from phase1.model_loader import ModelLoader


def chunk_text(text: str, size: int = 2000):
    words = text.split()
    for i in range(0, len(words), size):
        yield " ".join(words[i:i + size])


# ---------------------------------------------------------------------------
# Build a plain-text dump from the state dict
# ---------------------------------------------------------------------------
def _raw_summary(state: dict) -> str:
    lines: list[str] = []

    # ---- Characters ----
    lines.append("=== CHARACTERS ===\n")
    for name in sorted(state.get("characters", {})):
        c = state["characters"][name]
        lines.append(f"■ {name}")
        lines.append(f"  First appearance : Chapter {c.get('first_appearance', '?')}")
        lines.append(f"  Status           : {c.get('status', 'unknown')}")
        if c.get("description"):
            lines.append(f"  Description      : {c['description']}")
        if c.get("abilities"):
            lines.append(f"  Abilities        : {', '.join(c['abilities'])}")
        if c.get("relationships"):
            rels = []
            for target_id, rel_data in c["relationships"].items():
                target_name = state.get("characters", {}).get(target_id, {}).get("display_name", target_id)
                rel_state = rel_data.get("state", "unknown")
                rels.append(f"{target_name} ({rel_state})")
            lines.append(f"  Relationships    : {', '.join(rels)}")
        # Key updates (last 5 to save space)
        updates = c.get("updates", [])
        if updates:
            for u in updates[-5:]:
                lines.append(f"    Ch {u.get('chapter', '?')}: {u.get('detail', '')}")
        lines.append("")

    # ---- Active plot threads ----
    lines.append("\n=== ACTIVE PLOT THREADS ===\n")
    for tname in sorted(state.get("plot_threads", {})):
        t = state["plot_threads"][tname]
        if t.get("status") == "resolved":
            continue
        lines.append(f"■ {tname}  (since Ch {t.get('introduced', '?')})")
        lines.append(f"  Status : {t.get('status', '?')}")
        lines.append(f"  {t.get('description', '')}")
        lines.append("")

    # ---- Resolved plot threads ----
    lines.append("\n=== RESOLVED PLOT THREADS ===\n")
    for tname in sorted(state.get("plot_threads", {})):
        t = state["plot_threads"][tname]
        if t.get("status") != "resolved":
            continue
        lines.append(f"■ {tname}  (Ch {t.get('introduced', '?')} → resolved)")
        lines.append(f"  {t.get('description', '')}")
        lines.append("")

    # ---- Timeline ----
    lines.append("\n=== TIMELINE OF MAJOR EVENTS ===\n")
    for ev in state.get("events", []):
        lines.append(f"  Ch {ev.get('chapter', '?'):>3}: {ev.get('event', '')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_summary() -> None:
    from phase1.canon.merger.cleanup import load_canon
    state = load_canon()
    if not state.get("characters"):
        print("No canon state found. Run 'extract' first.")
        return

    raw = _raw_summary(state)
    word_count = len(raw.split())
    print(f"[summary] Raw structured dump: {word_count} words")

    # If the dump already fits in the context window with room for output,
    # ask Mistral to compress it.  Otherwise use chunked summarization.
    if word_count > 6000:
        print("[summary] Large dump detected — using chunked summarization")
        chunks = list(chunk_text(raw, 2000))
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            print(f"[summary] Compressing chunk {i+1}/{len(chunks)} …")
            prompt = (
                "[INST] You are a story-bible editor. "
                f"Below is a section (part {i+1} of {len(chunks)}) of raw structured data about a story's characters, "
                "plot threads, and timeline.\n\n"
                "Compress this into a clean, readable summary section.\n\n"
                f"Source data:\n{chunk}\n\n"
                "Summary Section: [/INST]"
            )
            res = ModelLoader.safe_generate(
                config.PHASE1_MODEL_NAME,
                prompt + "\\n\\nReturn ONLY valid JSON. No explanation. Follow the schema exactly.",
            max_tokens=config.PHASE1_MAX_TOKENS,
            temperature=config.PHASE1_TEMPERATURE
        )
            chunk_summaries.append(res)
        
        combined_text = "\n\n".join(chunk_summaries)
        print("[summary] Performing final compression pass …")
        final_prompt = (
            "[INST] You are a story-bible editor. "
            "Below are combined summaries of a story's characters, plot threads, and timeline.\n\n"
            "Compress this into a clean, readable Canon Bible Summary. "
            "Use these sections:\n"
            "1. Character Guide (name, role, status, key traits)\n"
            "2. Active Plot Threads\n"
            "3. Resolved Plot Threads\n"
            "4. Timeline of Major Events\n\n"
            "Rules:\n"
            "- Stay strictly factual — do NOT add anything not in the data.\n"
            "- Keep the summary under 3000 words.\n\n"
            f"Source data:\n{combined_text}\n\n"
            "Canon Bible Summary: [/INST]"
        )
        final = ModelLoader.safe_generate(
            config.PHASE1_MODEL_NAME,
            final_prompt,
            max_tokens=config.PHASE1_MAX_TOKENS,
            temperature=config.PHASE1_TEMPERATURE,
        )

    else:
        prompt = (
            "[INST] You are a story-bible editor. "
            "Below is raw structured data about a story's characters, "
            "plot threads, and timeline.\n\n"
            "Compress this into a clean, readable Canon Bible Summary. "
            "Use these sections:\n"
            "1. Character Guide (name, role, status, key traits)\n"
            "2. Active Plot Threads\n"
            "3. Resolved Plot Threads\n"
            "4. Timeline of Major Events\n\n"
            "Rules:\n"
            "- Stay strictly factual — do NOT add anything not in the data.\n"
            "- Keep the summary under 3000 words.\n\n"
            f"Source data:\n{raw}\n\n"
            "Canon Bible Summary: [/INST]"
        )
        print("[summary] Compressing with Mistral …")
        final = ModelLoader.safe_generate(
            config.PHASE1_MODEL_NAME,
            prompt + "\\n\\nReturn ONLY valid JSON. No explanation. Follow the schema exactly.",
            max_tokens=config.PHASE1_MAX_TOKENS,
            temperature=config.PHASE1_TEMPERATURE
        )

    with open(config.CANON_SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(final)

    print(f"[summary] Written to {config.CANON_SUMMARY_FILE} "
          f"({len(final.split())} words)")
