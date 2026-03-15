"""
Search backend base class and MultiSearch router.

All search backends implement SearchBackend.search() and return
web_search.SearchResponse objects for interoperability.
"""

import sys
import os

# Ensure project root is importable (safe: only adds if not already present)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.append(_project_root)

from abc import ABC, abstractmethod
from typing import List, Optional
from web_search import SearchResponse, SearchResult, merge_search_results


class SearchBackend(ABC):
    """Base class for all search backends."""

    name: str = "base"

    @abstractmethod
    def search(
        self,
        query: str,
        num_results: int = 10,
        region: str = "wt-wt",
        date_range: str = None,
    ) -> SearchResponse:
        """
        Execute a search and return structured results.

        Args:
            query: The search query (may include operators like site:, filetype:)
            num_results: Maximum number of results
            region: Region code
            date_range: Time filter — "day", "week", "month", "year"

        Returns:
            SearchResponse with results and metadata
        """
        ...

    def is_available(self) -> bool:
        """Check if this backend is currently available (deps installed, server reachable, etc.)"""
        return True


class MultiSearch:
    """
    Routes queries across multiple search backends with fallback and merging.

    Modes:
    - "fallback": Try backends in order, return first successful result
    - "merge": Query all backends, deduplicate and merge results
    """

    def __init__(self, backends: List[SearchBackend], mode: str = "fallback"):
        self.backends = [b for b in backends if b.is_available()]
        self.mode = mode

    def search(
        self,
        query: str,
        num_results: int = 10,
        region: str = "wt-wt",
        date_range: str = None,
    ) -> SearchResponse:
        if not self.backends:
            return SearchResponse(
                query=query, results=[], total_results=0,
                search_time_ms=0, source="none", success=False,
                error="No search backends available"
            )

        if self.mode == "merge":
            return self._merge_search(query, num_results, region, date_range)
        else:
            return self._fallback_search(query, num_results, region, date_range)

    def _fallback_search(self, query, num_results, region, date_range) -> SearchResponse:
        """Try each backend in order, return first successful result."""
        last_error = None
        for backend in self.backends:
            try:
                result = backend.search(query, num_results, region, date_range)
                if result.success and result.total_results > 0:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)

        return SearchResponse(
            query=query, results=[], total_results=0,
            search_time_ms=0, source="multi",
            success=False, error=f"All backends failed: {last_error}"
        )

    def _merge_search(self, query, num_results, region, date_range) -> SearchResponse:
        """Query all backends and merge/deduplicate results."""
        responses = []
        for backend in self.backends:
            try:
                result = backend.search(query, num_results, region, date_range)
                if result.success:
                    responses.append(result)
            except Exception:
                continue

        if not responses:
            return SearchResponse(
                query=query, results=[], total_results=0,
                search_time_ms=0, source="multi",
                success=False, error="All backends failed"
            )

        merged = merge_search_results(responses)
        # Trim to requested count
        merged.results = merged.results[:num_results]
        merged.total_results = len(merged.results)
        return merged
