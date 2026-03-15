"""
Smart Web Scraper - Unified interface that auto-detects best scraping method
Combines static and JavaScript scrapers with intelligent fallback
Integrates with sitemap registry for efficient URL discovery

Features:
- Multi-signal JS fallback detection (not just content length)
- Per-domain scraping intelligence
- Integrates with sitemap registry for URL discovery
"""

from typing import Optional, List, Dict, Union
from dataclasses import dataclass
from web_scraper import WebScraper, ContentType, ScrapedContent, quick_scrape
from sitemap_registry import SitemapRegistry
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from url_validator import validate_url as _validate_url
import json
import re
import requests

# NOTE: js_scraper is imported lazily inside methods that need it

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
# This allows the module to load without Playwright installed


class SmartScraper:
    """
    Intelligent scraper that chooses the best method automatically.
    Uses multi-signal detection for JS fallback instead of just content length.
    """

    # Domains known to be JS-heavy (always use browser)
    JS_HEAVY_DOMAINS = {
        'twitter.com', 'x.com', 'reddit.com', 'youtube.com',
        'instagram.com', 'facebook.com', 'linkedin.com',
        'medium.com', 'substack.com', 'discord.com'
    }

    # Patterns that indicate JS is needed
    JS_NEEDED_PATTERNS = re.compile(
        r'enable javascript|requires javascript|please turn on javascript|'
        r'javascript is required|javascript must be enabled|'
        r'this page requires javascript|browser does not support javascript',
        re.IGNORECASE
    )

    def __init__(
        self,
        min_content_length: int = 200,
        force_js: bool = False
    ):
        self.min_content_length = min_content_length
        self.force_js = force_js
        self.static_scraper = WebScraper()

    def _is_js_heavy_site(self, url: str) -> bool:
        """Check if URL is likely to need JavaScript rendering"""
        domain = urlparse(url).netloc.lower().replace('www.', '')
        return any(js_domain in domain for js_domain in self.JS_HEAVY_DOMAINS)

    def _try_source_adapter(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        """
        Try source-specific non-browser adapters before static/JS scraping.
        Returns ScrapedContent on adapter success, else None to continue fallback.
        """
        # SSRF protection: validate URL before any adapter makes outbound requests
        url_ok, _ = _validate_url(url)
        if not url_ok:
            return None

        domain = urlparse(url).netloc.lower().replace('www.', '')
        if domain.endswith('reddit.com'):
            return self._scrape_reddit_json(url, content_types)
        if domain.endswith('dev.to'):
            return self._scrape_devto_api(url, content_types)
        if domain == 'github.com':
            return self._scrape_github_discussions_html(url, content_types)
        if self._is_stackexchange_domain(domain):
            return self._scrape_stackexchange_api(url, content_types)
        return None

    def _is_stackexchange_domain(self, domain: str) -> bool:
        """Check if domain is part of the Stack Exchange network."""
        return (
            domain == "stackoverflow.com"
            or domain.endswith(".stackexchange.com")
            or domain in {"superuser.com", "serverfault.com", "askubuntu.com", "mathoverflow.net"}
        )

    def _stackexchange_site_from_domain(self, domain: str) -> Optional[str]:
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

    def _extract_stackexchange_question_id(self, url: str) -> Optional[str]:
        """Extract question ID from Stack Exchange URL path."""
        parsed = urlparse(url)
        match = re.search(r"/questions/(\d+)", parsed.path or "")
        return match.group(1) if match else None

    def _extract_github_discussion_info(self, url: str) -> Optional[Dict[str, str]]:
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

    def _build_stackprinter_url(self, domain: str, site: str, question_id: str) -> str:
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

    def _scrape_reddit_json(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        """
        Scrape Reddit via JSON endpoints (works without browser automation).
        Supports subreddit listings and thread pages.
        """
        json_url = self._build_reddit_json_url(url)
        headers = {
            "User-Agent": "justscrape/1.0 (reddit-json-adapter)",
            "Accept": "application/json",
        }
        response = _safe_get(json_url, headers=headers, timeout=15)
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

    def _scrape_devto_api(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        """
        Scrape dev.to articles via public API without browser automation.
        """
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
            resp = _safe_get(api_url, headers=headers, timeout=15)
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

    def _scrape_github_discussions_html(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        """
        Scrape GitHub Discussions pages from HTML without browser automation.
        Supports /{owner}/{repo}/discussions/{number}.
        """
        info = self._extract_github_discussion_info(url)
        if not info:
            return None

        headers = {
            "User-Agent": "justscrape/1.0 (github-discussions-adapter)",
            "Accept": "text/html,application/xhtml+xml",
        }
        response = _safe_get(url, headers=headers, timeout=20)
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

        q_resp = _safe_get(question_url, headers=headers, timeout=15)
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
        a_resp = _safe_get(answers_url, headers=headers, timeout=15)
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

        response = _safe_get(stackprinter_url, headers=headers, timeout=20)
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

    def _needs_javascript(self, html: str, content: str, url: str) -> bool:
        """
        Multi-signal decision for whether to fall back to JS rendering.
        Smarter than the old simple content-length check.
        """
        content_length = len(content) if content else 0

        # Known JS-heavy domains
        if self._is_js_heavy_site(url):
            return True

        # Short content + explicit JS requirement message in HTML
        if content_length < 500 and html and self.JS_NEEDED_PATTERNS.search(html):
            return True

        # Very short content + page has noscript tag or high script density
        if content_length < self.min_content_length and html:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                has_noscript = bool(soup.find('noscript'))
                script_count = len(soup.find_all('script'))

                if has_noscript or script_count > 5:
                    return True
            except Exception:
                pass

        # Fallback: just too short
        if content_length < self.min_content_length:
            return True

        return False

    def scrape(
        self,
        url: str,
        content_types: List[ContentType] = None,
        force_method: Optional[str] = None
    ) -> ScrapedContent:
        """
        Intelligently scrape URL using best method.

        Uses multi-signal detection to decide between static and JS scraping.
        """
        if content_types is None:
            content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]

        # SSRF protection: reject unsafe URLs before any network request
        url_ok, url_reason = _validate_url(url)
        if not url_ok:
            return ScrapedContent(url=url, status_code=0)

        # Try non-browser adapters first for known hard targets.
        adapter_result = self._try_source_adapter(url, content_types)
        if adapter_result is not None:
            return adapter_result

        # Determine scraping method
        use_js = (
            self.force_js or
            force_method == 'js' or
            (force_method != 'static' and self._is_js_heavy_site(url))
        )

        if not use_js:
            # Fetch raw HTML once (used for both content extraction and JS detection)
            raw_html = None
            try:
                raw_html, _ = self.static_scraper.fetch(url)
            except Exception:
                pass

            # Extract content from the fetched HTML
            if raw_html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(raw_html, 'html.parser')
                result = ScrapedContent(url=url, status_code=200, scrape_method='static')
                for ct in content_types:
                    if ct == ContentType.CLEAN_TEXT:
                        result.content = self.static_scraper.extract_clean_text(raw_html, soup)
                    elif ct == ContentType.METADATA:
                        result.metadata = self.static_scraper.extract_metadata(soup)
                        result.title = result.metadata.get('title')
                    elif ct == ContentType.LINKS:
                        result.links = self.static_scraper.extract_links(soup, url)
                    elif ct == ContentType.IMAGES:
                        result.images = self.static_scraper.extract_images(soup, url)
            else:
                result = ScrapedContent(url=url, status_code=0)

            # Multi-signal check: do we need JS?
            if not self._needs_javascript(raw_html, result.content, url):
                return result

            use_js = True

        if use_js:
            from js_scraper import JavaScriptScraper
            with JavaScriptScraper() as js_scraper:
                return js_scraper.scrape(url, content_types)

        # Unreachable, but safe fallback to prevent UnboundLocalError
        return ScrapedContent(url=url)
    
    def scrape_to_markdown(self, url: str) -> str:
        """
        Scrape and return clean markdown-formatted text
        Perfect for feeding to LLMs or saving as docs
        """
        result = self.scrape(url, [ContentType.CLEAN_TEXT, ContentType.METADATA])
        
        output = []
        
        # Add title
        if result.title:
            output.append(f"# {result.title}\n")
        
        # Add metadata
        if result.metadata:
            if result.metadata.get('description'):
                output.append(f"> {result.metadata['description']}\n")
            if result.metadata.get('author'):
                output.append(f"**Author:** {result.metadata['author']}")
            if result.metadata.get('published_date'):
                output.append(f"**Published:** {result.metadata['published_date']}")
            if result.metadata.get('author') or result.metadata.get('published_date'):
                output.append("")
        
        # Add main content
        if result.content:
            output.append(result.content)
        
        return '\n'.join(output)
    
    def scrape_to_dict(
        self,
        url: str,
        include_links: bool = False,
        force_method: Optional[str] = None,
    ) -> Dict:
        """Scrape and return as simple dictionary"""
        content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]
        if include_links:
            content_types.append(ContentType.LINKS)
        
        result = self.scrape(url, content_types, force_method=force_method)
        
        return {
            'url': result.url,
            'title': result.title,
            'content': result.content,
            'metadata': result.metadata,
            'links': result.links if include_links else None,
            'scrape_method': result.scrape_method,
            'status_code': result.status_code,
        }


# Utility functions
def scrape_article(url: str) -> str:
    """
    Scrape an article and return clean, readable text
    Automatically handles both static and JS sites
    """
    scraper = SmartScraper()
    return scraper.scrape_to_markdown(url)


def scrape_multiple_articles(urls: List[str]) -> List[Dict]:
    """
    Scrape multiple URLs and return as list of dictionaries
    """
    scraper = SmartScraper()
    results = []
    
    for url in urls:
        print(f"Scraping: {url}")
        result_dict = scraper.scrape_to_dict(url)
        results.append(result_dict)
    
    return results


def extract_article_for_llm(url: str) -> str:
    """
    Extract article optimized for LLM consumption
    Returns clean markdown with minimal metadata
    """
    scraper = SmartScraper()
    result = scraper.scrape(url, [ContentType.CLEAN_TEXT, ContentType.METADATA])
    
    # Simple format for LLM
    parts = []
    if result.title:
        parts.append(f"Title: {result.title}")
    if result.content:
        parts.append(f"\nContent:\n{result.content}")
    
    return '\n'.join(parts)


def scrape_and_summarize(url: str, max_length: int = 5000) -> str:
    """
    Scrape article and return truncated version if too long
    Useful for quick previews
    """
    content = scrape_article(url)
    
    if len(content) > max_length:
        return content[:max_length] + f"\n\n[Content truncated - {len(content)} total chars]"
    
    return content


def batch_scrape_to_files(urls: List[str], output_dir: str = "./scraped"):
    """
    Scrape multiple URLs and save each to a separate markdown file
    """
    import os
    from pathlib import Path
    from urllib.parse import urlparse
    
    Path(output_dir).mkdir(exist_ok=True)
    scraper = SmartScraper()
    
    for i, url in enumerate(urls):
        print(f"Scraping [{i+1}/{len(urls)}]: {url}")
        
        try:
            content = scraper.scrape_to_markdown(url)
            
            # Generate filename from URL
            parsed = urlparse(url)
            filename = parsed.netloc.replace('www.', '') + '_' + str(i) + '.md'
            filename = re.sub(r'[^\w\s-]', '', filename)
            
            filepath = os.path.join(output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"  ✓ Saved to {filepath}")
            
        except Exception as e:
            print(f"  ✗ Error: {e}")


# Advanced utilities
def scrape_with_extraction(url: str, extract_pattern: str = None) -> List[str]:
    """
    Scrape and extract specific patterns (emails, phone numbers, etc.)
    
    Args:
        url: URL to scrape
        extract_pattern: Regex pattern to extract, or use preset:
                        'emails', 'phones', 'urls'
    """
    scraper = SmartScraper()
    result = scraper.scrape(url, [ContentType.CLEAN_TEXT])
    
    if not result.content:
        return []
    
    # Preset patterns
    patterns = {
        'emails': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phones': r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        'urls': r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
    }
    
    pattern = patterns.get(extract_pattern, extract_pattern)
    if not pattern:
        return []
    
    matches = re.findall(pattern, result.content, re.MULTILINE)
    return list(set(matches))  # Remove duplicates


def compare_scraping_methods(url: str) -> Dict:
    """
    Compare static vs JS scraping for a URL
    Useful for debugging which method works better
    """
    results = {
        'url': url,
        'static': None,
        'javascript': None,
        'recommendation': None
    }
    
    # Try static
    static_scraper = WebScraper()
    static_result = static_scraper.scrape(url, [ContentType.CLEAN_TEXT])
    results['static'] = {
        'success': bool(static_result.content),
        'length': len(static_result.content) if static_result.content else 0,
        'preview': static_result.content[:200] if static_result.content else None
    }
    
    # Try JS
    try:
        from js_scraper import JavaScriptScraper
        with JavaScriptScraper() as js_scraper:
            js_result = js_scraper.scrape(url, [ContentType.CLEAN_TEXT])
            results['javascript'] = {
                'success': bool(js_result.content),
                'length': len(js_result.content) if js_result.content else 0,
                'preview': js_result.content[:200] if js_result.content else None
            }
    except Exception as e:
        results['javascript'] = {
            'success': False,
            'error': str(e)
        }
    
    # Recommendation
    if results['static']['success'] and results['static']['length'] > 200:
        results['recommendation'] = 'static'
    else:
        results['recommendation'] = 'javascript'
    
    return results


def scrape_from_sitemap(
    domain: str,
    limit: int = 10,
    unscraped_only: bool = True,
    auto_add: bool = True
) -> List[Dict]:
    """
    Scrape multiple URLs from a domain's sitemap

    Args:
        domain: Domain to scrape from (e.g., "example.com")
        limit: Maximum number of URLs to scrape
        unscraped_only: Only scrape URLs not previously scraped
        auto_add: Automatically add domain to registry if not found

    Returns:
        List of dictionaries with scraped content
    """
    registry = SitemapRegistry()

    # Check if domain has sitemap
    if not registry.has_sitemap(domain):
        if auto_add:
            print(f"Domain {domain} not in registry, fetching sitemap...")
            success = registry.add_domain(domain)
            if not success:
                print(f"Failed to fetch sitemap for {domain}")
                return []
        else:
            print(f"Domain {domain} not in registry")
            return []

    # Check if sitemap is stale
    if registry.is_stale(domain):
        print(f"Sitemap for {domain} is stale, refreshing...")
        registry.refresh_domain(domain)

    # Get URLs to scrape
    urls = registry.get_urls(domain, limit=limit, unscraped_only=unscraped_only)

    if not urls:
        print(f"No URLs found for {domain}")
        return []

    print(f"Scraping {len(urls)} URLs from {domain}...")

    # Scrape each URL
    scraper = SmartScraper()
    results = []

    for i, url in enumerate(urls):
        print(f"  [{i+1}/{len(urls)}] {url}")

        try:
            result = scraper.scrape_to_dict(url)
            results.append(result)

            # Mark as scraped in registry
            registry.mark_scraped(url)

        except Exception as e:
            print(f"    ✗ Error: {e}")

    print(f"\n✓ Scraped {len(results)}/{len(urls)} URLs")
    return results


def get_sitemap_urls(domain: str, limit: int = 100) -> List[str]:
    """
    Get URLs from a domain's sitemap without scraping

    Args:
        domain: Domain to get URLs from
        limit: Maximum URLs to return

    Returns:
        List of URLs
    """
    registry = SitemapRegistry()

    if not registry.has_sitemap(domain):
        print(f"Fetching sitemap for {domain}...")
        registry.add_domain(domain)

    return registry.get_urls(domain, limit=limit)


if __name__ == '__main__':
    # Example usage
    url = "https://example.com"

    print("=== Smart Scraper Examples ===\n")

    # Simple article scraping
    print("1. Scraping article...")
    content = scrape_article(url)
    print(f"Content length: {len(content)} chars\n")

    # Extract specific data
    print("2. Extracting emails...")
    emails = scrape_with_extraction(url, 'emails')
    print(f"Found {len(emails)} emails\n")

    # Compare methods
    print("3. Comparing scraping methods...")
    comparison = compare_scraping_methods(url)
    print(f"Recommendation: {comparison['recommendation']}\n")

    # Sitemap-based scraping
    print("4. Scraping from sitemap...")
    results = scrape_from_sitemap("example.com", limit=5)
    print(f"Scraped {len(results)} articles from sitemap\n")
