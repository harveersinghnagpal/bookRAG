"""
retriever.py — Hybrid retrieval with cross-encoder reranking.

Pipeline for every query:
  1.  Embed query           (HuggingFace all-MiniLM-L6-v2)
  2.  FAISS search          top_k_vector  = 10 candidates
  3.  BM25 keyword search   top_k_keyword = 10 candidates
  4.  Merge + dedup         by chunk_index → up to 20 candidates
  5.  Cross-encoder rerank  (ms-marco-MiniLM-L-6-v2, batch)
  6.  Return top_k_final    = 5 passages to the LLM
"""

import os
import json
import pickle
import re
from typing import List, Dict, Any

import numpy as np
import faiss
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
from langchain_huggingface import HuggingFaceEmbeddings
from dotenv import load_dotenv

load_dotenv()

PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_store")

# ---------------------------------------------------------------------------
# Module-level singletons — loaded once at import / server startup
# ---------------------------------------------------------------------------
embeddings_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

reranker = CrossEncoder(
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    max_length=512,
)

# ---------------------------------------------------------------------------
# BM25 tokenizer (must match ingestion.py)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


# ---------------------------------------------------------------------------
# Simple in-process cache for BM25 indices
# ---------------------------------------------------------------------------
_bm25_cache: Dict[str, BM25Okapi] = {}


def _load_bm25(collection_name: str) -> BM25Okapi:
    if collection_name not in _bm25_cache:
        bm25_path = os.path.join(PERSIST_DIR, collection_name, "bm25.pkl")
        if not os.path.isfile(bm25_path):
            raise FileNotFoundError(
                f"BM25 index not found for '{collection_name}'. "
                "Re-upload the book to rebuild the index."
            )
        with open(bm25_path, "rb") as f:
            _bm25_cache[collection_name] = pickle.load(f)
    return _bm25_cache[collection_name]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve_chunks(
    query: str,
    collection_name: str,
    top_k_vector: int = 20,
    top_k_keyword: int = 20,
    top_k_final: int = 15,
) -> List[Dict[str, Any]]:
    """
    Hybrid retrieval + reranking pipeline.

    Returns up to *top_k_final* passages as:
        [{ text, page_number, chapter, chunk_index, score }, ...]
    where *score* is the cross-encoder relevance score (higher = better).
    """
    cdir = os.path.join(PERSIST_DIR, collection_name)
    index_path = os.path.join(cdir, "index.faiss")
    meta_path = os.path.join(cdir, "metadata.json")

    if not os.path.isfile(index_path) or not os.path.isfile(meta_path):
        raise FileNotFoundError(f"Collection '{collection_name}' not found.")

    # ------------------------------------------------------------------
    # Load FAISS index + chunk metadata
    # ------------------------------------------------------------------
    faiss_index = faiss.read_index(index_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    stored_chunks = meta["chunks"]

    # ------------------------------------------------------------------
    # Stage 1 — FAISS semantic search
    # ------------------------------------------------------------------
    query_vec = np.array(
        [embeddings_model.embed_query(query)], dtype="float32"
    )
    faiss.normalize_L2(query_vec)

    k_vec = min(top_k_vector, faiss_index.ntotal)
    distances, indices = faiss_index.search(query_vec, k_vec)

    faiss_hits: Dict[int, Dict[str, Any]] = {}
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0:
            continue
        chunk = stored_chunks[idx]
        ci = chunk.get("chunk_index", idx)
        faiss_hits[ci] = {
            "text": chunk["text"],
            "page_number": chunk.get("page_number"),
            "chapter": chunk.get("chapter", "Unknown"),
            "chunk_index": ci,
            "_faiss_score": float(dist),
        }

    # ------------------------------------------------------------------
    # Stage 2 — BM25 keyword search
    # ------------------------------------------------------------------
    bm25 = _load_bm25(collection_name)
    query_tokens = _tokenize(query)
    bm25_scores = bm25.get_scores(query_tokens)

    # Get top-k BM25 results by score
    top_bm25_indices = np.argsort(bm25_scores)[::-1][:top_k_keyword]

    bm25_hits: Dict[int, Dict[str, Any]] = {}
    for idx in top_bm25_indices:
        if bm25_scores[idx] <= 0:
            continue
        chunk = stored_chunks[idx]
        ci = chunk.get("chunk_index", int(idx))
        bm25_hits[ci] = {
            "text": chunk["text"],
            "page_number": chunk.get("page_number"),
            "chapter": chunk.get("chapter", "Unknown"),
            "chunk_index": ci,
            "_bm25_score": float(bm25_scores[idx]),
        }

    # ------------------------------------------------------------------
    # Stage 3 — Merge and dedup by chunk_index
    # ------------------------------------------------------------------
    merged: Dict[int, Dict[str, Any]] = {}

    for ci, hit in faiss_hits.items():
        merged[ci] = hit

    for ci, hit in bm25_hits.items():
        if ci in merged:
            # Already present from FAISS — just attach BM25 score
            merged[ci]["_bm25_score"] = hit.get("_bm25_score", 0.0)
        else:
            merged[ci] = hit

    candidates = list(merged.values())

    if not candidates:
        return []

    # ------------------------------------------------------------------
    # Stage 4 — Cross-encoder reranking (batch)
    # ------------------------------------------------------------------
    pairs = [(query, c["text"]) for c in candidates]
    rerank_scores = reranker.predict(pairs, show_progress_bar=False)

    for candidate, score in zip(candidates, rerank_scores):
        candidate["score"] = float(score)

    # Sort descending by reranker score
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # ------------------------------------------------------------------
    # Stage 5 — Return top_k_final
    # ------------------------------------------------------------------
    final = candidates[:top_k_final]

    # Clean internal scoring fields before returning
    for c in final:
        c.pop("_faiss_score", None)
        c.pop("_bm25_score", None)

    return final
