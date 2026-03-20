"""
database.py — SQLAlchemy ORM models and session management.

Models:
  - User   : registered user (email + hashed password)
  - Book   : ingested book owned by a user (maps collection_id → FAISS index)
"""

import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config import settings

import logging
# ---------------------------------------------------------------------------
# Engine — supports SQLite (local) and PostgreSQL (Render)
# ---------------------------------------------------------------------------
logger = logging.getLogger("bookrag.database")

_connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
else:
    # PostgreSQL optimizations for production (timeout prevents hanging)
    _connect_args = {
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }

logger.info(f"Creating engine for {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else 'local db'}")
engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id             = Column(Integer, primary_key=True, index=True)
    email          = Column(String, unique=True, index=True, nullable=False)
    hashed_password= Column(String, nullable=False)
    created_at     = Column(DateTime, default=datetime.datetime.utcnow)

    books = relationship("Book", back_populates="owner", cascade="all, delete-orphan")


class Book(Base):
    __tablename__ = "books"

    id            = Column(Integer, primary_key=True, index=True)
    collection_id = Column(String, unique=True, index=True, nullable=False)
    book_title    = Column(String, nullable=False)
    chunk_count   = Column(Integer, default=0)
    owner_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="books")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
