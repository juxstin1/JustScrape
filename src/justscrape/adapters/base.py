"""
Base class for source-specific scrapers (adapters).

Provides the SourceAdapter ABC and shared utilities like _safe_get().
"""

from abc import ABC, abstractmethod
from typing import Optional, List

import requests

from ..web_scraper import ContentType, ScrapedContent

# Maximum response size for adapter HTTP requests (10 MB)
MAX_ADAPTER_RESPONSE_SIZE = 10 * 1024 * 1024


def _safe_get(url: str, headers: dict = None, timeout: int = 15) -> Optional[requests.Response]:
    """HTTP GET with response size cap. Returns None if too large or on error."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
        if resp.status_code != 200:
            resp.close()
            return None
        # Check Content-Length header first
        cl = resp.headers.get('content-length')
        if cl and int(cl) > MAX_ADAPTER_RESPONSE_SIZE:
            resp.close()
            return None
        # Read with size cap
        chunks = []
        size = 0
        for chunk in resp.iter_content(chunk_size=8192):
            size += len(chunk)
            if size > MAX_ADAPTER_RESPONSE_SIZE:
                resp.close()
                return None
            chunks.append(chunk)
        resp._content = b"".join(chunks)
        return resp
    except Exception:
        return None


class SourceAdapter(ABC):
    """Abstract base class for domain-specific source adapters."""

    @staticmethod
    @abstractmethod
    def can_handle(url: str) -> bool:
        """Return True if this adapter can handle the given URL."""
        ...

    @abstractmethod
    def scrape(self, url: str, content_types: List[ContentType]) -> Optional[ScrapedContent]:
        """
        Scrape the URL and return a ScrapedContent, or None on failure.

        Parameters
        ----------
        url : str
            The validated URL to scrape.
        content_types : list[ContentType]
            Which content facets the caller wants populated.
        """
        ...
