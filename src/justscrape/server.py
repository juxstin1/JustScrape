#!/usr/bin/env python3
"""
JustScrape MCP Server - Web Search & Scraping for AI

This MCP server exposes web search and scraping tools for AI models.
Search uses SearXNG (self-hosted meta-search) with automatic fallback
to DuckDuckGo and public SearXNG instances.

Tools exposed:
- web_search: Multi-engine search with fallback chain (with operators)
- scrape_url: Clean content extraction from any URL
- search_and_scrape: Search + fetch top results in one call (parallel)
- extract_urls: Extract links from a page
- get_stats: Cache and browser pool status

Usage:
    justscrape              # via entry point
    python -m justscrape    # via module

Or add to any MCP-compatible AI client:
    {
        "mcpServers": {
            "justscrape": {
                "command": "uvx",
                "args": ["justscrape"]
            }
        }
    }
"""

import asyncio
import json
import threading
import time
import atexit
from typing import Any, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
)

# Import our modules
from .web_search import (
    WebSearch,
    search_full,
    get_cache_stats,
    should_scrape,
    relevance_score,
)
from .smart_scraper import SmartScraper, scrape_article
from .url_validator import validate_url

# Phase 2 quality pipeline components
from .query_analyzer import QueryAnalyzer, AnalyzedQuery
from .result_reranker import ResultReranker, RankedResult
from .snippet_extractor import SnippetExtractor, ExtractedSnippet
from .quality_scorer import QualityScorer, ScoredResult, deduplicate_results


class LazyBrowserPool:
    """
    Lazy browser pool for Playwright - only initializes when first needed.
    Keeps browser warm for subsequent requests.
    Thread-safe singleton pattern.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._playwright = None
        self._browser = None
        self._init_lock = threading.Lock()
        self._last_used = 0
        self._initialized = True

        # Register cleanup on exit
        atexit.register(self.shutdown)

    def _ensure_browser(self):
        """Lazily initialize browser on first use"""
        if self._browser is not None:
            self._last_used = time.time()
            return

        with self._init_lock:
            if self._browser is not None:
                return

            try:
                from playwright.sync_api import sync_playwright

                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
                self._last_used = time.time()
            except Exception as e:
                self._browser = None
                raise RuntimeError(f"Failed to initialize browser: {e}")

    def get_browser(self):
        """Get the browser instance, initializing if needed"""
        self._ensure_browser()
        return self._browser

    def is_initialized(self) -> bool:
        """Check if browser is initialized"""
        return self._browser is not None

    def get_stats(self) -> dict:
        """Get pool statistics"""
        return {
            "initialized": self.is_initialized(),
            "last_used": self._last_used,
            "idle_seconds": int(time.time() - self._last_used)
            if self._last_used
            else None,
        }

    def shutdown(self):
        """Shutdown browser and playwright"""
        with self._init_lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None

            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None


# Global browser pool (lazy singleton)
_browser_pool = LazyBrowserPool()

# Phase 2 quality pipeline singletons
_query_analyzer = QueryAnalyzer()
_result_reranker = ResultReranker()
_snippet_extractor = SnippetExtractor()
_quality_scorer = QualityScorer()

# Global concurrency limit for outbound scrape requests (prevents DDoS amplification)
MAX_CONCURRENT_SCRAPES = 5
_scrape_semaphore = None  # Initialized lazily in async context


def _get_scrape_semaphore():
    global _scrape_semaphore
    if _scrape_semaphore is None:
        _scrape_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCRAPES)
    return _scrape_semaphore


class PooledSmartScraper(SmartScraper):
    """
    SmartScraper that uses the lazy browser pool for JS rendering.
    Avoids cold starts on every JS scrape.
    """

    def scrape(self, url, content_types=None, force_method=None):
        """Override to use pooled browser for JS scraping"""
        from .web_scraper import ContentType, ScrapedContent

        if content_types is None:
            content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]

        # SSRF protection: reject unsafe URLs before any network request
        url_ok, _ = validate_url(url)
        if not url_ok:
            return ScrapedContent(url=url, status_code=0)

        # Try non-browser adapters first (e.g., reddit JSON).
        adapter_result = self._try_source_adapter(url, content_types)
        if adapter_result is not None:
            return adapter_result

        # Determine if we need JS
        use_js = (
            self.force_js
            or force_method == "js"
            or (force_method != "static" and self._is_js_heavy_site(url))
        )

        if not use_js:
            # Try static first
            result = self.static_scraper.scrape(url, content_types)
            content_ok = (
                result.content and len(result.content) >= self.min_content_length
            )

            if content_ok:
                return result

            use_js = True

        # Use pooled browser for JS — fall back to static if Playwright unavailable
        if use_js:
            try:
                return self._scrape_with_pooled_browser(url, content_types)
            except Exception:
                # Playwright not installed or browser failed — try static as last resort
                result = self.static_scraper.scrape(url, content_types)
                if result.content:
                    return result
                return ScrapedContent(url=url)

        # Unreachable, but safe fallback
        return ScrapedContent(url=url)

    def _scrape_with_pooled_browser(self, url, content_types):
        """Scrape using pooled browser"""
        from .web_scraper import ScrapedContent, ContentType
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse

        # Block non-HTTP schemes before Playwright navigation (prevents file:// access)
        scheme = urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(
                f"URL scheme '{scheme}' is not allowed for browser scraping"
            )

        browser = _browser_pool.get_browser()
        # Use isolated browser context per scrape to prevent cookie/storage leakage
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            java_script_enabled=True,
        )
        page = context.new_page()

        try:
            # Block tracking/ads
            def route_handler(route):
                blocked_patterns = [
                    "google-analytics",
                    "googletagmanager",
                    "doubleclick",
                    "facebook.com/tr",
                    "facebook.net",
                    "twitter.com/i/adsct",
                ]
                if any(p in route.request.url for p in blocked_patterns):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", route_handler)

            # Navigate
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)  # Let JS settle

            html = page.content()
            soup = BeautifulSoup(html, "lxml")

            # Extract content
            title = soup.title.string if soup.title else None

            # Remove junk
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()

            # Find main content
            main = soup.find("article") or soup.find("main") or soup.find("body")
            content = main.get_text(separator="\n", strip=True) if main else ""

            # Clean up
            lines = [line.strip() for line in content.split("\n") if line.strip()]
            content = "\n".join(lines)

            # Extract metadata
            metadata = {}
            if ContentType.METADATA in content_types:
                meta_desc = soup.find("meta", attrs={"name": "description"})
                if meta_desc:
                    metadata["description"] = meta_desc.get("content", "")

            # Extract links
            links = None
            if ContentType.LINKS in content_types:
                links = [a.get("href") for a in soup.find_all("a", href=True)]
                links = [l for l in links if l.startswith("http")]

            return ScrapedContent(
                url=url,
                title=title,
                content=content,
                metadata=metadata,
                links=links,
                images=None,
                structured_data=None,
                scrape_method="javascript_pooled",
            )

        finally:
            page.close()
            context.close()


# Initialize MCP server
server = Server("justscrape")


# Tool definitions
@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools"""
    return [
        Tool(
            name="web_search",
            description="""Search the web using multiple engines (free, no API key needed).
Uses SearXNG if available, falls back to DuckDuckGo automatically.
Returns SERP-style results with titles, URLs, and snippets.
Results are cached in memory (5 min) and on disk (24 hr).
Supports search operators: site restriction, filetype, date range, domain exclusion.

Returns: JSON with query, results array, cached flag, and metadata.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "num_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10, max: 25)",
                        "default": 10,
                    },
                    "site": {
                        "type": "string",
                        "description": "Restrict results to a specific site (e.g., 'docs.python.org')",
                    },
                    "filetype": {
                        "type": "string",
                        "description": "Restrict to file type (e.g., 'pdf')",
                    },
                    "date_range": {
                        "type": "string",
                        "description": "Time filter: 'day', 'week', 'month', or 'year'",
                        "enum": ["day", "week", "month", "year"],
                    },
                    "exclude_sites": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of domains to exclude from results",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="scrape_url",
            description="""Scrape a URL and extract clean, readable content.
Automatically handles both static and JavaScript-heavy sites.
Uses a warm browser pool for JS sites (no cold start penalty).

Features:
- Auto-detects JS-heavy sites (Twitter, Reddit, etc.)
- Removes ads, navigation, footers, and other junk
- Extracts main article content
- Returns markdown-formatted text

Returns: JSON with url, title, content, and metadata.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to scrape"},
                    "include_links": {
                        "type": "boolean",
                        "description": "Include extracted links from the page",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="search_and_scrape",
            description="""Search the web AND scrape the top results in one call.
Combines web_search + scrape_url for efficient research.

Flow:
1. Search the web (SearXNG or DuckDuckGo fallback)
2. Pre-filter: skip known-blocked domains and non-content URLs
3. HEAD pre-check: verify pages are reachable HTML before scraping
4. Scrape results in parallel (not sequentially)
5. Score each result for relevance to the query
6. Return results sorted by relevance score

Perfect for research tasks where you need actual content, not just links.

Returns: JSON with search results, each including full scraped content and relevance_score.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to search and scrape (default: 3, max: 5)",
                        "default": 3,
                    },
                    "max_content_length": {
                        "type": "integer",
                        "description": "Max characters per scraped page (default: 5000)",
                        "default": 5000,
                    },
                    "site": {
                        "type": "string",
                        "description": "Restrict search to a specific site",
                    },
                    "date_range": {
                        "type": "string",
                        "description": "Time filter: 'day', 'week', 'month', or 'year'",
                        "enum": ["day", "week", "month", "year"],
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="extract_urls",
            description="""Extract all URLs/links from a webpage.
Useful for discovering related pages, finding resources, or crawling.

Returns: JSON with source URL and list of discovered URLs.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to extract links from",
                    },
                    "filter_external": {
                        "type": "boolean",
                        "description": "Only return external links (different domain)",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="get_stats",
            description="""Get MCP server statistics including cache and browser pool status.
Useful for debugging and monitoring.

Returns: JSON with cache stats and browser pool status.""",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Handle tool calls"""

    try:
        if name == "web_search":
            return await handle_web_search(arguments)
        elif name == "scrape_url":
            return await handle_scrape_url(arguments)
        elif name == "search_and_scrape":
            return await handle_search_and_scrape(arguments)
        elif name == "extract_urls":
            return await handle_extract_urls(arguments)
        elif name == "get_stats":
            return await handle_get_stats(arguments)
        else:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"success": False, "error": f"Unknown tool: {name}"},
                            indent=2,
                        ),
                    )
                ],
                isError=True,
            )

    except Exception as e:
        import sys

        # Log full error to stderr for debugging; return sanitized message to client
        print(f"[justscrape] Tool '{name}' error: {e}", file=sys.stderr)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": False,
                            "error": "Internal server error. Check server logs for details.",
                            "tool": name,
                        },
                        indent=2,
                    ),
                )
            ],
            isError=True,
        )


async def handle_web_search(arguments: dict) -> CallToolResult:
    """Handle web_search tool with operator support"""
    query = arguments.get("query", "")
    if not isinstance(query, str):
        query = str(query) if query is not None else ""

    try:
        num_results = int(arguments.get("num_results", 10))
    except (TypeError, ValueError):
        num_results = 10
    num_results = max(1, min(num_results, 25))

    site = arguments.get("site")
    if site is not None:
        site = str(site)
    filetype = arguments.get("filetype")
    if filetype is not None:
        filetype = str(filetype)
    date_range = arguments.get("date_range")
    if date_range is not None:
        date_range = str(date_range)
    exclude_sites = arguments.get("exclude_sites")

    if not query or len(query) > 1000:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": False,
                            "error": "Query is required (max 1000 chars)",
                        }
                    ),
                )
            ],
            isError=True,
        )

    if exclude_sites is not None:
        if not isinstance(exclude_sites, list):
            exclude_sites = None
        else:
            exclude_sites = [str(s) for s in exclude_sites if s is not None]

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: search_full(
            query,
            num_results,
            site=site,
            filetype=filetype,
            date_range=date_range,
            exclude_sites=exclude_sites,
        ),
    )

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, indent=2))]
    )


async def handle_scrape_url(arguments: dict) -> CallToolResult:
    """Handle scrape_url tool"""
    url = arguments.get("url", "")
    include_links = arguments.get("include_links", False)

    if not url or len(url) > 2048:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "error": "URL is required (max 2048 chars)"}
                    ),
                )
            ],
            isError=True,
        )

    # SSRF protection: validate URL before any outbound request
    url_ok, url_reason = validate_url(url)
    if not url_ok:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "error": f"URL blocked: {url_reason}"}
                    ),
                )
            ],
            isError=True,
        )

    # Run scraper in thread pool
    loop = asyncio.get_running_loop()

    def do_scrape():
        scraper = PooledSmartScraper()
        return scraper.scrape_to_dict(url, include_links=include_links)

    try:
        result = await loop.run_in_executor(None, do_scrape)
        result["success"] = True
        result["content_length"] = len(result.get("content", "") or "")
        result["browser_pooled"] = _browser_pool.is_initialized()

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2))]
        )

    except Exception as e:
        import sys

        print(f"[justscrape] scrape_url error for {url}: {e}", file=sys.stderr)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": False,
                            "error": "Scraping failed. Check server logs for details.",
                            "url": url,
                        },
                        indent=2,
                    ),
                )
            ],
            isError=True,
        )


async def handle_search_and_scrape(arguments: dict) -> CallToolResult:
    """
    Handle search_and_scrape tool.
    Full quality pipeline: query analysis -> search -> rerank -> scrape+extract -> score -> dedup -> return.
    Graceful fallback to old behavior if new pipeline fails.
    """
    query = arguments.get("query", "")
    if not isinstance(query, str):
        query = str(query) if query is not None else ""

    try:
        num_results = int(arguments.get("num_results", 3))
    except (TypeError, ValueError):
        num_results = 3
    num_results = max(1, min(num_results, 5))

    try:
        max_content_length = int(arguments.get("max_content_length", 5000))
    except (TypeError, ValueError):
        max_content_length = 5000
    max_content_length = max(100, min(max_content_length, 100000))

    site = arguments.get("site")
    if site is not None:
        site = str(site)
    date_range = arguments.get("date_range")
    if date_range is not None:
        date_range = str(date_range)

    if not query or len(query) > 1000:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": "Query is required"}),
                )
            ],
            isError=True,
        )

    loop = asyncio.get_running_loop()
    _cached_search_result = None  # Preserve for fallback reuse

    try:
        # Step 1: Analyze query
        analyzed = _query_analyzer.analyze(query)

        # Step 2: Search
        search_result = await loop.run_in_executor(
            None,
            lambda: search_full(
                query,
                num_results + 3,  # fetch extra to compensate for filtering
                site=site,
                date_range=date_range,
            ),
        )

        if not search_result.get("success", False):
            return CallToolResult(
                content=[
                    TextContent(type="text", text=json.dumps(search_result, indent=2))
                ],
                isError=True,
            )

        _cached_search_result = search_result  # Save for fallback reuse

        # Step 3: Rerank results before filtering
        search_results_as_dicts = [
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "position": r.get("position", i + 1),
            }
            for i, r in enumerate(search_result.get("results", []))
        ]
        ranked_results = _result_reranker.rerank(
            search_results_as_dicts, analyzed.intent
        )

        # Filter out blocked results and take top num_results
        candidates = []
        skipped = []
        for ranked in ranked_results:
            url = ranked.url
            if not url:
                continue

            ok, reason = should_scrape(url, ranked.snippet)
            if ok and len(candidates) < num_results:
                candidates.append(ranked)
            else:
                skipped.append(
                    {"url": url, "title": ranked.title, "skip_reason": reason}
                )

        # Step 4: Parallel scraping + snippet extraction
        scraper = PooledSmartScraper()

        async def scrape_and_extract_one(
            ranked: RankedResult,
        ) -> Optional[tuple]:
            """Returns (ScoredResult, all_snippets) or None."""
            url = ranked.url
            sem = _get_scrape_semaphore()

            # Hold semaphore only for network I/O, release before CPU work
            try:
                async with sem:
                    scraped = await loop.run_in_executor(
                        None, lambda u=url: scraper.scrape_to_dict(u)
                    )
                full_content = scraped.get("content", "") or ""
            except Exception as e:
                import sys
                print(f"[justscrape] Scrape failed for {url}: {e}", file=sys.stderr)
                return None

            try:
                # CPU-bound: snippet extraction + scoring (no semaphore needed)
                snippets = _snippet_extractor.extract_snippets(
                    html=full_content,
                    query=analyzed.original,
                    intent=analyzed.intent,
                    url=url,
                    top_n=3,
                )

                if snippets and len(snippets) > 0:
                    best_snippet = snippets[0]
                else:
                    fallback_text = full_content[:500] if full_content else ""
                    _js_indicators = ("var ", "function(", "(function(", "window.", "document.", "<!doctype", "<?xml")
                    is_js_garbage = fallback_text and any(
                        fallback_text.strip().lower().startswith(sig) for sig in _js_indicators
                    )
                    if is_js_garbage:
                        fallback_text = ""

                    best_snippet = ExtractedSnippet(
                        text=fallback_text,
                        chunk_index=0,
                        score=0.1,
                        is_code=False,
                        source_url=url,
                        best_sentence=fallback_text[:200] if fallback_text else "",
                    )
                    snippets = [best_snippet]

                scored = _quality_scorer.score(
                    snippet=best_snippet, ranked=ranked, query=analyzed
                )

                return (scored, snippets)
            except Exception as e:
                import sys
                print(f"[justscrape] Extract/score failed for {url}: {e}", file=sys.stderr)
                return None

        # Fire all scrape+extract tasks in parallel
        scrape_tasks = [
            scrape_and_extract_one(ranked)
            for ranked in candidates
        ]
        raw_results = await asyncio.gather(*scrape_tasks)
        # Collect (ScoredResult, snippets) pairs
        scored_with_snippets = [r for r in raw_results if r is not None]
        scored_results = [r[0] for r in scored_with_snippets]
        snippets_by_url = {r[0].url: r[1] for r in scored_with_snippets}

        # Step 5: Dedup
        deduped = deduplicate_results(scored_results, threshold=0.85)

        # Step 6: Build response — return only the relevant extracted content
        enriched_results = []
        for scored in deduped:
            snippets = snippets_by_url.get(scored.url, [])

            # Build content from extracted snippets only (not the full page)
            # This is the "grep" — only the parts that match the query
            content_parts = []
            for snip in snippets:
                content_parts.append(snip.text)
            content = "\n\n---\n\n".join(content_parts)

            if len(content) > max_content_length:
                content = (
                    content[:max_content_length]
                    + "\n\n[Truncated]"
                )

            enriched_results.append(
                {
                    "position": scored.original_position,
                    "title": scored.title,
                    "url": scored.url,
                    "content": content,
                    "best_sentence": scored.best_sentence,
                    "content_length": len(content),
                    "relevance_score": scored.composite_score,
                    "score_breakdown": scored.score_breakdown,
                    "source_type": scored.source_type,
                    "detected_date": scored.detected_date,
                    "confidence": scored.confidence,
                    "scraped_successfully": True,
                }
            )

        # Step 7: Sort by composite_score (highest first)
        enriched_results.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)

        response = {
            "success": True,
            "query": query,
            "results": enriched_results,
            "skipped": skipped,
            "total_results": len(enriched_results),
            "total_skipped": len(skipped),
            "search_time_ms": search_result.get("search_time_ms", 0),
            "search_cached": search_result.get("cached", False),
        }

        if not enriched_results and skipped:
            response["note"] = "All search results were filtered (blocked domains or unscrapeable)"

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(response, indent=2))]
        )

    except Exception as e:
        # Fallback to old behavior if new pipeline fails
        import sys

        print(
            f"[justscrape] Quality pipeline failed for '{query}', falling back to old behavior: {e}",
            file=sys.stderr,
        )

        # Reuse search result from the try block if available, else re-fetch
        if _cached_search_result is not None:
            search_result = _cached_search_result
        else:
            search_result = await loop.run_in_executor(
                None,
                lambda: search_full(
                    query,
                    num_results + 3,
                    site=site,
                    date_range=date_range,
                ),
            )

        if not search_result.get("success", False):
            return CallToolResult(
                content=[
                    TextContent(type="text", text=json.dumps(search_result, indent=2))
                ],
                isError=True,
            )

        candidates = []
        skipped = []
        for result in search_result.get("results", []):
            url = result.get("url", "")
            if not url:
                continue

            ok, reason = should_scrape(url, result.get("snippet", ""))
            if ok and len(candidates) < num_results:
                candidates.append(result)
            else:
                skipped.append(
                    {"url": url, "title": result.get("title"), "skip_reason": reason}
                )

        scraper = PooledSmartScraper()

        async def scrape_one(result: dict) -> dict:
            url = result.get("url", "")
            sem = _get_scrape_semaphore()
            async with sem:
                try:
                    scraped = await loop.run_in_executor(
                        None, lambda u=url: scraper.scrape_to_dict(u)
                    )
                    full_content = scraped.get("content", "") or ""
                    content = full_content
                    if len(content) > max_content_length:
                        content = (
                            content[:max_content_length]
                            + f"\n\n[Truncated - {len(full_content)} total chars]"
                        )

                    score = relevance_score(
                        query,
                        full_content,
                        scraped.get("title") or result.get("title", ""),
                    )

                    return {
                        "position": result.get("position"),
                        "title": scraped.get("title") or result.get("title"),
                        "url": url,
                        "snippet": result.get("snippet"),
                        "content": content,
                        "content_length": len(full_content),
                        "relevance_score": score,
                        "scraped_successfully": True,
                    }
                except Exception as e:
                    return {
                        "position": result.get("position"),
                        "title": result.get("title"),
                        "url": url,
                        "snippet": result.get("snippet"),
                        "content": None,
                        "error": "Scraping failed",
                        "relevance_score": 0.0,
                        "scraped_successfully": False,
                    }

        scrape_tasks = [scrape_one(r) for r in candidates]
        enriched_results = await asyncio.gather(*scrape_tasks)
        enriched_results = list(enriched_results)

        enriched_results.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)

        response = {
            "success": True,
            "query": query,
            "results": enriched_results,
            "skipped": skipped,
            "total_results": len(enriched_results),
            "total_skipped": len(skipped),
            "search_time_ms": search_result.get("search_time_ms", 0),
            "search_cached": search_result.get("cached", False),
        }

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(response, indent=2))]
        )


async def handle_extract_urls(arguments: dict) -> CallToolResult:
    """Handle extract_urls tool"""
    url = arguments.get("url", "")
    filter_external = arguments.get("filter_external", False)

    if not url:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": "URL is required"}),
                )
            ],
            isError=True,
        )

    # SSRF protection: validate URL before any outbound request
    url_ok, url_reason = validate_url(url)
    if not url_ok:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "error": f"URL blocked: {url_reason}"}
                    ),
                )
            ],
            isError=True,
        )

    from .web_scraper import WebScraper, ContentType
    from urllib.parse import urlparse

    loop = asyncio.get_running_loop()

    def do_extract():
        scraper = WebScraper()
        result = scraper.scrape(url, [ContentType.LINKS])
        return result.links or []

    try:
        links = await loop.run_in_executor(None, do_extract)

        # Filter if requested
        if filter_external:
            source_domain = urlparse(url).netloc.lower().replace("www.", "")
            links = [
                link
                for link in links
                if urlparse(link).netloc.lower().replace("www.", "") != source_domain
            ]

        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": True,
                            "source_url": url,
                            "urls": links,
                            "count": len(links),
                        },
                        indent=2,
                    ),
                )
            ]
        )

    except Exception as e:
        import sys
        print(f"[justscrape] extract_urls failed for {url}: {e}", file=sys.stderr)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "error": "Extraction failed", "url": url}, indent=2
                    ),
                )
            ],
            isError=True,
        )


async def handle_get_stats(arguments: dict) -> CallToolResult:
    """Handle get_stats tool — includes memory cache, persistent cache, and browser pool"""
    stats = {
        "success": True,
        "search_cache": get_cache_stats(),
        "browser_pool": _browser_pool.get_stats(),
    }

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(stats, indent=2))]
    )


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
