"""
main.py — FastAPI server for the BookRAG chatbot.

Auth endpoints (public):
    POST /auth/register    — create account → { access_token, user }
    POST /auth/login       — sign in        → { access_token, user }
    GET  /auth/me          — current user   (protected)

Book endpoints (all protected — require Bearer token):
    POST /upload           — start ingestion in background, return job_id
    GET  /progress/{job_id}— poll ingestion progress (0-100%)
    GET  /books            — list current user's ingested books
    POST /chat             — ask a question about an uploaded book

Utility:
    GET  /health           — liveness probe
"""

import os
import shutil
import tempfile
import uuid
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any

import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import settings
from database import create_tables, get_db, User, Book, SessionLocal
from auth import hash_password, verify_password, create_access_token, get_current_user
from ingestion import ingest_book, get_embeddings_model
from retriever import retrieve_chunks
from chat import generate_answer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("bookrag")

# ---------------------------------------------------------------------------
# Rate limiter (IP-based, no Redis needed — in-memory)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# In-memory job store { job_id → {status, progress, message, result, error} }
# NOTE: Replace with Redis for multi-worker deployments.
# ---------------------------------------------------------------------------
jobs: Dict[str, Dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app):
    """Create DB tables, purge stale book records, warm up embedding model."""
    logger.info("Initializing application startup...")
    
    try:
        logger.info("Connecting to database and creating tables...")
        create_tables()
        logger.info("✓ Database tables ready.")
    except Exception as e:
        logger.error(f"❌ DATABASE STARTUP FAILED: {e}", exc_info=True)
        # We don't raise here so the app can still bind to the port for health checks
        # but most routes will fail later.

    # Purge book records whose FAISS index no longer exists on disk
    # (happens after every free-tier restart since /tmp is wiped)
    try:
        db = SessionLocal()
        try:
            stale = [
                b for b in db.query(Book).all()
                if not os.path.isfile(os.path.join(settings.PERSIST_DIR, b.collection_id, "index.faiss"))
            ]
            if stale:
                for b in stale:
                    db.delete(b)
                db.commit()
                logger.info(f"Cleaned up {len(stale)} stale book record(s) (vector store was reset).")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Failed to clean up stale books: {e}", exc_info=True)

    async def _warm():
        try:
            model = get_embeddings_model()
            await run_in_threadpool(model.embed_query, "warmup")
            logger.info("✓ Embedding model ready.")
        except Exception as e:
            logger.warning(f"Warmup warning: {e}")
    asyncio.create_task(_warm())
    yield


app = FastAPI(title="BookRAG API", version="2.0.0", lifespan=lifespan)

# Rate-limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".epub", ".txt", ".html", ".htm"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]

class ChatRequest(BaseModel):
    question: str
    collection_id: str
    book_title: str

class ChatResponse(BaseModel):
    answer: str

class UploadStartResponse(BaseModel):
    job_id: str
    message: str


# ---------------------------------------------------------------------------
# Auth routes  (public)
# ---------------------------------------------------------------------------

@app.post("/auth/register", response_model=AuthResponse, status_code=201)
@limiter.limit("5/minute")          # max 5 sign-up attempts per IP per minute
async def register(request: Request, req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    user = User(email=req.email, hashed_password=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"New user registered: {user.email}")

    token = create_access_token(user.id, user.email)
    return AuthResponse(
        access_token=token,
        user={"id": user.id, "email": user.email},
    )


@app.post("/auth/login", response_model=AuthResponse)
@limiter.limit("10/minute")         # brute-force guard: 10 attempts per IP per minute
async def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_access_token(user.id, user.email)
    logger.info(f"User logged in: {user.email}")
    return AuthResponse(
        access_token=token,
        user={"id": user.id, "email": user.email},
    )


@app.get("/auth/me")
@limiter.limit("60/minute")
async def me(request: Request, current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}


# ---------------------------------------------------------------------------
# Background ingestion worker
# ---------------------------------------------------------------------------

def _run_ingestion(job_id: str, tmp_path: str, filename: str, tmp_dir: str, user_id: int):
    """Runs in a thread pool. Updates jobs[job_id] and persists to DB on success."""
    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["message"] = "Parsing file…"
        jobs[job_id]["progress"] = 5
        logger.info(f"Job {job_id}: ingesting '{filename}' for user {user_id}")

        def progress_cb(current: int, total: int, msg: str = ""):
            pct = 5 + int((current / total) * 90) if total > 0 else 5
            jobs[job_id]["progress"] = pct
            jobs[job_id]["message"] = msg or f"Embedding chunk {current}/{total}…"

        result = ingest_book(tmp_path, filename, progress_callback=progress_cb, user_id=user_id)

        # Persist book metadata to DB (create session inside the thread)
        db = SessionLocal()
        try:
            if not db.query(Book).filter(Book.collection_id == result["collection_id"]).first():
                db.add(Book(
                    collection_id=result["collection_id"],
                    book_title=result["book_title"],
                    chunk_count=result["chunk_count"],
                    owner_id=user_id,
                ))
                db.commit()
        finally:
            db.close()

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["message"] = "Complete!"
        jobs[job_id]["result"] = result
        logger.info(f"Job {job_id}: done — {result['chunk_count']} chunks")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = str(e)
        jobs[job_id]["error"] = str(e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Protected routes
# ---------------------------------------------------------------------------

@app.post("/upload", response_model=UploadStartResponse)
@limiter.limit("10/hour")           # heavy operation — 10 uploads per IP per hour
async def upload_book(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {settings.MAX_UPLOAD_BYTES // (1024*1024)} MB.",
        )

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
    logger.info(f"Job {job_id}: queued for user {current_user.id} — '{file.filename}'")

    background_tasks.add_task(
        _run_ingestion, job_id, tmp_path, file.filename, tmp_dir, current_user.id
    )
    return UploadStartResponse(job_id=job_id, message="Ingestion started")


@app.get("/progress/{job_id}")
@limiter.limit("120/minute")        # polling — generous limit
async def get_progress(request: Request, job_id: str, current_user: User = Depends(get_current_user)):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/books")
@limiter.limit("60/minute")
async def list_books(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all books belonging to the authenticated user."""
    books = db.query(Book).filter(Book.owner_id == current_user.id).all()
    return {
        "books": [
            {
                "collection_id": b.collection_id,
                "book_title": b.book_title,
                "chunk_count": b.chunk_count,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in books
        ]
    }


@app.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")         # 30 questions per IP per minute
async def chat_with_book(
    request: Request,
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Security: verify the collection belongs to this user
    book = db.query(Book).filter(
        Book.collection_id == req.collection_id,
        Book.owner_id == current_user.id,
    ).first()
    if not book:
        raise HTTPException(
            status_code=403,
            detail="Book not found or you don't have access to it.",
        )

    logger.info(f"Chat: user {current_user.id} — '{req.question[:60]}' on '{req.collection_id}'")
    try:
        chunks = await run_in_threadpool(retrieve_chunks, req.question, req.collection_id)
    except Exception:
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
    return {"status": "ok", "model": settings.GROQ_MODEL, "version": "2.0.0"}
