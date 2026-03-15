"""
DuckDuckGo search backend.

Wraps the existing WebSearch class as a SearchBackend for use with MultiSearch.
Free, no API key required.
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.append(_project_root)

import time
from web_search import SearchResponse, SearchResult, WebSearch
from backends.base import SearchBackend


class DuckDuckGoBackend(SearchBackend):
    """DuckDuckGo search via the duckduckgo-search library."""

    name = "duckduckgo"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def search(
        self,
        query: str,
        num_results: int = 10,
        region: str = "wt-wt",
        date_range: str = None,
    ) -> SearchResponse:
        ws = WebSearch(timeout=self.timeout, use_cache=False)
        return ws.search(query, num_results, region=region, date_range=date_range)

    def is_available(self) -> bool:
        try:
            from duckduckgo_search import DDGS
            return True
        except ImportError:
            return False
