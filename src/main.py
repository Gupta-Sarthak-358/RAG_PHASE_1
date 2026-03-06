#!/usr/bin/env python3
"""
CLI entry point for the Phase-1 canon engine.

Commands
--------
  python main.py extract          Extract canon from all new chapters
  python main.py build_index      Build FAISS embeddings index
  python main.py summary          Generate Canon_Bible_Summary.txt
  python main.py query "…"        Retrieve relevant chunks
  python main.py reprocess [N]    Re-extract last N chapters (default 5)
  python main.py migrate          Migrate character IDs to stable format
  python main.py normalize        Run global character deduplication
  python main.py recap [N]        Story recap — last N chapters (default 10)
"""

import sys
import time


# -----------------------------------------------------------------------
# extract
# -----------------------------------------------------------------------
def cmd_extract():
    from phase1.file_processor import scan_new_chapters, read_chapter, mark_processed
    from phase1.extractor import extract_chapter
    from phase1.canon.merger.canon_merger import merge_chapter

    chapters = scan_new_chapters()
    if not chapters:
        print("Nothing new to process.")
        return

    print(f"Found {len(chapters)} unprocessed chapter(s)\n")

    for ch_num, path in chapters:
        print(f"━━━ Chapter {ch_num} ━━━")
        print(f"  file  : {path}")

        text = read_chapter(path)
        wc = len(text.split())
        print(f"  words : {wc}")

        t0 = time.time()
        extraction = extract_chapter(ch_num, text)
        dt = time.time() - t0

        if extraction is None:
            print("  SKIPPED (extraction failed)\n")
            continue

        nc = len(extraction.get("new_characters", []))
        cu = len(extraction.get("character_updates", []))
        me = len(extraction.get("major_events", []))
        nt = len(extraction.get("new_plot_threads", []))
        rt = len(extraction.get("resolved_plot_threads", []))
        re_count = len(extraction.get("relationship_events", []))
        ed = len(extraction.get("emotional_deltas", {}))
        tp = len(extraction.get("thread_progression", []))
        print(f"  extracted in {dt:.1f}s — "
              f"chars={nc} updates={cu} events={me} "
              f"threads+={nt} threads✓={rt} "
              f"rel_events={re_count} emo_deltas={ed} "
              f"thread_prog={tp}")

        merge_chapter(extraction)
        mark_processed(ch_num)
        print(f"  ✓ merged\n")

    print(f"Done — {len(chapters)} chapter(s) processed.")


# -----------------------------------------------------------------------
# reprocess
# -----------------------------------------------------------------------
def cmd_reprocess(n: int = 5):
    from phase1.file_processor import get_processed_sorted, unmark_chapters
    from phase1.canon.merger.canon_merger import purge_chapter

    processed = get_processed_sorted()
    if not processed:
        print("No processed chapters found.")
        return

    last_n = processed[-n:]
    print(f"Reprocessing last {len(last_n)} chapter(s): {last_n}\n")

    for ch in last_n:
        purge_chapter(ch)

    unmark_chapters(last_n)

    cmd_extract()


# -----------------------------------------------------------------------
# migrate
# -----------------------------------------------------------------------
def cmd_migrate():
    from phase1.canon.merger.canon_merger import migrate_to_stable_ids
    migrate_to_stable_ids()


# -----------------------------------------------------------------------
# normalize
# -----------------------------------------------------------------------
def cmd_normalize():
    from phase1.normalizer import run_global_normalization
    run_global_normalization()


# -----------------------------------------------------------------------
# recap
# -----------------------------------------------------------------------
def cmd_recap(n: int = 10):
    from phase1.recap import generate_recap
    generate_recap(n)


# -----------------------------------------------------------------------
# build_index
# -----------------------------------------------------------------------
def cmd_build_index():
    from phase1.file_processor import get_all_chapters
    from phase1.embedder import build_index

    chapters = get_all_chapters()
    if not chapters:
        print("No chapters found.")
        return

    print(f"Indexing {len(chapters)} chapter(s) …")
    build_index(chapters)


# -----------------------------------------------------------------------
# summary
# -----------------------------------------------------------------------
def cmd_summary():
    from phase1.summarizer import generate_summary
    generate_summary()


# -----------------------------------------------------------------------
# query
# -----------------------------------------------------------------------
def cmd_query(query_text: str):
    from phase1.retriever import Retriever

    r = Retriever()
    results = r.query(query_text)

    print(f'\nQuery: "{query_text}"')
    print(f"Top {len(results)} result(s):\n")

    for hit in results:
        print(f"─── Ch {hit['chapter']}  chunk {hit['chunk_index']}  "
              f"score {hit['score']:.4f} ───")
        words = hit["text"].split()
        print(" ".join(words[:200]) + (" …" if len(words) > 200 else ""))
        print()


# -----------------------------------------------------------------------
# snapshot
# -----------------------------------------------------------------------
def cmd_snapshot():
    from phase1.snapshot import generate_snapshot
    generate_snapshot()

# -----------------------------------------------------------------------
# main
# -----------------------------------------------------------------------
def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="""Story Canon Engine — Unified CLI

Phase 1 (canon) commands:
  extract          Extract canon from all new chapters
  reprocess [N]    Re-extract last N chapters (default 5)
  build_index      Build FAISS semantic search index
  summary          Generate Canon_Bible_Summary.txt
  query "<text>"   Semantic search across chapters
  migrate          Migrate character IDs to stable format
  normalize        Run global character deduplication
  recap [N]        Story recap — last N chapters (default 10)
  snapshot         World state snapshot

Phase 2 (story) commands — prefix with 'story':
  story init                         Initialise Phase 2 state
  story outline <ch> "<direction>"   Generate chapter outline
  story approve <ch>                 Approve outline
  story expand <ch>                  Expand to full draft
  story validate <ch>                Validate draft vs outline
  story update <ch>                  Update state post-canonisation
  story dashboard                    One-glance narrative overview
  story metrics                      Full telemetry panel
  story forecast                     3-chapter projection
  story inspect <target>             Dump raw state file
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # ── Phase 1 sub-commands ─────────────────────────────────────────────────
    subparsers.add_parser("extract",     help="Extract canon from all new chapters")
    subparsers.add_parser("build_index", help="Build FAISS embeddings index")
    subparsers.add_parser("summary",     help="Generate Canon_Bible_Summary.txt")
    subparsers.add_parser("migrate",     help="Migrate character IDs to stable format")
    subparsers.add_parser("normalize",   help="Run global character deduplication")
    subparsers.add_parser("snapshot",    help="Generate a world state snapshot")

    p_reprocess = subparsers.add_parser("reprocess", help="Re-extract last N chapters")
    p_reprocess.add_argument("n", type=int, nargs="?", default=5)

    p_query = subparsers.add_parser("query", help="Retrieve relevant chunks")
    p_query.add_argument("query_text", type=str)

    p_recap = subparsers.add_parser("recap", help="Story recap — last N chapters")
    p_recap.add_argument("n", type=int, nargs="?", default=10)

    # ── Phase 2 'story' sub-command group ───────────────────────────────────
    # Usage:  python main.py story <subcommand> [args...]
    # All story subcommands are forwarded to phase2_main via passthrough.
    p_story = subparsers.add_parser(
        "story",
        help="Phase 2 story commands (outline, expand, validate, dashboard, …)",
        description="Phase 2 Narrative Engine commands.",
        add_help=False,  # let phase2_main handle its own help
    )
    p_story.add_argument("story_args", nargs=argparse.REMAINDER,
                         help="Subcommand + arguments forwarded to phase2_main")

    # ── Dispatch ─────────────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.cmd == "extract":     cmd_extract()
    elif args.cmd == "reprocess": cmd_reprocess(args.n)
    elif args.cmd == "build_index": cmd_build_index()
    elif args.cmd == "summary":   cmd_summary()
    elif args.cmd == "query":     cmd_query(args.query_text)
    elif args.cmd == "migrate":   cmd_migrate()
    elif args.cmd == "normalize": cmd_normalize()
    elif args.cmd == "recap":     cmd_recap(args.n)
    elif args.cmd == "snapshot":  cmd_snapshot()

    elif args.cmd == "story":
        # Forward all story subcommands to phase2_main
        import subprocess, os
        p2_main = os.path.join(os.path.dirname(__file__), "phase2_main.py")
        story_cmd = args.story_args if args.story_args else ["--help"]
        result = subprocess.run([sys.executable, p2_main] + story_cmd)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()