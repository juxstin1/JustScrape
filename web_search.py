"""
Free Web Search Module - DuckDuckGo-based search
No API keys required - just works.

This module provides free web search capabilities using DuckDuckGo.
Designed to be used as a tool/capability worker - deterministic, no reasoning.

Features:
- TTL cache to avoid duplicate requests
- Exponential backoff for rate limiting
- Multiple fallback methods
"""

import time
import hashlib
import threading
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict, field


@dataclass
class SearchResult:
    """Single search result with metadata"""
    position: int
    title: str
    url: str
    snippet: str
    source: str = "duckduckgo"

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SearchResponse:
    """Complete search response with metadata"""
    query: str
    results: List[SearchResult]
    total_results: int
    search_time_ms: int
    source: str = "duckduckgo"
    success: bool = True
    error: Optional[str] = None
    cached: bool = False

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total_results": self.total_results,
            "search_time_ms": self.search_time_ms,
            "source": self.source,
            "success": self.success,
            "error": self.error,
            "cached": self.cached
        }


class SearchCache:
    """Simple TTL cache for search results"""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._cache: Dict[str, Tuple[float, SearchResponse]] = {}
        self._lock = threading.Lock()

    def _make_key(self, query: str, num_results: int) -> str:
        """Create cache key from query params"""
        raw = f"{query.lower().strip()}:{num_results}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, query: str, num_results: int) -> Optional[SearchResponse]:
        """Get cached result if exists and not expired"""
        key = self._make_key(query, num_results)
        with self._lock:
            if key in self._cache:
                timestamp, response = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    # Return cached response with flag
                    return SearchResponse(
                        query=response.query,
                        results=response.results,
                        total_results=response.total_results,
                        search_time_ms=0,
                        source=response.source,
                        success=response.success,
                        error=response.error,
                        cached=True
                    )
                else:
                    # Expired, remove it
                    del self._cache[key]
        return None

    def set(self, query: str, num_results: int, response: SearchResponse):
        """Cache a search response"""
        if not response.success:
            return  # Don't cache failures

        key = self._make_key(query, num_results)
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]

            self._cache[key] = (time.time(), response)

    def clear(self):
        """Clear all cached results"""
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict:
        """Get cache statistics"""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl
            }


class RateLimiter:
    """Simple rate limiter with exponential backoff"""

    def __init__(self, min_delay: float = 1.0, max_delay: float = 30.0, backoff_factor: float = 2.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self._last_request = 0.0
        self._current_delay = min_delay
        self._consecutive_errors = 0
        self._lock = threading.Lock()

    def wait(self):
        """Wait appropriate amount before next request"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request
            if elapsed < self._current_delay:
                time.sleep(self._current_delay - elapsed)
            self._last_request = time.time()

    def success(self):
        """Call after successful request to reduce delay"""
        with self._lock:
            self._consecutive_errors = 0
            self._current_delay = self.min_delay

    def failure(self):
        """Call after failed request to increase delay"""
        with self._lock:
            self._consecutive_errors += 1
            self._current_delay = min(
                self._current_delay * self.backoff_factor,
                self.max_delay
            )

    def get_delay(self) -> float:
        """Get current delay value"""
        with self._lock:
            return self._current_delay


# Global cache and rate limiter (shared across instances)
_search_cache = SearchCache(ttl_seconds=300, max_size=100)
_rate_limiter = RateLimiter(min_delay=1.0, max_delay=30.0)


class WebSearch:
    """
    Free web search using DuckDuckGo.
    No API keys, no rate limits (within reason), just works.

    Features:
    - TTL cache (5 min default)
    - Exponential backoff on rate limits
    - Multiple fallback methods
    """

    def __init__(self, timeout: int = 10, use_cache: bool = True):
        """
        Args:
            timeout: Request timeout in seconds
            use_cache: Whether to use TTL cache (default: True)
        """
        self.timeout = timeout
        self.use_cache = use_cache

    def search(
        self,
        query: str,
        num_results: int = 10,
        region: str = "wt-wt"  # Worldwide
    ) -> SearchResponse:
        """
        Search DuckDuckGo and return structured results.

        Args:
            query: Search query string
            num_results: Maximum number of results to return
            region: Region code (default: worldwide)

        Returns:
            SearchResponse with results and metadata
        """
        # Check cache first
        if self.use_cache:
            cached = _search_cache.get(query, num_results)
            if cached:
                return cached

        start_time = time.time()

        # Wait for rate limiter
        _rate_limiter.wait()

        try:
            # Try using duckduckgo-search library (most reliable)
            response = self._search_with_ddgs(query, num_results, region, start_time)
            _rate_limiter.success()

            # Cache successful response
            if self.use_cache and response.success:
                _search_cache.set(query, num_results, response)

            return response

        except ImportError:
            # Fallback to HTML scraping
            return self._try_html_fallback(query, num_results, region, start_time)

        except Exception as e:
            _rate_limiter.failure()
            return self._try_html_fallback(query, num_results, region, start_time)

    def _try_html_fallback(
        self,
        query: str,
        num_results: int,
        region: str,
        start_time: float
    ) -> SearchResponse:
        """Try HTML scraping as fallback"""
        try:
            _rate_limiter.wait()
            response = self._search_with_html(query, num_results, region, start_time)
            _rate_limiter.success()

            if self.use_cache and response.success:
                _search_cache.set(query, num_results, response)

            return response

        except Exception as e:
            _rate_limiter.failure()
            elapsed_ms = int((time.time() - start_time) * 1000)
            return SearchResponse(
                query=query,
                results=[],
                total_results=0,
                search_time_ms=elapsed_ms,
                source="duckduckgo",
                success=False,
                error=f"All search methods failed: {str(e)}"
            )

    def _search_with_ddgs(
        self,
        query: str,
        num_results: int,
        region: str,
        start_time: float
    ) -> SearchResponse:
        """Search using duckduckgo-search library"""
        from duckduckgo_search import DDGS

        results = []

        with DDGS() as ddgs:
            ddg_results = list(ddgs.text(
                query,
                region=region,
                max_results=num_results
            ))

            for i, r in enumerate(ddg_results):
                results.append(SearchResult(
                    position=i + 1,
                    title=r.get('title', ''),
                    url=r.get('href', r.get('link', '')),
                    snippet=r.get('body', r.get('snippet', '')),
                    source="duckduckgo"
                ))

        elapsed_ms = int((time.time() - start_time) * 1000)

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            search_time_ms=elapsed_ms,
            source="duckduckgo",
            success=True
        )

    def _search_with_html(
        self,
        query: str,
        num_results: int,
        region: str,
        start_time: float
    ) -> SearchResponse:
        """Fallback: Search by scraping DuckDuckGo HTML"""
        import re
        import random
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import unquote

        DDG_URL = "https://html.duckduckgo.com/html/"

        USER_AGENTS = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        ]

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        data = {'q': query, 'kl': region}

        response = requests.post(
            DDG_URL,
            data=data,
            headers=headers,
            timeout=self.timeout
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'lxml')
        results = []

        for i, div in enumerate(soup.select('.result__body')[:num_results]):
            try:
                title_elem = div.select_one('.result__a')
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                href = title_elem.get('href', '')

                # Extract actual URL from DDG redirect
                if 'uddg=' in href:
                    url_match = re.search(r'uddg=([^&]+)', href)
                    url = unquote(url_match.group(1)) if url_match else href
                else:
                    url = href

                snippet_elem = div.select_one('.result__snippet')
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                if url and url.startswith('http'):
                    results.append(SearchResult(
                        position=len(results) + 1,
                        title=title,
                        url=url,
                        snippet=snippet,
                        source="duckduckgo"
                    ))
            except Exception:
                continue

        elapsed_ms = int((time.time() - start_time) * 1000)

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            search_time_ms=elapsed_ms,
            source="duckduckgo",
            success=True
        )


# Convenience functions for direct use

def search(query: str, num_results: int = 10) -> List[Dict]:
    """
    Quick search function - returns list of result dictionaries.

    Args:
        query: Search query
        num_results: Max results to return

    Returns:
        List of dicts with: position, title, url, snippet
    """
    searcher = WebSearch()
    response = searcher.search(query, num_results)
    return [r.to_dict() for r in response.results]


def search_urls(query: str, num_results: int = 10) -> List[str]:
    """
    Search and return just URLs.

    Args:
        query: Search query
        num_results: Max results

    Returns:
        List of URLs
    """
    searcher = WebSearch()
    response = searcher.search(query, num_results)
    return [r.url for r in response.results]


def search_full(query: str, num_results: int = 10) -> Dict:
    """
    Full search with metadata.

    Args:
        query: Search query
        num_results: Max results

    Returns:
        Full SearchResponse as dict (includes 'cached' flag)
    """
    searcher = WebSearch()
    response = searcher.search(query, num_results)
    return response.to_dict()


def get_cache_stats() -> Dict:
    """Get search cache statistics"""
    return _search_cache.stats()


def clear_cache():
    """Clear the search cache"""
    _search_cache.clear()


if __name__ == '__main__':
    # Test the search
    print("Testing DuckDuckGo search...\n")

    query = "python web scraping tutorial"
    print(f"Query: {query}\n")

    # First search (not cached)
    results = search_full(query, num_results=5)
    print(f"Results: {results['total_results']}, Cached: {results['cached']}")

    # Second search (should be cached)
    results2 = search_full(query, num_results=5)
    print(f"Results: {results2['total_results']}, Cached: {results2['cached']}")

    print(f"\nCache stats: {get_cache_stats()}")
