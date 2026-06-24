"""Environment configuration for the Railway web service."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "artifacts")).resolve()


def crawl_dir_for_url(url: str) -> Path:
    host = urlparse(url).netloc.replace(":", "-") or "site"
    return data_dir() / "crawls" / host


def processed_dir_for_url(url: str) -> Path:
    return crawl_dir_for_url(url) / "processed"


def knowledge_sync_state_path() -> Path:
    return data_dir() / "knowledge-sync-state.json"


def knowledge_config_state_path() -> Path:
    return data_dir() / "knowledge-config-state.json"


def jobs_dir() -> Path:
    path = data_dir() / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def genesys_agent_id() -> str:
    return os.getenv("AVA_AGENT_ID", "").strip()


def genesys_agent_version() -> str:
    return os.getenv("AVA_VERSION", "6.0")


def studio_mode() -> bool:
    return os.getenv("AVA_STUDIO_MODE", "1").strip().lower() in {"1", "true", "yes"}


def pipeline_api_key() -> str | None:
    value = os.getenv("PIPELINE_API_KEY", "").strip()
    return value or None


def pipeline_key_enforced() -> bool:
    """Ingest is manual-only; production should always require a pipeline key."""
    if os.getenv("REQUIRE_PIPELINE_KEY", "1").strip().lower() in {"0", "false", "no"}:
        return False
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))


def chat_api_key() -> str | None:
    value = os.getenv("CHAT_API_KEY", "").strip()
    return value or None


def chat_title() -> str:
    return os.getenv("CHAT_TITLE", "FAQ Assistant")


def chat_subtitle() -> str:
    return os.getenv(
        "CHAT_SUBTITLE",
        "Ask questions about our products and services.",
    )
