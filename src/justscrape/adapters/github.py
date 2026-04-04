"""
GitHub Discussions adapter — scrapes discussion pages from HTML.

Supports /{owner}/{repo}/discussions/{number} URLs.
"""

import re
from typing import Optional, List, Dict
from urllib.parse import urlparse

from ..web_scraper import ContentType, ScrapedContent
from . import base as _base_mod
from .base import SourceAdapter


class GitHubDiscussionsAdapter(SourceAdapter):
    """Scrape GitHub Discussions pages from HTML without browser automation."""

    @staticmethod
    def can_handle(url: str) -> bool:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        if domain != 'github.com':
            return False
        # Only handle discussion URLs
        return GitHubDiscussionsAdapter._extract_discussion_info(url) is not None

    @staticmethod
    def _extract_discussion_info(url: str) -> Optional[Dict[str, str]]:
        """Extract owner/repo/discussion number from GitHub discussion URL."""
        parsed = urlparse(url)
        path = (parsed.path or "").strip("/")
        parts = path.split("/")
        if len(parts) < 4:
            return None
        if parts[2] != "discussions":
            return None
        if not parts[3].isdigit():
            return None
        return {
            "owner": parts[0],
            "repo": parts[1],
            "number": parts[3],
        }

    def scrape(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        info = self._extract_discussion_info(url)
        if not info:
            return None

        headers = {
            "User-Agent": "justscrape/1.0 (github-discussions-adapter)",
            "Accept": "text/html,application/xhtml+xml",
        }
        response = _base_mod._safe_get(url, headers=headers, timeout=20)
        if response is None or not response.text:
            return None

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, "html.parser")
            for node in soup(["script", "style", "noscript"]):
                node.decompose()

            title = None
            og_title = soup.select_one("meta[property='og:title']")
            if og_title and og_title.get("content"):
                title = og_title.get("content").strip()
            if not title:
                title_node = (
                    soup.select_one("#discussion_bucket h1")
                    or soup.select_one("main h1")
                    or soup.select_one(".gh-header-title")
                    or soup.select_one("h1")
                )
                title = title_node.get_text(" ", strip=True) if title_node else None
            if title:
                title = re.sub(r"\s+#\d+$", "", title).strip()
                title = re.split(r"\s+[·•]\s+", title)[0].strip()
                if title.startswith("Search code, repositories"):
                    title = None
            if not title and soup.title:
                title = soup.title.get_text(" ", strip=True).split(" · ")[0].strip()

            body_nodes = soup.select(".js-comment-body")
            if not body_nodes:
                body_nodes = soup.select(".comment-body")
            if not body_nodes:
                body_nodes = soup.select(".markdown-body")

            content_lines: List[str] = []
            if title:
                content_lines.append(f"Discussion: {title}")

            for idx, body in enumerate(body_nodes[:6], start=1):
                text = body.get_text("\n", strip=True)
                if not text:
                    continue
                if idx == 1:
                    content_lines.append("Topic:")
                else:
                    content_lines.append(f"Reply {idx - 1}:")
                content_lines.append(text)

            content_text = "\n\n".join(line.strip() for line in content_lines if line and line.strip())
            if len(content_text) < 120:
                return None

            links = []
            for anchor in soup.find_all("a", href=True):
                href = anchor.get("href")
                if not href:
                    continue
                if href.startswith("http"):
                    links.append(href)
                elif href.startswith("/"):
                    links.append(f"https://github.com{href}")

            result = ScrapedContent(
                url=url,
                title=title,
                status_code=response.status_code,
                scrape_method="github_discussions_html",
            )
            if ContentType.METADATA in content_types:
                result.metadata = {
                    "source": "github_discussions_html",
                    "owner": info["owner"],
                    "repo": info["repo"],
                    "discussion_number": info["number"],
                    "title": title,
                }
            if ContentType.LINKS in content_types:
                result.links = list(dict.fromkeys(links))
            if ContentType.CLEAN_TEXT in content_types:
                result.content = content_text
            elif ContentType.FULL_HTML in content_types:
                result.content = response.text

            has_useful = bool(result.content) or bool(result.links) or bool(result.title)
            return result if has_useful else None
        except Exception:
            return None
