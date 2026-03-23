"""
Google search backend — scrapes Google search results directly.

No API key required. Uses the consent-bypass cookie and rotating
user agents. Falls back gracefully on CAPTCHA/block.
"""

import time
import random
from urllib.parse import urlparse, parse_qs


import requests
from bs4 import BeautifulSoup
from ..web_search import SearchResponse, SearchResult
from .base import SearchBackend

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
]

_DATE_RANGE_MAP = {
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
}


def _extract_url_from_google_redirect(href: str) -> str:
    """Extract actual URL from Google's /url?q= redirect wrapper."""
    if href and href.startswith("/url?"):
        parsed = parse_qs(urlparse(href).query)
        actual = parsed.get("q", [None])[0]
        if actual:
            return actual
    return href


class GoogleBackend(SearchBackend):
    """Scrapes Google search results directly. No API key needed."""

    name = "google"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._session = requests.Session()
        # Set consent cookie to bypass EU consent wall
        self._session.cookies.set("CONSENT", "PENDING+987", domain=".google.com")
        self._session.cookies.set("SOCS", "CAISHAgBEhJnd3NfMjAyMzA4MTUtMF9SQzIaAmVuIAEaBgiAo_CmBg", domain=".google.com")

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
            "num": min(num_results + 5, 20),
            "hl": "en",
            "safe": "off",
        }

        if date_range and date_range in _DATE_RANGE_MAP:
            params["tbs"] = f"qdr:{_DATE_RANGE_MAP[date_range]}"

        ua = random.choice(_USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
        }

        try:
            resp = self._session.get(
                "https://www.google.com/search",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )

            if "sorry/index" in resp.url or resp.status_code == 429:
                return self._fail(query, start_time, "Google CAPTCHA or rate limit")

            # Check for consent redirect / JS-required page
            text = resp.text
            if "Please click here if you are not redirected" in text or len(text) < 5000:
                return self._fail(query, start_time, "Google consent wall or empty response")

            results = self._parse_results(text, num_results)
            elapsed_ms = int((time.time() - start_time) * 1000)

            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                search_time_ms=elapsed_ms,
                source="google",
                success=len(results) > 0,
            )

        except Exception as e:
            return self._fail(query, start_time, str(e))

    def _fail(self, query, start_time, error):
        return SearchResponse(
            query=query,
            results=[],
            total_results=0,
            search_time_ms=int((time.time() - start_time) * 1000),
            source="google",
            success=False,
            error=error,
        )

    def _parse_results(self, html: str, max_results: int) -> list:
        """Parse Google search results from HTML."""
        soup = BeautifulSoup(html, "lxml")
        results = []
        position = 1

        # Strategy 1: div.g containers (classic Google)
        for div in soup.select("div.g"):
            if position > max_results:
                break
            result = self._extract_from_container(div, position)
            if result:
                results.append(result)
                position += 1

        if results:
            return results

        # Strategy 2: h3 inside anchors (newer layouts)
        for h3 in soup.select("h3"):
            if position > max_results:
                break
            parent_a = h3.find_parent("a")
            if not parent_a:
                continue
            href = parent_a.get("href", "")
            url = _extract_url_from_google_redirect(href)
            if not url or not url.startswith("http"):
                continue

            title = h3.get_text(strip=True)
            if not title:
                continue

            results.append(
                SearchResult(
                    position=position,
                    title=title,
                    url=url,
                    snippet="",
                    source="google",
                )
            )
            position += 1

        return results

    def _extract_from_container(self, div, position) -> SearchResult | None:
        link_tag = div.select_one("a[href]")
        if not link_tag:
            return None

        href = link_tag.get("href", "")
        url = _extract_url_from_google_redirect(href)
        if not url or not url.startswith("http"):
            return None

        title_tag = div.select_one("h3")
        title = title_tag.get_text(strip=True) if title_tag else ""

        snippet = ""
        for selector in ["div[data-sncf]", "div.VwiC3b", "span.aCOpRe", "div.IsZvec"]:
            snippet_tag = div.select_one(selector)
            if snippet_tag:
                snippet = snippet_tag.get_text(strip=True)
                break

        if not title and not snippet:
            return None

        return SearchResult(
            position=position,
            title=title,
            url=url,
            snippet=snippet,
            source="google",
        )

    def is_available(self) -> bool:
        return True
