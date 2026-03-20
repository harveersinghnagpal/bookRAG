"""
ingestion.py — Book ingestion pipeline.

Accepts file uploads (PDF, DOCX, EPUB, TXT, HTML), extracts text with metadata,
chunks it, embeds it, and stores:
  - FAISS index + metadata.json  (semantic search)
  - bm25.pkl                     (keyword search)
"""

import os
import re
import json
import pickle
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

import numpy as np
import faiss
from rank_bm25 import BM25Okapi
import fitz  # PyMuPDF
from docx import Document as DocxDocument
from ebooklib import epub
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

from config import settings

# Suppress noisy third-party warnings
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

PERSIST_DIR = settings.PERSIST_DIR
os.makedirs(PERSIST_DIR, exist_ok=True)

from functools import lru_cache

@lru_cache(maxsize=1)
def get_embeddings_model():
    return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_pdf(file_path: str) -> List[Dict[str, Any]]:
    """Extract text + metadata from a PDF using PyMuPDF."""
    doc = fitz.open(file_path)
    pages = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        if text.strip():
            pages.append({
                "text": text,
                "page_number": page_num + 1,
                "chapter": _detect_chapter(text),
            })
    doc.close()
    return pages


def _parse_docx(file_path: str) -> List[Dict[str, Any]]:
    """Extract text + metadata from a DOCX file."""
    doc = DocxDocument(file_path)
    current_chapter = "Unknown"
    full_text_parts: List[str] = []
    for para in doc.paragraphs:
        if para.style and para.style.name.startswith("Heading"):
            current_chapter = para.text.strip() or current_chapter
        full_text_parts.append(para.text)
    full_text = "\n".join(full_text_parts)
    if full_text.strip():
        return [{"text": full_text, "page_number": 1, "chapter": current_chapter}]
    return []


def _parse_epub(file_path: str) -> List[Dict[str, Any]]:
    """Extract text + metadata from an EPUB file."""
    book = epub.read_epub(file_path, options={"ignore_ncx": True})
    pages = []
    page_counter = 1
    for item in book.get_items_of_type(9):  # ITEM_DOCUMENT
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n")
        if text.strip():
            pages.append({
                "text": text,
                "page_number": page_counter,
                "chapter": _detect_chapter(text),
            })
            page_counter += 1
    return pages


def _parse_html(file_path: str) -> List[Dict[str, Any]]:
    """Extract text + metadata from an HTML file."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    text = soup.get_text(separator="\n")
    title_tag = soup.find("title")
    chapter = title_tag.get_text() if title_tag else "Unknown"
    if text.strip():
        return [{"text": text, "page_number": 1, "chapter": chapter}]
    return []


def _parse_txt(file_path: str) -> List[Dict[str, Any]]:
    """Extract text from a plain-text file."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    if text.strip():
        return [{"text": text, "page_number": 1, "chapter": _detect_chapter(text)}]
    return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHAPTER_RE = re.compile(r"(?:^|\n)\s*(chapter\s+\d+[^\n]*)", re.IGNORECASE)


def _detect_chapter(text: str) -> str:
    match = CHAPTER_RE.search(text[:500])
    return match.group(1).strip() if match else "Unknown"


def _sanitize_collection_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "_", name)
    slug = re.sub(r"_+", "_", slug).strip("_")[:63]
    if len(slug) < 3:
        slug = slug + "_col"
    if not slug[0].isalnum():
        slug = "b" + slug
    if not slug[-1].isalnum():
        slug = slug + "k"
    return slug


PARSER_MAP = {
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".epub": _parse_epub,
    ".html": _parse_html,
    ".htm": _parse_html,
    ".txt": _parse_txt,
}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _collection_dir(collection_name: str) -> str:
    return os.path.join(PERSIST_DIR, collection_name)


def _collection_exists(collection_name: str) -> bool:
    """Collection is valid only if ALL three index files exist."""
    cdir = _collection_dir(collection_name)
    return (
        os.path.isdir(cdir)
        and os.path.isfile(os.path.join(cdir, "index.faiss"))
        and os.path.isfile(os.path.join(cdir, "metadata.json"))
        and os.path.isfile(os.path.join(cdir, "bm25.pkl"))
    )


def _load_collection_meta(collection_name: str) -> Dict[str, Any]:
    with open(
        os.path.join(_collection_dir(collection_name), "metadata.json"),
        "r", encoding="utf-8",
    ) as f:
        return json.load(f)


def _save_collection(
    collection_name: str,
    index: faiss.Index,
    metadata: Dict[str, Any],
    bm25: BM25Okapi,
) -> None:
    """Persist FAISS index, JSON metadata, and BM25 index to disk."""
    cdir = _collection_dir(collection_name)
    os.makedirs(cdir, exist_ok=True)

    faiss.write_index(index, os.path.join(cdir, "index.faiss"))

    with open(os.path.join(cdir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False)

    with open(os.path.join(cdir, "bm25.pkl"), "wb") as f:
        pickle.dump(bm25, f)


# ---------------------------------------------------------------------------
# BM25 tokenizer (simple, fast)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alphanumeric characters."""
    return re.findall(r"[a-z0-9]+", text.lower())


# ---------------------------------------------------------------------------
# Main ingestion function
# ---------------------------------------------------------------------------

def ingest_book(
    file_path: str,
    original_filename: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Full ingestion pipeline:
      1. Parse  → extract text + metadata per page/section
      2. Chunk  → RecursiveCharacterTextSplitter (700 / 150)
      3. Embed  → FAISS IndexFlatIP with L2-normalized vectors
      4. BM25   → BM25Okapi over tokenized chunk texts
      5. Persist → index.faiss + metadata.json + bm25.pkl

    progress_callback(current, total, msg) fires after every embedding batch.
    """
    ext = Path(original_filename).suffix.lower()
    parser = PARSER_MAP.get(ext)
    if parser is None:
        raise ValueError(f"Unsupported file format: {ext}")

    book_title = Path(original_filename).stem
    base_slug = _sanitize_collection_name(book_title)
    # Prefix with user_id so each user gets isolated collections in the store
    collection_name = f"u{user_id}_{base_slug}" if user_id is not None else base_slug

    # Dedup: return immediately if all indices already exist
    if _collection_exists(collection_name):
        meta = _load_collection_meta(collection_name)
        return {
            "collection_id": collection_name,
            "book_title": book_title,
            "chunk_count": meta["chunk_count"],
            "already_existed": True,
        }

    # ---- 1. Parse ----------------------------------------------------------------
    if progress_callback:
        progress_callback(0, 1, "Parsing file…")
    raw_pages = parser(file_path)
    if not raw_pages:
        raise ValueError("No text could be extracted from the uploaded file.")

    # ---- 2. Chunk ----------------------------------------------------------------
    if progress_callback:
        progress_callback(0, 1, "Splitting into chunks…")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=700, chunk_overlap=150, length_function=len,
    )
    chunks: List[Dict[str, Any]] = []
    chunk_index = 0
    for page in raw_pages:
        for split in splitter.split_text(page["text"]):
            chunks.append({
                "text": split,
                "metadata": {
                    "book_title": book_title,
                    "page_number": page["page_number"],
                    "chapter": page.get("chapter", "Unknown"),
                    "chunk_index": chunk_index,
                },
            })
            chunk_index += 1

    # ---- 3. FAISS embeddings ------------------------------------------------------
    texts = [c["text"] for c in chunks]
    total_chunks = len(texts)
    all_vectors: List[List[float]] = []
    batch_size = 50

    model = get_embeddings_model()

    for i in range(0, total_chunks, batch_size):
        batch = texts[i : i + batch_size]
        all_vectors.extend(model.embed_documents(batch))
        done = min(i + batch_size, total_chunks)
        if progress_callback:
            progress_callback(done, total_chunks, f"Embedding {done}/{total_chunks} chunks…")

    vectors_np = np.array(all_vectors, dtype="float32")
    faiss.normalize_L2(vectors_np)
    faiss_index = faiss.IndexFlatIP(vectors_np.shape[1])
    faiss_index.add(vectors_np)

    # ---- 4. BM25 index ------------------------------------------------------------
    if progress_callback:
        progress_callback(total_chunks, total_chunks, "Building BM25 index…")
    tokenized_corpus = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized_corpus)

    # ---- 5. Persist ---------------------------------------------------------------
    if progress_callback:
        progress_callback(total_chunks, total_chunks, "Saving to disk…")
    metadata = {
        "book_title": book_title,
        "chunk_count": len(chunks),
        "chunks": [{"text": c["text"], **c["metadata"]} for c in chunks],
    }
    _save_collection(collection_name, faiss_index, metadata, bm25)

    return {
        "collection_id": collection_name,
        "book_title": book_title,
        "chunk_count": len(chunks),
        "already_existed": False,
    }
