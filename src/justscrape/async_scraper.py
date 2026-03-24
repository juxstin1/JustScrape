"""
Async Web Scraper - httpx + HTTP/2 based async scraping.

Replaces the run_in_executor pattern in the MCP server with truly async
HTTP operations. Uses httpx with HTTP/2 support and connection pooling.

Features:
- HTTP/2 multiplexing (multiple requests over one connection)
- Async-native (fits directly in MCP server's asyncio loop)
- Configurable connection pooling and timeouts
- HEAD pre-check built-in
- Per-domain concurrency limiting
"""

import asyncio
import time
import re
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse
from dataclasses import dataclass

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from bs4 import BeautifulSoup
from .web_scraper import ScrapedContent, ContentType


# Per-domain concurrency semaphores
_domain_semaphores: Dict[str, asyncio.Semaphore] = {}
_MAX_DOMAIN_SEMAPHORES = 500
_global_semaphore = asyncio.Semaphore(10)  # max 10 concurrent requests total


def _get_domain_semaphore(url: str, max_per_domain: int = 2) -> asyncio.Semaphore:
    """Get or create a per-domain concurrency limiter."""
    domain = urlparse(url).netloc.lower()
    if domain not in _domain_semaphores:
        # Evict oldest if at capacity
        if len(_domain_semaphores) >= _MAX_DOMAIN_SEMAPHORES:
            oldest = next(iter(_domain_semaphores))
            del _domain_semaphores[oldest]
        _domain_semaphores[domain] = asyncio.Semaphore(max_per_domain)
    return _domain_semaphores[domain]


class AsyncWebScraper:
    """
    Async HTTP/2 web scraper using httpx.
    Drop-in replacement for WebScraper's fetch layer in async contexts.
    """

    def __init__(
        self,
        timeout_connect: float = 5,
        timeout_read: float = 15,
        max_connections: int = 20,
        max_keepalive: int = 10,
        use_http2: bool = True,
    ):
        if not HTTPX_AVAILABLE:
            raise ImportError("httpx is required for AsyncWebScraper. Install with: pip install httpx[http2]")

        self.client = httpx.AsyncClient(
            http2=use_http2,
            follow_redirects=True,
            timeout=httpx.Timeout(
                connect=timeout_connect,
                read=timeout_read,
                write=5.0,
                pool=10.0,
            ),
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive,
            ),
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
            },
        )
        self._closed = False

    async def close(self):
        if not self._closed:
            await self.client.aclose()
            self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def head_check(self, url: str) -> Tuple[bool, Dict]:
        """Async HEAD pre-check."""
        try:
            resp = await self.client.head(url, timeout=5.0)
            info = {
                "status_code": resp.status_code,
                "final_url": str(resp.url),
                "content_type": resp.headers.get("content-type", ""),
                "content_length": resp.headers.get("content-length", ""),
                "http_version": resp.http_version,
            }

            if resp.status_code in (401, 403, 429, 451):
                return False, {**info, "reason": f"status:{resp.status_code}"}

            ct = info["content_type"].lower()
            if ct and not any(t in ct for t in ("text/html", "text/plain", "application/xhtml")):
                return False, {**info, "reason": f"content_type:{ct}"}

            if info["content_length"]:
                try:
                    if int(info["content_length"]) > 5 * 1024 * 1024:
                        return False, {**info, "reason": "too_large"}
                except ValueError:
                    pass

            final_path = urlparse(str(resp.url)).path.lower()
            if any(p in final_path for p in ["/login", "/signin", "/signup", "/auth"]):
                return False, {**info, "reason": f"redirect_to_login:{resp.url}"}

            return True, info

        except Exception:
            return True, {"reason": "head_failed"}

    async def fetch(self, url: str, check_head: bool = True) -> Tuple[Optional[str], int, Dict]:
        """
        Async fetch with per-domain concurrency limiting.
        Returns (html, status_code, info).
        """
        # SSRF protection: validate URL before any outbound request
        from .url_validator import validate_url
        url_ok, url_reason = validate_url(url)
        if not url_ok:
            return None, 0, {"reason": f"blocked:{url_reason}"}

        domain_sem = _get_domain_semaphore(url)

        async with _global_semaphore:
            async with domain_sem:
                info = {}

                # HEAD pre-check
                if check_head:
                    ok, head_info = await self.head_check(url)
                    info["head_check"] = head_info
                    if not ok:
                        return None, head_info.get("status_code", 0), info

                try:
                    resp = await self.client.get(url)
                    info["http_version"] = resp.http_version
                    info["response_time_ms"] = int(resp.elapsed.total_seconds() * 1000) if resp.elapsed else 0
                    return resp.text, resp.status_code, info
                except Exception as e:
                    info["error"] = str(e)
                    return None, 0, info

    async def scrape(
        self,
        url: str,
        content_types: List[ContentType] = None,
        check_head: bool = True,
    ) -> ScrapedContent:
        """Async scrape with extraction (mirrors WebScraper.scrape)."""
        if content_types is None:
            content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]

        html, status_code, info = await self.fetch(url, check_head=check_head)

        if not html:
            return ScrapedContent(url=url, status_code=status_code, scrape_method="async_httpx")

        soup = BeautifulSoup(html, "html.parser")
        result = ScrapedContent(url=url, status_code=status_code, scrape_method="async_httpx")

        for ct in content_types:
            if ct == ContentType.CLEAN_TEXT:
                result.content = self._extract_clean_text(soup)
            elif ct == ContentType.METADATA:
                result.metadata = self._extract_metadata(soup)
                result.title = result.metadata.get("title")
            elif ct == ContentType.LINKS:
                result.links = self._extract_links(soup, url)

        return result

    async def scrape_many(
        self,
        urls: List[str],
        content_types: List[ContentType] = None,
    ) -> List[ScrapedContent]:
        """Scrape multiple URLs concurrently."""
        tasks = [self.scrape(url, content_types) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=False)

    # --- Extraction methods (mirrored from WebScraper) ---

    def _extract_clean_text(self, soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe", "noscript"]):
            tag.decompose()

        ad_patterns = [
            r'\bad[s]?\b', r'\badvertisement\b', r'\bbanner\b', r'\bpromo\b', r'\bsponsor\b',
            r'\bpopup\b', r'\bmodal\b', r'\bcookie\b', r'\bnewsletter\b', r'\bsidebar\b',
        ]
        for pattern in ad_patterns:
            for el in soup.find_all(class_=re.compile(pattern, re.I)):
                el.decompose()
            for el in soup.find_all(id=re.compile(pattern, re.I)):
                el.decompose()

        main = (
            soup.find("article") or soup.find("main") or
            soup.find(class_=re.compile("content|article|post|entry", re.I)) or
            soup.find(id=re.compile("content|article|post|entry", re.I)) or
            soup.find("body")
        )

        if main:
            text = main.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            cleaned = []
            prev = None
            for line in lines:
                if line != prev:
                    cleaned.append(line)
                    prev = line
            return "\n\n".join(cleaned)

        return soup.get_text(separator="\n", strip=True)

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict:
        metadata = {"title": None, "description": None, "author": None, "og_data": {}}

        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.string

        for meta in soup.find_all("meta"):
            name = meta.get("name", "").lower()
            prop = meta.get("property", "").lower()
            content = meta.get("content", "")

            if name == "description":
                metadata["description"] = content
            elif name == "author":
                metadata["author"] = content
            if prop.startswith("og:"):
                metadata["og_data"][prop] = content

        return metadata

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        from urllib.parse import urljoin
        links = set()
        for a in soup.find_all("a", href=True):
            links.add(urljoin(base_url, a["href"]))
        return list(links)


# Singleton for use across MCP handlers
_async_scraper: Optional[AsyncWebScraper] = None


def get_async_scraper() -> AsyncWebScraper:
    """Get or create the global async scraper instance."""
    global _async_scraper
    if _async_scraper is None or _async_scraper._closed:
        _async_scraper = AsyncWebScraper()
    return _async_scraper
