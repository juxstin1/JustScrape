"""
Shared utilities for MCP tool handlers.

Contains helper functions and constants used across multiple handler modules.
"""

import asyncio
from typing import Any, Optional
from urllib.parse import urlparse

from ..config import MAX_CONCURRENT_SCRAPES, YOUTUBE_DOMAINS
from ..worker import classify_content as classify_retrieved_content
_scrape_semaphore = None  # Initialized lazily in async context


def _get_scrape_semaphore():
    global _scrape_semaphore
    if _scrape_semaphore is None:
        _scrape_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCRAPES)
    return _scrape_semaphore


def _normalize_bool(value: Any, default: bool) -> bool:
    """Parse loose boolean-like MCP inputs without surprising truthiness."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _normalize_scrape_method(raw_method: Optional[str]) -> str:
    """Collapse scrape method variants into the refined contract values."""
    method = (raw_method or "unknown").lower()
    if "javascript" in method:
        return "javascript"
    if method in {
        "reddit_json",
        "stackexchange_api",
        "stackexchange_stackprinter",
        "devto_api",
        "github_discussions_html",
    }:
        return method
    return "static"


def _build_retrieve_payload(url: str, scraped: dict) -> dict:
    """Shape a scrape result into the refined retrieve_source contract."""
    content = scraped.get("content")
    title = scraped.get("title")
    method = _normalize_scrape_method(
        scraped.get("scrape_method") or scraped.get("method")
    )
    status_code = scraped.get("status_code")
    signals = {
        "content_length": len(content) if content else 0,
        "method": method,
        "had_html": bool(status_code == 200 or content),
        "encoding_error": False,
    }
    classification = classify_retrieved_content(
        content=content,
        title=title,
        had_html=signals["had_html"],
        encoding_error=False,
        method=method,
    )

    warnings = []
    domain = urlparse(url).netloc.lower().replace("www.", "")
    if domain in YOUTUBE_DOMAINS or any(domain.endswith(f".{d}") for d in YOUTUBE_DOMAINS):
        warnings.append(
            "Video watch pages often contain site chrome instead of transcript text. Prefer a non-video source or the combined research tool unless you specifically need this page."
        )

    payload = {
        "url": url,
        "title": title,
        "content": content,
        "signals": signals,
        "classification": classification,
    }
    if warnings:
        payload["warnings"] = warnings
    return payload
