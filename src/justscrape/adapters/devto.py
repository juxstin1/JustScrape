"""
Dev.to adapter — scrapes dev.to articles via the public API.
"""

import json
import re
from typing import Optional, List
from urllib.parse import urlparse

from ..web_scraper import ContentType, ScrapedContent
from . import base as _base_mod
from .base import SourceAdapter


class DevToAdapter(SourceAdapter):
    """Scrape dev.to article pages via their public JSON API."""

    @staticmethod
    def can_handle(url: str) -> bool:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        return domain.endswith('dev.to')

    def scrape(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        parsed = urlparse(url)
        parts = [p for p in (parsed.path or "").split("/") if p]
        if len(parts) < 2:
            return None

        username = parts[0]
        slug = parts[1]
        base = "https://dev.to/api/articles"
        api_urls = [f"{base}/{username}/{slug}"]
        id_match = re.search(r"-(\d+)$", slug)
        if id_match:
            api_urls.append(f"{base}/{id_match.group(1)}")

        headers = {
            "User-Agent": "justscrape/1.0 (devto-api-adapter)",
            "Accept": "application/json",
        }

        payload = None
        chosen_api_url = None
        for api_url in api_urls:
            resp = _base_mod._safe_get(api_url, headers=headers, timeout=15)
            if resp is not None:
                try:
                    payload = resp.json()
                    chosen_api_url = api_url
                    break
                except Exception:
                    continue

        if not payload:
            return None

        title = payload.get("title")
        body_markdown = payload.get("body_markdown") or ""
        description = payload.get("description") or ""
        content_text = body_markdown.strip() or description.strip()
        if not content_text:
            return None

        result = ScrapedContent(
            url=url,
            title=title,
            status_code=200,
            scrape_method="devto_api",
        )

        author = (payload.get("user") or {}).get("name") or (payload.get("user") or {}).get("username")
        metadata = {
            "source": "devto_api",
            "api_url": chosen_api_url,
            "description": description,
            "tags": payload.get("tags", []),
            "author": author,
            "published_date": payload.get("published_at") or payload.get("readable_publish_date"),
            "reading_time_minutes": payload.get("reading_time_minutes"),
            "title": title,
        }

        links = []
        canonical = payload.get("canonical_url")
        article_url = payload.get("url")
        if canonical and canonical.startswith("http"):
            links.append(canonical)
        if article_url and article_url.startswith("http"):
            links.append(article_url)
        for found in re.findall(r"https?://[^\s)>\"]+", content_text):
            links.append(found)

        if ContentType.METADATA in content_types:
            result.metadata = metadata
        if ContentType.LINKS in content_types:
            result.links = list(dict.fromkeys(links))
        if ContentType.CLEAN_TEXT in content_types:
            result.content = content_text
        elif ContentType.FULL_HTML in content_types:
            result.content = json.dumps(payload, indent=2)

        has_useful = bool(result.content) or bool(result.links) or bool(result.title)
        return result if has_useful else None
