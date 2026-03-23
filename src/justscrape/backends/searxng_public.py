"""
Public SearXNG instances backend.

Rotates through known public SearXNG instances for meta-search
across Google, Bing, DuckDuckGo, and 70+ other engines.
No API key, no self-hosting required.

Instances are tried in random order; dead/blocked ones are
temporarily deprioritized via a simple cooldown mechanism.
"""

import time
import random
import threading


import requests
from ..web_search import SearchResponse, SearchResult
from .base import SearchBackend

# Known public SearXNG instances that serve JSON
# Curated for reliability — update periodically
_PUBLIC_INSTANCES = [
    "https://search.sapti.me",
    "https://searx.be",
    "https://search.bus-hit.me",
    "https://searxng.site",
    "https://search.ononoki.org",
    "https://searx.tiekoetter.com",
    "https://search.hbubli.cc",
    "https://priv.au",
    "https://searx.ox2.fr",
    "https://paulgo.io",
    "https://opnxng.com",
    "https://etsi.me",
    "https://search.mdosch.de",
    "https://searx.namejeff.xyz",
    "https://s.mble.dk",
]

# Cooldown period for failed instances (seconds)
_INSTANCE_COOLDOWN = 300  # 5 minutes


class SearXNGPublicBackend(SearchBackend):
    """Search via public SearXNG instances with automatic rotation."""

    name = "searxng_public"

    def __init__(self, timeout: int = 8, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._lock = threading.Lock()
        # Track failed instances: url -> timestamp of last failure
        self._failures: dict[str, float] = {}

    def _get_available_instances(self) -> list[str]:
        """Return instances not currently in cooldown, shuffled."""
        now = time.time()
        with self._lock:
            available = [
                url
                for url in _PUBLIC_INSTANCES
                if now - self._failures.get(url, 0) > _INSTANCE_COOLDOWN
            ]
        if not available:
            # All in cooldown — try them all anyway
            available = list(_PUBLIC_INSTANCES)
        random.shuffle(available)
        return available

    def _mark_failed(self, instance_url: str):
        with self._lock:
            self._failures[instance_url] = time.time()

    def search(
        self,
        query: str,
        num_results: int = 10,
        region: str = "wt-wt",
        date_range: str = None,
    ) -> SearchResponse:
        start_time = time.time()
        instances = self._get_available_instances()
        last_error = None

        for instance_url in instances[: self.max_retries]:
            try:
                result = self._search_instance(
                    instance_url, query, num_results, region, date_range, start_time
                )
                if result.success and result.total_results > 0:
                    return result
                # Got a response but no results — try next instance
                last_error = result.error or "0 results"
                self._mark_failed(instance_url)
            except Exception as e:
                last_error = str(e)
                self._mark_failed(instance_url)

        elapsed_ms = int((time.time() - start_time) * 1000)
        return SearchResponse(
            query=query,
            results=[],
            total_results=0,
            search_time_ms=elapsed_ms,
            source="searxng_public",
            success=False,
            error=f"All instances failed: {last_error}",
        )

    def _search_instance(
        self,
        base_url: str,
        query: str,
        num_results: int,
        region: str,
        date_range: str,
        start_time: float,
    ) -> SearchResponse:
        """Query a single SearXNG instance."""
        params = {
            "q": query,
            "format": "json",
            "categories": "general",
        }

        if date_range:
            time_range_map = {
                "day": "day",
                "week": "week",
                "month": "month",
                "year": "year",
            }
            tr = time_range_map.get(date_range)
            if tr:
                params["time_range"] = tr

        if region and region != "wt-wt":
            params["language"] = region

        resp = requests.get(
            f"{base_url.rstrip('/')}/search",
            params=params,
            timeout=self.timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "JustScrape/1.0",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for i, r in enumerate(data.get("results", [])[:num_results]):
            results.append(
                SearchResult(
                    position=i + 1,
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    source=f"searxng_public:{r.get('engine', 'unknown')}",
                )
            )

        elapsed_ms = int((time.time() - start_time) * 1000)

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            search_time_ms=elapsed_ms,
            source="searxng_public",
            success=True,
        )

    def is_available(self) -> bool:
        """Always available — individual instance failures handled internally."""
        return True
