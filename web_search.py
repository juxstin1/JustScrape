"""
Free Web Search Module - DuckDuckGo-based search
No API keys required - just works.

This module provides free web search capabilities using DuckDuckGo.
Designed to be used as a tool/capability worker - deterministic, no reasoning.

Uses the duckduckgo-search library for reliable results, with fallback to HTML scraping.
"""

import time
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict


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

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "total_results": self.total_results,
            "search_time_ms": self.search_time_ms,
            "source": self.source,
            "success": self.success,
            "error": self.error
        }


class WebSearch:
    """
    Free web search using DuckDuckGo.
    No API keys, no rate limits (within reason), just works.

    Uses duckduckgo-search library for robust results.
    """

    def __init__(self, timeout: int = 10):
        """
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout

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
        start_time = time.time()

        try:
            # Try using duckduckgo-search library (most reliable)
            return self._search_with_ddgs(query, num_results, region, start_time)
        except ImportError:
            # Fallback to HTML scraping
            return self._search_with_html(query, num_results, region, start_time)
        except Exception as e:
            # Try HTML fallback on any error
            try:
                return self._search_with_html(query, num_results, region, start_time)
            except Exception as e2:
                elapsed_ms = int((time.time() - start_time) * 1000)
                return SearchResponse(
                    query=query,
                    results=[],
                    total_results=0,
                    search_time_ms=elapsed_ms,
                    source="duckduckgo",
                    success=False,
                    error=f"All search methods failed: {str(e2)}"
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
        Full SearchResponse as dict
    """
    searcher = WebSearch()
    response = searcher.search(query, num_results)
    return response.to_dict()


if __name__ == '__main__':
    # Test the search
    print("Testing DuckDuckGo search...\n")

    query = "python web scraping tutorial"
    print(f"Query: {query}\n")

    results = search(query, num_results=5)

    if results:
        for r in results:
            print(f"{r['position']}. {r['title']}")
            print(f"   URL: {r['url']}")
            print(f"   {r['snippet'][:100]}..." if r['snippet'] else "   (no snippet)")
            print()
    else:
        print("No results found. Check your network connection.")
