"""
Brave Search API backend.

Free tier: 2,000 queries/month. Independent index, high quality results.
Requires API key from https://brave.com/search/api/

Configure:
    BraveSearchBackend(api_key="YOUR_KEY")
    # Or set BRAVE_SEARCH_API_KEY environment variable
"""

import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.append(_project_root)

import time
import requests
from web_search import SearchResponse, SearchResult
from backends.base import SearchBackend


class BraveSearchBackend(SearchBackend):
    """Brave Search API backend (free tier: 2000 queries/month)."""

    name = "brave"

    def __init__(self, api_key: str = None, timeout: int = 10):
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY", "")
        self.timeout = timeout
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    def search(
        self,
        query: str,
        num_results: int = 10,
        region: str = "wt-wt",
        date_range: str = None,
    ) -> SearchResponse:
        start_time = time.time()

        if not self.api_key:
            return SearchResponse(
                query=query, results=[], total_results=0,
                search_time_ms=0, source="brave",
                success=False, error="No Brave API key configured"
            )

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }

        params = {
            "q": query,
            "count": min(num_results, 20),
        }

        # Map date_range to Brave freshness parameter
        if date_range:
            freshness_map = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}
            f = freshness_map.get(date_range)
            if f:
                params["freshness"] = f

        # Map region
        if region and region != "wt-wt":
            params["country"] = region.split("-")[0] if "-" in region else region

        try:
            resp = requests.get(
                self.base_url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            web_results = data.get("web", {}).get("results", [])
            for i, r in enumerate(web_results[:num_results]):
                results.append(SearchResult(
                    position=i + 1,
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("description", ""),
                    source="brave",
                ))

            elapsed_ms = int((time.time() - start_time) * 1000)

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                search_time_ms=elapsed_ms,
                source="brave",
                success=True,
            )

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return SearchResponse(
                query=query, results=[], total_results=0,
                search_time_ms=elapsed_ms, source="brave",
                success=False, error=str(e),
            )

    def is_available(self) -> bool:
        return bool(self.api_key)
