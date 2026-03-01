"""
Free Web Search Module - Multi-backend search with DuckDuckGo default
No API keys required - just works.

This module provides free web search capabilities using DuckDuckGo
with optional SearXNG and Brave Search backends.

Features:
- TTL cache (in-memory L1 + SQLite L2 persistent)
- Per-domain rate limiting with exponential backoff
- Multiple search backends with automatic fallback
- Search result deduplication and merging
- Query operator support (site:, date range, filetype)
"""

import time
import hashlib
import threading
import sqlite3
import os
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict, field
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse


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
    """Simple TTL cache for search results (L1 in-memory)"""

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
                    del self._cache[key]
        return None

    def set(self, query: str, num_results: int, response: SearchResponse):
        """Cache a search response"""
        if not response.success:
            return

        key = self._make_key(query, num_results)
        with self._lock:
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


class PersistentSearchCache:
    """L2 SQLite-backed persistent cache that survives server restarts"""

    def __init__(self, db_path: str = None, ttl_seconds: int = 86400):
        if db_path is None:
            db_path = os.path.join(os.path.expanduser("~"), ".scraper_search_cache.db")
        self.db_path = db_path
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    cache_key TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    num_results INTEGER NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_created ON search_cache(created_at)")
            conn.commit()
            conn.close()

    def _make_key(self, query: str, num_results: int) -> str:
        raw = f"{query.lower().strip()}:{num_results}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, query: str, num_results: int) -> Optional[SearchResponse]:
        """Get from persistent cache if not expired"""
        key = self._make_key(query, num_results)
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    "SELECT response_json, created_at FROM search_cache WHERE cache_key = ?",
                    (key,)
                )
                row = cursor.fetchone()
                conn.close()

                if row:
                    response_json, created_at = row
                    if time.time() - created_at < self.ttl:
                        data = __import__('json').loads(response_json)
                        results = [
                            SearchResult(
                                position=r["position"],
                                title=r["title"],
                                url=r["url"],
                                snippet=r["snippet"],
                                source=r.get("source", "duckduckgo")
                            )
                            for r in data.get("results", [])
                        ]
                        return SearchResponse(
                            query=data["query"],
                            results=results,
                            total_results=data["total_results"],
                            search_time_ms=0,
                            source=data.get("source", "duckduckgo"),
                            success=True,
                            cached=True
                        )
            except Exception:
                pass
        return None

    def set(self, query: str, num_results: int, response: SearchResponse):
        """Store in persistent cache"""
        if not response.success:
            return

        key = self._make_key(query, num_results)
        import json as _json
        response_json = _json.dumps(response.to_dict())

        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "INSERT OR REPLACE INTO search_cache (cache_key, query, num_results, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (key, query.lower().strip(), num_results, response_json, time.time())
                )
                # Prune expired entries occasionally
                conn.execute("DELETE FROM search_cache WHERE created_at < ?", (time.time() - self.ttl,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def clear(self):
        """Clear persistent cache"""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute("DELETE FROM search_cache")
                conn.commit()
                conn.close()
            except Exception:
                pass

    def stats(self) -> Dict:
        """Get persistent cache statistics"""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute("SELECT COUNT(*) FROM search_cache WHERE created_at > ?", (time.time() - self.ttl,))
                count = cursor.fetchone()[0]
                conn.close()
                return {"size": count, "ttl_seconds": self.ttl, "db_path": self.db_path}
            except Exception:
                return {"size": 0, "ttl_seconds": self.ttl, "db_path": self.db_path}


class PerDomainRateLimiter:
    """Rate limiter that tracks delays per domain instead of globally"""

    def __init__(self, default_delay: float = 1.0, max_delay: float = 30.0, backoff_factor: float = 2.0):
        self.default_delay = default_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self._domains: Dict[str, Dict] = {}  # domain -> {last_request, current_delay, errors}
        self._lock = threading.Lock()

    def _get_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return "__global__"

    def _get_state(self, domain: str) -> Dict:
        if domain not in self._domains:
            self._domains[domain] = {
                "last_request": 0.0,
                "current_delay": self.default_delay,
                "consecutive_errors": 0
            }
        return self._domains[domain]

    def wait(self, url: str = None):
        """Wait based on the specific domain's rate limit"""
        domain = self._get_domain(url) if url else "__global__"
        with self._lock:
            state = self._get_state(domain)
            now = time.time()
            elapsed = now - state["last_request"]
            wait_time = state["current_delay"] - elapsed
        # Sleep outside the lock
        if wait_time > 0:
            time.sleep(wait_time)
        with self._lock:
            state = self._get_state(domain)
            state["last_request"] = time.time()

    def success(self, url: str = None):
        """Reset delay after successful request"""
        domain = self._get_domain(url) if url else "__global__"
        with self._lock:
            state = self._get_state(domain)
            state["consecutive_errors"] = 0
            state["current_delay"] = self.default_delay

    def failure(self, url: str = None):
        """Increase delay after failed request"""
        domain = self._get_domain(url) if url else "__global__"
        with self._lock:
            state = self._get_state(domain)
            state["consecutive_errors"] += 1
            state["current_delay"] = min(
                state["current_delay"] * self.backoff_factor,
                self.max_delay
            )

    def get_delay(self, url: str = None) -> float:
        domain = self._get_domain(url) if url else "__global__"
        with self._lock:
            return self._get_state(domain)["current_delay"]


class RateLimiter:
    """Simple rate limiter with exponential backoff (legacy, wraps PerDomainRateLimiter)"""

    def __init__(self, min_delay: float = 1.0, max_delay: float = 30.0, backoff_factor: float = 2.0):
        self._inner = PerDomainRateLimiter(min_delay, max_delay, backoff_factor)

    def wait(self):
        self._inner.wait()

    def success(self):
        self._inner.success()

    def failure(self):
        self._inner.failure()

    def get_delay(self) -> float:
        return self._inner.get_delay()


# =============================================================================
# URL NORMALIZATION (for deduplication)
# =============================================================================

def normalize_url(url: str) -> str:
    """Normalize URL for deduplication — strip tracking params and trailing slashes"""
    try:
        parsed = urlparse(url)
        # Strip tracking parameters
        tracking_params = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                          'utm_content', 'ref', 'fbclid', 'gclid', 'msclkid'}
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            cleaned = {k: v for k, v in params.items() if k.lower() not in tracking_params}
            query = urlencode(cleaned, doseq=True) if cleaned else ''
        else:
            query = ''
        # Strip trailing slash from path
        path = parsed.path.rstrip('/') or '/'
        return urlunparse((parsed.scheme, parsed.netloc.lower(), path, parsed.params, query, ''))
    except Exception:
        return url


# =============================================================================
# SNIPPET PRE-FILTERING
# =============================================================================

# Domains known to block scrapers
KNOWN_BLOCKED_DOMAINS = {
    'medium.com', 'reddit.com', 'www.reddit.com', 'old.reddit.com',
    'twitter.com', 'x.com', 'linkedin.com', 'www.linkedin.com',
    'facebook.com', 'www.facebook.com', 'instagram.com', 'www.instagram.com',
}

# URL path patterns that are rarely useful content
SKIP_PATH_PATTERNS = ['/login', '/signup', '/register', '/terms', '/privacy',
                      '/cookie', '/tos', '/legal', '/auth', '/account/']


def should_scrape(url: str, snippet: str = "") -> Tuple[bool, str]:
    """
    Pre-filter: decide if a search result is worth scraping.
    Returns (should_scrape, reason).
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace('www.', '')
        path = parsed.path.lower()

        # Skip known-blocked domains
        if domain in KNOWN_BLOCKED_DOMAINS or any(d in domain for d in KNOWN_BLOCKED_DOMAINS):
            return False, f"blocked_domain:{domain}"

        # Skip login/signup/legal pages
        if any(p in path for p in SKIP_PATH_PATTERNS):
            return False, f"skip_path:{path}"

        # Skip non-HTML file extensions
        non_html = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.tar', '.gz',
                    '.mp4', '.mp3', '.avi', '.mov', '.jpg', '.jpeg', '.png', '.gif', '.svg')
        if any(path.endswith(ext) for ext in non_html):
            return False, f"non_html_file:{path.split('.')[-1]}"

    except Exception:
        pass

    return True, "ok"


# =============================================================================
# RELEVANCE SCORING
# =============================================================================

def relevance_score(query: str, content: str, title: str = "") -> float:
    """
    Score 0.0-1.0 for how relevant scraped content is to the search query.
    Uses lightweight text-matching heuristics (no LLM).
    """
    if not content:
        return 0.0

    # Tokenize query into meaningful terms (3+ chars, lowered)
    query_terms = set(t for t in query.lower().split() if len(t) >= 3)
    if not query_terms:
        query_terms = set(query.lower().split())
    if not query_terms:
        return 0.5  # Can't score without terms

    content_lower = content.lower()
    title_lower = (title or "").lower()
    content_words = max(len(content.split()), 1)

    # Term frequency (normalized, capped at 1.0)
    term_hits = sum(content_lower.count(term) for term in query_terms)
    tf_score = min(term_hits / content_words * 50, 1.0)

    # Title match
    title_hits = sum(1 for term in query_terms if term in title_lower)
    title_score = title_hits / len(query_terms)

    # Content length bonus (longer structured content is usually better)
    length_score = min(len(content) / 5000, 1.0)

    # Combined weighted score
    return round(0.45 * tf_score + 0.35 * title_score + 0.20 * length_score, 3)


# Global cache and rate limiter (shared across instances)
_search_cache = SearchCache(ttl_seconds=300, max_size=100)
_persistent_cache = PersistentSearchCache()
_rate_limiter = PerDomainRateLimiter(default_delay=1.0, max_delay=30.0)


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
        region: str = "wt-wt",
        site: str = None,
        filetype: str = None,
        exclude_sites: List[str] = None,
        date_range: str = None,
    ) -> SearchResponse:
        """
        Search DuckDuckGo and return structured results.

        Args:
            query: Search query string
            num_results: Maximum number of results to return
            region: Region code (default: worldwide)
            site: Restrict to specific site (e.g., "docs.python.org")
            filetype: Restrict to file type (e.g., "pdf")
            exclude_sites: List of domains to exclude
            date_range: Date filter — "day", "week", "month", "year"

        Returns:
            SearchResponse with results and metadata
        """
        # Build effective query with operators
        effective_query = build_query(query, site=site, filetype=filetype,
                                       exclude_sites=exclude_sites)

        # Check L1 (memory) cache
        if self.use_cache:
            cached = _search_cache.get(effective_query, num_results)
            if cached:
                return cached

            # Check L2 (persistent SQLite) cache
            cached = _persistent_cache.get(effective_query, num_results)
            if cached:
                # Promote to L1
                _search_cache.set(effective_query, num_results, cached)
                return cached

        start_time = time.time()

        # Wait for rate limiter (keyed to DuckDuckGo domain)
        _rate_limiter.wait("https://duckduckgo.com")

        try:
            response = self._search_with_ddgs(effective_query, num_results, region, start_time, date_range)
            _rate_limiter.success("https://duckduckgo.com")

            # Cache to both layers
            if self.use_cache and response.success:
                _search_cache.set(effective_query, num_results, response)
                _persistent_cache.set(effective_query, num_results, response)

            return response

        except ImportError:
            return self._try_html_fallback(effective_query, num_results, region, start_time)

        except Exception as e:
            _rate_limiter.failure("https://duckduckgo.com")
            return self._try_html_fallback(effective_query, num_results, region, start_time)

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
        start_time: float,
        date_range: str = None,
    ) -> SearchResponse:
        """Search using duckduckgo-search library"""
        from duckduckgo_search import DDGS

        results = []

        # Map date_range to DDGS timelimit parameter
        timelimit = None
        if date_range:
            timelimit_map = {"day": "d", "week": "w", "month": "m", "year": "y"}
            timelimit = timelimit_map.get(date_range)

        with DDGS() as ddgs:
            kwargs = dict(keywords=query, region=region, max_results=num_results)
            if timelimit:
                kwargs["timelimit"] = timelimit
            ddg_results = list(ddgs.text(**kwargs))

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


# =============================================================================
# QUERY BUILDING
# =============================================================================

def build_query(query: str, site: str = None, filetype: str = None,
                exclude_sites: List[str] = None) -> str:
    """
    Build search query with operators.

    Args:
        query: Base search query
        site: Restrict to site (e.g., "docs.python.org")
        filetype: Restrict to file type (e.g., "pdf")
        exclude_sites: Domains to exclude
    """
    parts = [query]
    if site:
        parts.append(f"site:{site}")
    if filetype:
        parts.append(f"filetype:{filetype}")
    if exclude_sites:
        for s in exclude_sites:
            parts.append(f"-site:{s}")
    return " ".join(parts)


# =============================================================================
# RESULT MERGING / DEDUP (for multi-backend use)
# =============================================================================

def merge_search_results(responses: List[SearchResponse]) -> SearchResponse:
    """
    Merge results from multiple search backends, deduplicating by URL.
    Round-robin interleaves unique results for diversity.
    Keeps the longest snippet when duplicates are found.
    """
    seen_urls: Dict[str, SearchResult] = {}
    merged: List[SearchResult] = []
    all_sources = []

    for response in responses:
        if not response.success:
            continue
        all_sources.append(response.source)
        for result in response.results:
            norm = normalize_url(result.url)
            if norm not in seen_urls:
                seen_urls[norm] = result
                merged.append(result)
            else:
                existing = seen_urls[norm]
                if len(result.snippet) > len(existing.snippet):
                    existing.snippet = result.snippet

    # Re-number positions
    for i, r in enumerate(merged):
        r.position = i + 1

    query = responses[0].query if responses else ""
    return SearchResponse(
        query=query,
        results=merged,
        total_results=len(merged),
        search_time_ms=sum(r.search_time_ms for r in responses if r.success),
        source="+".join(all_sources) if all_sources else "none",
        success=len(merged) > 0
    )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def search(query: str, num_results: int = 10, **kwargs) -> List[Dict]:
    """
    Quick search function - returns list of result dictionaries.

    Args:
        query: Search query
        num_results: Max results to return
        **kwargs: Additional args (site, filetype, exclude_sites, date_range)

    Returns:
        List of dicts with: position, title, url, snippet
    """
    searcher = WebSearch()
    response = searcher.search(query, num_results, **kwargs)
    return [r.to_dict() for r in response.results]


def search_urls(query: str, num_results: int = 10) -> List[str]:
    """Search and return just URLs."""
    searcher = WebSearch()
    response = searcher.search(query, num_results)
    return [r.url for r in response.results]


def search_full(query: str, num_results: int = 10, **kwargs) -> Dict:
    """
    Full search with metadata.

    Args:
        query: Search query
        num_results: Max results
        **kwargs: Additional args (site, filetype, exclude_sites, date_range)

    Returns:
        Full SearchResponse as dict (includes 'cached' flag)
    """
    searcher = WebSearch()
    response = searcher.search(query, num_results, **kwargs)
    return response.to_dict()


def get_cache_stats() -> Dict:
    """Get search cache statistics (both L1 memory and L2 persistent)"""
    return {
        "memory": _search_cache.stats(),
        "persistent": _persistent_cache.stats()
    }


def clear_cache():
    """Clear both memory and persistent search caches"""
    _search_cache.clear()
    _persistent_cache.clear()


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
