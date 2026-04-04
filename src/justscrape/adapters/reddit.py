"""
Reddit adapter — scrapes Reddit via JSON endpoints without browser automation.

Supports subreddit listings and thread pages.
"""

import json
import re
from typing import Optional, List, Dict
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from ..web_scraper import ContentType, ScrapedContent
from . import base as _base_mod
from .base import SourceAdapter


class RedditAdapter(SourceAdapter):
    """Scrape Reddit pages via their JSON API endpoints."""

    @staticmethod
    def can_handle(url: str) -> bool:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        return domain.endswith('reddit.com')

    def _build_reddit_json_url(self, url: str) -> str:
        """Convert a Reddit page URL to its JSON endpoint."""
        parsed = urlparse(url)
        path = parsed.path or "/"
        if not path.endswith(".json"):
            trimmed = path[:-1] if path.endswith("/") and path != "/" else path
            path = f"{trimmed}.json"
        params = parse_qs(parsed.query, keep_blank_values=True)
        params.setdefault("raw_json", ["1"])
        params.setdefault("limit", ["25"])
        query = urlencode(params, doseq=True)
        scheme = parsed.scheme or "https"
        return urlunparse((scheme, parsed.netloc, path, parsed.params, query, ""))

    def scrape(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        json_url = self._build_reddit_json_url(url)
        headers = {
            "User-Agent": "justscrape/1.0 (reddit-json-adapter)",
            "Accept": "application/json",
        }
        response = _base_mod._safe_get(json_url, headers=headers, timeout=15)
        if response is None:
            return None
        try:
            payload = response.json()
        except Exception:
            return None

        result = ScrapedContent(
            url=url,
            status_code=response.status_code,
            scrape_method="reddit_json",
        )

        links: List[str] = []
        content_lines: List[str] = []
        metadata: Dict = {
            "source": "reddit_json",
            "json_url": json_url,
        }

        def _add_link(value: str):
            if not value:
                return
            if value.startswith("/"):
                links.append(f"https://www.reddit.com{value}")
            elif value.startswith("http"):
                links.append(value)

        try:
            # Thread endpoint usually returns [post_listing, comments_listing]
            if isinstance(payload, list) and payload:
                post_listing = payload[0] if len(payload) > 0 else {}
                comment_listing = payload[1] if len(payload) > 1 else {}

                post_children = post_listing.get("data", {}).get("children", [])
                if post_children:
                    post = post_children[0].get("data", {})
                    subreddit = post.get("subreddit")
                    result.title = post.get("title") or (f"r/{subreddit}" if subreddit else None)
                    metadata.update(
                        {
                            "subreddit": subreddit,
                            "author": post.get("author"),
                            "score": post.get("score"),
                            "num_comments": post.get("num_comments"),
                            "created_utc": post.get("created_utc"),
                        }
                    )
                    _add_link(post.get("permalink"))
                    _add_link(post.get("url_overridden_by_dest") or post.get("url"))
                    if post.get("selftext"):
                        content_lines.append(post["selftext"])

                comments = comment_listing.get("data", {}).get("children", [])
                comment_bodies = []
                for child in comments:
                    data = child.get("data", {})
                    body = data.get("body")
                    if body:
                        comment_bodies.append(body)
                if comment_bodies:
                    content_lines.append("Top comments:")
                    content_lines.extend(comment_bodies[:20])

            # Subreddit/listing endpoint usually returns {"kind":"Listing", ...}
            elif isinstance(payload, dict):
                listing = payload.get("data", {})
                children = listing.get("children", [])
                subreddit = None
                for index, child in enumerate(children[:25], start=1):
                    data = child.get("data", {})
                    post_title = data.get("title", "")
                    subreddit = subreddit or data.get("subreddit")
                    permalink = data.get("permalink")
                    score = data.get("score")
                    num_comments = data.get("num_comments")
                    if post_title:
                        content_lines.append(f"{index}. {post_title}")
                        content_lines.append(f"Score: {score} | Comments: {num_comments}")
                    selftext = data.get("selftext")
                    if selftext:
                        content_lines.append(selftext)
                    _add_link(permalink)
                    _add_link(data.get("url_overridden_by_dest") or data.get("url"))
                    content_lines.append("")

                if subreddit:
                    result.title = f"r/{subreddit} - Reddit"
                    metadata["subreddit"] = subreddit

            if ContentType.METADATA in content_types:
                result.metadata = metadata
                if result.title and "title" not in metadata:
                    result.metadata["title"] = result.title

            if ContentType.LINKS in content_types:
                deduped = list(dict.fromkeys(links))
                result.links = deduped

            if ContentType.CLEAN_TEXT in content_types:
                cleaned_lines = [line.strip() for line in content_lines if line and line.strip()]
                result.content = "\n\n".join(cleaned_lines)
            elif ContentType.FULL_HTML in content_types:
                result.content = json.dumps(payload, indent=2)

            # If adapter produced nothing usable, continue normal fallback path.
            has_useful = bool(result.content) or bool(result.links) or bool(result.title)
            return result if has_useful else None
        except Exception:
            return None
