"""
SearXNG search backend.

Connects to a self-hosted SearXNG instance for meta-search across 70+ engines.
No rate limits from third parties when self-hosted.

Setup:
    docker run -d --name searxng -p 8080:8080 searxng/searxng

Configure:
    SearXNGBackend(base_url="http://localhost:8080")
"""



import time
import requests
from ..web_search import SearchResponse, SearchResult
from .base import SearchBackend


class SearXNGBackend(SearchBackend):
    """SearXNG self-hosted meta-search engine backend."""

    name = "searxng"

    def __init__(self, base_url: str = "http://localhost:8080", timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def search(
        self,
        query: str,
        num_results: int = 10,
        region: str = "wt-wt",
        date_range: str = None,
    ) -> SearchResponse:
        start_time = time.time()

        params = {
            "q": query,
            "format": "json",
            "categories": "general",
        }

        # Map date_range to SearXNG time_range parameter
        if date_range:
            time_range_map = {"day": "day", "week": "week", "month": "month", "year": "year"}
            tr = time_range_map.get(date_range)
            if tr:
                params["time_range"] = tr

        # Map region
        if region and region != "wt-wt":
            params["language"] = region

        try:
            resp = requests.get(
                f"{self.base_url}/search",
                params=params,
                timeout=self.timeout,
                headers={"Accept": "application/json"}
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for i, r in enumerate(data.get("results", [])[:num_results]):
                results.append(SearchResult(
                    position=i + 1,
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    source=f"searxng:{r.get('engine', 'unknown')}"
                ))

            elapsed_ms = int((time.time() - start_time) * 1000)

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                search_time_ms=elapsed_ms,
                source="searxng",
                success=True
            )

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return SearchResponse(
                query=query,
                results=[],
                total_results=0,
                search_time_ms=elapsed_ms,
                source="searxng",
                success=False,
                error=str(e)
            )

    def is_available(self) -> bool:
        """Check if SearXNG instance is reachable."""
        try:
            resp = requests.get(f"{self.base_url}/config", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False
