"""
Search backends for JustScrape.

Each backend implements the SearchBackend interface and can be used
independently or combined via MultiSearch for fallback/merging.
"""

from backends.base import SearchBackend, MultiSearch
from backends.duckduckgo import DuckDuckGoBackend

__all__ = [
    "SearchBackend",
    "MultiSearch",
    "DuckDuckGoBackend",
]

# Optional backends — only importable if deps are available
try:
    from backends.searxng import SearXNGBackend
    __all__.append("SearXNGBackend")
except ImportError:
    pass

try:
    from backends.brave import BraveSearchBackend
    __all__.append("BraveSearchBackend")
except ImportError:
    pass
