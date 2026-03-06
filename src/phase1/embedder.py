"""
Chunk chapters into overlapping windows, embed with MiniLM, and
store in a FAISS IndexFlatIP (cosine via normalised vectors).
"""

import json
import os

import numpy as np

from phase1 import config
from io_utils import save_json
from logger import get_logger

log = get_logger(__name__)


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    """Split *text* into word-level chunks with overlap."""
    size = size or config.CHUNK_SIZE_WORDS
    overlap = overlap or config.CHUNK_OVERLAP_WORDS
    words = text.split()
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start + size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += size - overlap
    return chunks


def build_index(chapters: list[tuple[int, str]]) -> None:
    """
    Build and persist a FAISS index + metadata.

    Parameters
    ----------
    chapters : list of (chapter_number, full_text) tuples
    """
    # Deferred imports — heavy libraries only when needed
    import faiss
    from sentence_transformers import SentenceTransformer

    log.info(f"[embedder] Loading {config.EMBEDDING_MODEL} …")
    model = SentenceTransformer(config.EMBEDDING_MODEL)

    all_chunks: list[str] = []
    metadata: list[dict] = []

    for chapter_num, text in chapters:
        for i, chunk in enumerate(chunk_text(text)):
            all_chunks.append(chunk)
            metadata.append({
                "chapter": chapter_num,
                "chunk_index": i,
                "text": chunk,
            })

    if not all_chunks:
        log.info("[embedder] Nothing to index.")
        return

    log.info(f"[embedder] Encoding {len(all_chunks)} chunks …")
    embeddings = model.encode(
        all_chunks, show_progress_bar=True, normalize_embeddings=True
    )
    embeddings = np.asarray(embeddings, dtype="float32")

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    idx_path = os.path.join(config.INDEX_DIR, "chapters.index")
    meta_path = os.path.join(config.INDEX_DIR, "chunks_metadata.json")

    faiss.write_index(index, idx_path)
    save_json(meta_path, metadata)

    log.info(f"[embedder] Saved {len(all_chunks)} chunks → {idx_path}")
