"""
Load the FAISS index and return top-k chunks for a free-text query.
"""

import json
import os

import numpy as np

from phase1 import config
from io_utils import load_json


class Retriever:
    """Lazy-loaded retriever — index is read once on first query."""

    def __init__(self):
        import faiss
        from sentence_transformers import SentenceTransformer

        idx_path = os.path.join(config.INDEX_DIR, "chapters.index")
        meta_path = os.path.join(config.INDEX_DIR, "chunks_metadata.json")

        if not os.path.exists(idx_path):
            raise FileNotFoundError(
                f"No FAISS index at {idx_path}. Run 'build_index' first."
            )

        self.index = faiss.read_index(idx_path)
        self.metadata: list[dict] = load_json(meta_path, [])

        self.model = SentenceTransformer(config.EMBEDDING_MODEL)

    def query(self, text: str, top_k: int | None = None) -> list[dict]:
        top_k = top_k or config.TOP_K

        vec = self.model.encode([text], normalize_embeddings=True)
        vec = np.asarray(vec, dtype="float32")

        scores, indices = self.index.search(vec, top_k)

        results = []
        for rank, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue
            meta = self.metadata[idx]
            results.append({
                "rank": rank + 1,
                "chapter": meta["chapter"],
                "chunk_index": meta["chunk_index"],
                "score": float(scores[0][rank]),
                "text": meta["text"],
            })
        return results
