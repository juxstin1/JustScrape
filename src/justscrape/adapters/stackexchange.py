"""
Stack Exchange adapter — scrapes SO/SE sites via API with StackPrinter fallback.

Supports question pages across the Stack Exchange network.
"""

import json
import re
from typing import Optional, List, Dict
from urllib.parse import urlparse, urlencode

from ..web_scraper import ContentType, ScrapedContent
from . import base as _base_mod
from .base import SourceAdapter


class StackExchangeAdapter(SourceAdapter):
    """Scrape Stack Exchange question pages via API, falling back to StackPrinter."""

    # Domains that belong to the Stack Exchange network
    _NETWORK_DOMAINS = {"superuser.com", "serverfault.com", "askubuntu.com", "mathoverflow.net"}

    @staticmethod
    def can_handle(url: str) -> bool:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        return StackExchangeAdapter._is_stackexchange_domain(domain)

    @staticmethod
    def _is_stackexchange_domain(domain: str) -> bool:
        """Check if domain is part of the Stack Exchange network."""
        return (
            domain == "stackoverflow.com"
            or domain.endswith(".stackexchange.com")
            or domain in StackExchangeAdapter._NETWORK_DOMAINS
        )

    @staticmethod
    def _stackexchange_site_from_domain(domain: str) -> Optional[str]:
        """Map host domain to Stack Exchange API 'site' parameter."""
        if domain == "stackoverflow.com":
            return "stackoverflow"
        if domain in {"superuser.com", "serverfault.com", "askubuntu.com"}:
            return domain.split(".")[0]
        if domain == "mathoverflow.net":
            return "mathoverflow"
        if domain.endswith(".stackexchange.com"):
            return domain[: -len(".stackexchange.com")]
        return None

    @staticmethod
    def _extract_stackexchange_question_id(url: str) -> Optional[str]:
        """Extract question ID from Stack Exchange URL path."""
        parsed = urlparse(url)
        match = re.search(r"/questions/(\d+)", parsed.path or "")
        return match.group(1) if match else None

    @staticmethod
    def _build_stackprinter_url(domain: str, site: str, question_id: str) -> str:
        """Build StackPrinter fallback URL for a Stack Exchange question."""
        params = {
            "service": site,
            "language": "en",
            "width": "640",
            "hideAnswers": "false",
            "showAll": "true",
            "noredirect": "1",
        }
        return f"https://{domain}/questions/{question_id}/stackprinter?" + urlencode(params)

    def scrape(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        return self._scrape_stackexchange_api(url, content_types)

    def _scrape_stackexchange_api(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        """
        Scrape Stack Exchange pages via API (no browser).
        Supports question pages and pulls top answers.
        """
        domain = urlparse(url).netloc.lower().replace("www.", "")
        site = self._stackexchange_site_from_domain(domain)
        question_id = self._extract_stackexchange_question_id(url)
        if not site or not question_id:
            return None

        api_base = "https://api.stackexchange.com/2.3"
        headers = {
            "User-Agent": "justscrape/1.0 (stackexchange-api-adapter)",
            "Accept": "application/json",
        }

        question_url = (
            f"{api_base}/questions/{question_id}"
            f"?order=desc&sort=activity&site={site}&filter=withbody"
        )
        answers_url = (
            f"{api_base}/questions/{question_id}/answers"
            f"?order=desc&sort=votes&site={site}&filter=withbody&pagesize=5"
        )

        q_resp = _base_mod._safe_get(question_url, headers=headers, timeout=15)
        if q_resp is None:
            return self._scrape_stackexchange_stackprinter(url, content_types, domain, site, question_id)
        try:
            q_payload = q_resp.json()
            q_items = q_payload.get("items", [])
            if not q_items:
                return self._scrape_stackexchange_stackprinter(url, content_types, domain, site, question_id)
            q_item = q_items[0]
        except Exception:
            return self._scrape_stackexchange_stackprinter(url, content_types, domain, site, question_id)

        answer_items = []
        a_resp = _base_mod._safe_get(answers_url, headers=headers, timeout=15)
        if a_resp is not None:
            try:
                answer_items = a_resp.json().get("items", [])
            except Exception:
                answer_items = []

        result = ScrapedContent(
            url=url,
            status_code=200,
            scrape_method="stackexchange_api",
        )

        metadata: Dict = {
            "source": "stackexchange_api",
            "site": site,
            "question_id": question_id,
            "question_score": q_item.get("score"),
            "answer_count": q_item.get("answer_count"),
            "is_answered": q_item.get("is_answered"),
            "tags": q_item.get("tags", []),
            "api_question_url": question_url,
            "api_answers_url": answers_url,
        }

        result.title = q_item.get("title")
        question_link = q_item.get("link")
        links: List[str] = []
        if question_link:
            links.append(question_link)

        content_lines: List[str] = []
        try:
            from bs4 import BeautifulSoup

            q_body_html = q_item.get("body", "")
            q_body_text = ""
            if q_body_html:
                q_body_text = BeautifulSoup(q_body_html, "html.parser").get_text("\n", strip=True)

            if result.title:
                content_lines.append(f"Question: {result.title}")
            if q_body_text:
                content_lines.append(q_body_text)

            if answer_items:
                content_lines.append("Top answers:")
                for idx, answer in enumerate(answer_items[:5], start=1):
                    a_body_html = answer.get("body", "")
                    a_body_text = ""
                    if a_body_html:
                        a_body_text = BeautifulSoup(a_body_html, "html.parser").get_text("\n", strip=True)
                    answer_score = answer.get("score")
                    is_accepted = answer.get("is_accepted")
                    if a_body_text:
                        content_lines.append(
                            f"Answer {idx} (score={answer_score}, accepted={bool(is_accepted)}):"
                        )
                        content_lines.append(a_body_text)
                    if answer.get("share_link"):
                        links.append(answer["share_link"])
        except Exception:
            return self._scrape_stackexchange_stackprinter(url, content_types, domain, site, question_id)

        if ContentType.METADATA in content_types:
            result.metadata = metadata
            if result.title and "title" not in result.metadata:
                result.metadata["title"] = result.title

        if ContentType.LINKS in content_types:
            result.links = list(dict.fromkeys(links))

        if ContentType.CLEAN_TEXT in content_types:
            cleaned_lines = [line.strip() for line in content_lines if line and line.strip()]
            result.content = "\n\n".join(cleaned_lines)
        elif ContentType.FULL_HTML in content_types:
            result.content = json.dumps(
                {"question": q_item, "answers": answer_items},
                indent=2,
            )

        has_useful = bool(result.content) or bool(result.links) or bool(result.title)
        if has_useful:
            return result
        return self._scrape_stackexchange_stackprinter(url, content_types, domain, site, question_id)

    def _scrape_stackexchange_stackprinter(
        self,
        url: str,
        content_types: List[ContentType],
        domain: str,
        site: str,
        question_id: str,
    ) -> Optional[ScrapedContent]:
        """
        Fallback for Stack Exchange pages via StackPrinter HTML export.
        Used when API fails or returns empty.
        """
        from bs4 import BeautifulSoup

        stackprinter_url = self._build_stackprinter_url(domain, site, question_id)
        headers = {
            "User-Agent": "justscrape/1.0 (stackexchange-stackprinter-fallback)",
            "Accept": "text/html,application/xhtml+xml",
        }

        response = _base_mod._safe_get(stackprinter_url, headers=headers, timeout=20)
        if response is None or not response.text:
            return None

        try:
            soup = BeautifulSoup(response.text, "html.parser")

            for element in soup(["script", "style", "noscript"]):
                element.decompose()

            title_tag = soup.select_one("h1 a") or soup.select_one("h1")
            title_candidate = (
                title_tag.get_text(strip=True)
                if title_tag
                else (soup.title.get_text(strip=True) if soup.title else None)
            )
            if title_candidate and title_candidate.lower() in {"question", "answer"} and soup.title:
                title_text = soup.title.get_text(strip=True)
            else:
                title_text = title_candidate
            links = []
            for anchor in soup.find_all("a", href=True):
                href = anchor.get("href")
                if href and href.startswith("http"):
                    links.append(href)

            content_lines = []

            question_body = (
                soup.select_one("#question .js-post-body")
                or soup.select_one("#question .s-prose")
                or soup.select_one(".question .js-post-body")
                or soup.select_one(".question .s-prose")
            )
            answer_bodies = soup.select(".answer .js-post-body")
            if not answer_bodies:
                answer_bodies = soup.select(".answer .s-prose")

            if question_body:
                q_text = question_body.get_text("\n", strip=True)
                if title_text:
                    content_lines.append(f"Question: {title_text}")
                if q_text:
                    content_lines.append(q_text)

            for idx, answer_body in enumerate(answer_bodies[:5], start=1):
                a_text = answer_body.get_text("\n", strip=True)
                if a_text:
                    content_lines.append(f"Answer {idx}:")
                    content_lines.append(a_text)

            if content_lines:
                content_text = "\n\n".join(line.strip() for line in content_lines if line and line.strip())
            else:
                full_text = soup.get_text("\n", strip=True)
                lines = [line.strip() for line in full_text.split("\n") if line and line.strip()]
                cleaned_lines = []
                prev = None
                for line in lines:
                    if line != prev:
                        cleaned_lines.append(line)
                        prev = line
                content_text = "\n\n".join(cleaned_lines)
            if len(content_text) < 80:
                return None

            result = ScrapedContent(
                url=url,
                title=title_text,
                status_code=response.status_code,
                scrape_method="stackexchange_stackprinter",
            )

            if ContentType.METADATA in content_types:
                result.metadata = {
                    "source": "stackexchange_stackprinter",
                    "site": site,
                    "question_id": question_id,
                    "stackprinter_url": stackprinter_url,
                }
                if result.title:
                    result.metadata["title"] = result.title

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
