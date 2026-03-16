"""
main.py — FastAPI server for the BookRAG chatbot.

Endpoints:
    POST /upload           — Starts ingestion in background, returns job_id
    GET  /progress/{job_id}— Poll for ingestion progress (0-100%)
    POST /chat             — Ask a question about an uploaded book
    GET  /health           — Health check
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from ingestion import ingest_book, embeddings_model
from retriever import retrieve_chunks
from chat import generate_answer

# --------------------------------------------------------------------------
# In-memory job store: job_id -> { status, progress, message, result, error }
# --------------------------------------------------------------------------
jobs: Dict[str, Dict[str, Any]] = {}


import asyncio

@asynccontextmanager
async def lifespan(app):
    """Fire-and-forget model warmup — server starts instantly."""
    async def _warm():
        try:
            await run_in_threadpool(embeddings_model.embed_query, "warmup")
            print("\u2713 Embedding model ready.")
        except Exception as e:
            print(f"Warmup warning: {e}")
    asyncio.create_task(_warm())
    yield

app = FastAPI(title="BookRAG API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".epub", ".txt", ".html", ".htm"}


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str
    collection_id: str
    book_title: str

class ChatResponse(BaseModel):
    answer: str

class UploadStartResponse(BaseModel):
    job_id: str
    message: str


# --------------------------------------------------------------------------
# Background ingestion worker
# --------------------------------------------------------------------------

def _run_ingestion(job_id: str, tmp_path: str, filename: str, tmp_dir: str):
    """Run in a thread pool. Updates jobs[job_id] with progress."""
    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["message"] = "Parsing file…"
        jobs[job_id]["progress"] = 5

        def progress_cb(current: int, total: int, msg: str = ""):
            pct = 5 + int((current / total) * 90) if total > 0 else 5
            jobs[job_id]["progress"] = pct
            jobs[job_id]["message"] = msg or f"Embedding chunk {current}/{total}…"

        result = ingest_book(tmp_path, filename, progress_callback=progress_cb)

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["message"] = "Complete!"
        jobs[job_id]["result"] = result

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = str(e)
        jobs[job_id]["error"] = str(e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.post("/upload", response_model=UploadStartResponse)
async def upload_book(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Save file, kick off background ingestion, return job_id immediately."""
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename)
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": 0, "message": "Queued…", "result": None}

    # Pass _run_ingestion directly — Starlette runs sync background tasks in a thread pool
    background_tasks.add_task(_run_ingestion, job_id, tmp_path, file.filename, tmp_dir)

    return UploadStartResponse(job_id=job_id, message="Ingestion started")


@app.get("/progress/{job_id}")
async def get_progress(job_id: str):
    """Poll for ingestion progress."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/chat", response_model=ChatResponse)
async def chat_with_book(req: ChatRequest):
    """Retrieve chunks and generate an LLM answer."""
    try:
        chunks = await run_in_threadpool(retrieve_chunks, req.question, req.collection_id)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Collection '{req.collection_id}' not found. Upload the book first.",
        )

    if not chunks:
        return ChatResponse(
            answer=f"I couldn't find an answer to that in '{req.book_title}'. "
            "The book may not cover this topic, or it may be phrased differently."
        )

    answer = await run_in_threadpool(generate_answer, req.question, chunks, req.book_title)
    return ChatResponse(answer=answer)


@app.get("/health")
async def health():
    return {"status": "ok"}
