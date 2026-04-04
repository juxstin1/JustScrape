"""
Source-specific adapters for domain-aware scraping.

Each adapter handles a specific family of sites (Reddit, Stack Exchange, etc.)
and can scrape them without browser automation.
"""

from typing import Optional

from .base import SourceAdapter, _safe_get
from .reddit import RedditAdapter
from .stackexchange import StackExchangeAdapter
from .devto import DevToAdapter
from .github import GitHubDiscussionsAdapter

__all__ = [
    "SourceAdapter",
    "_safe_get",
    "RedditAdapter",
    "StackExchangeAdapter",
    "DevToAdapter",
    "GitHubDiscussionsAdapter",
    "get_adapter",
]

# Ordered list of adapters — checked in sequence by get_adapter().
_ADAPTERS = [
    RedditAdapter,
    StackExchangeAdapter,
    DevToAdapter,
    GitHubDiscussionsAdapter,
]


def get_adapter(url: str) -> Optional[SourceAdapter]:
    """Return an instantiated adapter that can handle *url*, or None."""
    for adapter_cls in _ADAPTERS:
        if adapter_cls.can_handle(url):
            return adapter_cls()
    return None
