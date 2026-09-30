"""Application configuration.

All settings are read from environment variables so nothing is hardcoded.
A local ``.env`` file (see ``.env.example``) is loaded automatically via
python-dotenv; real environment variables always win over ``.env`` values.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env if present (does not override variables already set in the shell).
load_dotenv(BASE_DIR / ".env")

# Default Gemini model - the current stable Flash model.
# Override it any time with the GEMINI_MODEL environment variable.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

# Models tried (in order) when the primary model is overloaded - Google's
# most popular model regularly returns a temporary 503 "high demand" on
# the free tier. Set GEMINI_FALLBACK_MODELS="" in .env to disable.
DEFAULT_GEMINI_FALLBACK_MODELS = "gemini-3.8-flash-lite"


def _database_uri() -> str:
    """Return the SQLAlchemy database URI.

    Default: a local SQLite file (resolved by Flask-SQLAlchemy inside the
    instance/ folder). A DATABASE_URL environment variable can override it,
    but only when it looks like a valid SQLAlchemy URL - anything else is
    ignored so a stray variable can never break startup.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith(("sqlite://", "postgresql://", "postgresql+", "mysql://", "mysql+")):
        return url
    return "sqlite:///finance.db"


class Config:
    """Base configuration for the Personal Finance Advisor Bot."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_for_local_development")

    # ---- Gemini AI ----
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    GEMINI_FALLBACK_MODELS = os.environ.get(
        "GEMINI_FALLBACK_MODELS", DEFAULT_GEMINI_FALLBACK_MODELS
    )

    # ---- Database ----
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---- Flask ----
    DEBUG = (
        os.environ.get("FLASK_DEBUG", "").lower() == "1"
        or os.environ.get("FLASK_ENV") == "development"
    )
