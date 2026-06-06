"""Centralized configuration for the Data Contract Registry.

All settings are read from environment variables with sensible defaults.
Import individual values or the module itself::

    from src.settings import API_HOST, API_PORT
    # or
    from src import settings
    uvicorn.run(..., host=settings.API_HOST, port=settings.API_PORT)
"""

import os

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
UI_PORT: int = int(os.getenv("UI_PORT", "8501"))

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

CORS_ORIGINS: list[str] = os.getenv(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:8501"
).split(",")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONTRACTS_DIR: str = os.getenv("CONTRACTS_DIR", "contracts")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
