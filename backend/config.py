"""
config.py — Single source of truth for all environment-driven settings.

Usage:
    from config import settings
    print(settings.GROQ_API_KEY)
"""

import os
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── LLM ────────────────────────────────────────────────────────────────────
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # ── Storage ────────────────────────────────────────────────────────────────
    PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_store")

    # ── Auth / Security ────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-prod-use-long-random-string")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = int(os.getenv("JWT_EXPIRE_DAYS", "7"))

    # ── Database ───────────────────────────────────────────────────────────────
    @property
    def DATABASE_URL(self) -> str:
        url = os.getenv("DATABASE_URL", "sqlite:///./bookrag.db")
        # Render provides postgres:// — SQLAlchemy needs postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url

    # ── CORS ───────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins
    @property
    def allowed_origins(self) -> list[str]:
        raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
        return [o.strip() for o in raw.split(",") if o.strip()]

    # ── Server ─────────────────────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")

    # ── Uploads ────────────────────────────────────────────────────────────────
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))  # 100 MB

    def validate(self):
        """Raise early if required secrets are missing."""
        if not self.GROQ_API_KEY:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. "
                "Get a free key at https://console.groq.com/keys and add it to backend/.env"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings().validate()


settings = get_settings()
