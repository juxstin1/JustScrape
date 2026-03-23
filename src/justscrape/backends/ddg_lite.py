"""
DuckDuckGo Lite search backend — scrapes the HTML lite interface directly.

The DDG library (duckduckgo-search) frequently returns empty results due to
rate limiting and CAPTCHA. The lite HTML interface at lite.duckduckgo.com
is far more reliable for programmatic access.

No API key, no external library beyond requests + BeautifulSoup.
"""

import time
import random
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
from ..web_search import SearchResponse, SearchResult
from .base import SearchBackend

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]

_DATE_RANGE_MAP = {
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
}


def _unwrap_ddg_redirect(href: str) -> str:
    """Extract actual URL from DDG's //duckduckgo.com/l/?uddg= redirect."""
    if "uddg=" in href:
        parsed = parse_qs(urlparse(href).query)
        actual = parsed.get("uddg", [None])[0]
        if actual:
            return unquote(actual)
    # Sometimes href is already the direct URL
    if href.startswith("http"):
        return href
    return ""


class DDGLiteBackend(SearchBackend):
    """Scrapes DuckDuckGo's lite HTML interface. Reliable and API-free."""

    name = "ddg_lite"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def search(
        self,
        query: str,
        num_results: int = 10,
        region: str = "wt-wt",
        date_range: str = None,
    ) -> SearchResponse:
        start_time = time.time()

        params = {"q": query}
        if date_range and date_range in _DATE_RANGE_MAP:
            params["df"] = _DATE_RANGE_MAP[date_range]

        ua = random.choice(_USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://lite.duckduckgo.com/",
        }

        try:
            resp = requests.get(
                "https://lite.duckduckgo.com/lite/",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()

            results = self._parse_results(resp.text, num_results)
            elapsed_ms = int((time.time() - start_time) * 1000)

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                search_time_ms=elapsed_ms,
                source="ddg_lite",
                success=len(results) > 0,
            )

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return SearchResponse(
                query=query,
                results=[],
                total_results=0,
                search_time_ms=elapsed_ms,
                source="ddg_lite",
                success=False,
                error=str(e),
            )

    def _parse_results(self, html: str, max_results: int) -> list:
        """Parse DDG lite search results.

        DDG lite uses a table layout where results appear as:
        - <a class="result-link"> for title + URL
        - <td class="result-snippet"> for snippet text
        These appear in sequential <tr> rows.
        """
        soup = BeautifulSoup(html, "lxml")
        results = []
        position = 1

        # Collect all result links and snippets
        link_rows = soup.select("a.result-link")
        snippet_rows = soup.select("td.result-snippet")

        for i, link_tag in enumerate(link_rows):
            if position > max_results:
                break

            href = link_tag.get("href", "")
            url = _unwrap_ddg_redirect(href)
            if not url or not url.startswith("http"):
                continue

            title = link_tag.get_text(strip=True)
            if not title:
                continue

            snippet = ""
            if i < len(snippet_rows):
                snippet = snippet_rows[i].get_text(strip=True)

            results.append(
                SearchResult(
                    position=position,
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="ddg_lite",
                )
            )
            position += 1

        return results

    def is_available(self) -> bool:
        return True
