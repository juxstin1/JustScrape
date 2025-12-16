#!/usr/bin/env python3
"""
JustScrape MCP Server - Web Search & Scraping Capability Worker

This MCP server exposes web search and scraping tools for AI models.
Following the TOOL-worker architecture:
- Deterministic execution
- No reasoning, just capabilities
- Structured input/output
- Fail loudly with metadata

Tools exposed:
- web_search: Free SERP-style search via DuckDuckGo
- scrape_url: Clean content extraction from any URL
- search_and_scrape: Search + fetch top results in one call
- extract_urls: Extract links from a page

Features:
- TTL cache for search results (5 min)
- Exponential backoff for rate limiting
- Lazy browser pool for JS rendering (only init when needed)

Usage:
    python justscrape_mcp.py

Or add to Claude Desktop config:
    {
        "mcpServers": {
            "justscrape": {
                "command": "python",
                "args": ["/path/to/justscrape_mcp.py"]
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
from web_search import WebSearch, search_full, get_cache_stats
from smart_scraper import SmartScraper, scrape_article


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
            "idle_seconds": int(time.time() - self._last_used) if self._last_used else None
        }

    def shutdown(self):
        """Shutdown browser and playwright"""
        with self._init_lock:
            if self._browser:
                try:
                    self._browser.close()
                except:
                    pass
                self._browser = None

            if self._playwright:
                try:
                    self._playwright.stop()
                except:
                    pass
                self._playwright = None


# Global browser pool (lazy singleton)
_browser_pool = LazyBrowserPool()


class PooledSmartScraper(SmartScraper):
    """
    SmartScraper that uses the lazy browser pool for JS rendering.
    Avoids cold starts on every JS scrape.
    """

    def scrape(self, url, content_types=None, force_method=None):
        """Override to use pooled browser for JS scraping"""
        from web_scraper import ContentType

        if content_types is None:
            content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]

        # Determine if we need JS
        use_js = (
            self.force_js or
            force_method == 'js' or
            (force_method != 'static' and self._is_js_heavy_site(url))
        )

        if not use_js:
            # Try static first
            result = self.static_scraper.scrape(url, content_types)
            content_ok = result.content and len(result.content) >= self.min_content_length

            if content_ok:
                return result

            use_js = True

        # Use pooled browser for JS
        if use_js:
            return self._scrape_with_pooled_browser(url, content_types)

        return result

    def _scrape_with_pooled_browser(self, url, content_types):
        """Scrape using pooled browser"""
        from web_scraper import ScrapedContent, ContentType
        from bs4 import BeautifulSoup

        browser = _browser_pool.get_browser()
        page = browser.new_page()

        try:
            # Set viewport
            page.set_viewport_size({"width": 1920, "height": 1080})

            # Block tracking/ads
            def route_handler(route):
                blocked_patterns = [
                    'google-analytics', 'googletagmanager', 'doubleclick',
                    'facebook.com/tr', 'facebook.net', 'twitter.com/i/adsct'
                ]
                if any(p in route.request.url for p in blocked_patterns):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", route_handler)

            # Navigate
            page.goto(url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)  # Let JS settle

            html = page.content()
            soup = BeautifulSoup(html, 'lxml')

            # Extract content
            title = soup.title.string if soup.title else None

            # Remove junk
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                tag.decompose()

            # Find main content
            main = soup.find('article') or soup.find('main') or soup.find('body')
            content = main.get_text(separator='\n', strip=True) if main else ""

            # Clean up
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            content = '\n'.join(lines)

            # Extract metadata
            metadata = {}
            if ContentType.METADATA in content_types:
                meta_desc = soup.find('meta', attrs={'name': 'description'})
                if meta_desc:
                    metadata['description'] = meta_desc.get('content', '')

            # Extract links
            links = None
            if ContentType.LINKS in content_types:
                links = [a.get('href') for a in soup.find_all('a', href=True)]
                links = [l for l in links if l.startswith('http')]

            return ScrapedContent(
                url=url,
                title=title,
                content=content,
                metadata=metadata,
                links=links,
                images=None,
                structured_data=None,
                scrape_method='javascript_pooled'
            )

        finally:
            page.close()


# Initialize MCP server
server = Server("justscrape")


# Tool definitions
@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools"""
    return [
        Tool(
            name="web_search",
            description="""Search the web using DuckDuckGo (free, no API key needed).
Returns SERP-style results with titles, URLs, and snippets.
Results are cached for 5 minutes to avoid rate limiting.

Returns: JSON with query, results array, cached flag, and metadata.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10, max: 25)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
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
                    "url": {
                        "type": "string",
                        "description": "The URL to scrape"
                    },
                    "include_links": {
                        "type": "boolean",
                        "description": "Include extracted links from the page",
                        "default": False
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="search_and_scrape",
            description="""Search the web AND scrape the top results in one call.
Combines web_search + scrape_url for efficient research.

Flow:
1. Search DuckDuckGo for the query
2. Scrape the top N results
3. Return search results with full content

Perfect for research tasks where you need actual content, not just links.

Returns: JSON with search results, each including full scraped content.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to search and scrape (default: 3, max: 5)",
                        "default": 3
                    },
                    "max_content_length": {
                        "type": "integer",
                        "description": "Max characters per scraped page (default: 5000)",
                        "default": 5000
                    }
                },
                "required": ["query"]
            }
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
                        "description": "The URL to extract links from"
                    },
                    "filter_external": {
                        "type": "boolean",
                        "description": "Only return external links (different domain)",
                        "default": False
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="get_stats",
            description="""Get MCP server statistics including cache and browser pool status.
Useful for debugging and monitoring.

Returns: JSON with cache stats and browser pool status.""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
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
                content=[TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Unknown tool: {name}"
                    }, indent=2)
                )],
                isError=True
            )

    except Exception as e:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": str(e),
                    "tool": name
                }, indent=2)
            )],
            isError=True
        )


async def handle_web_search(arguments: dict) -> CallToolResult:
    """Handle web_search tool"""
    query = arguments.get("query", "")
    num_results = min(arguments.get("num_results", 10), 25)

    if not query:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"success": False, "error": "Query is required"})
            )],
            isError=True
        )

    # Run search in thread pool to not block
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: search_full(query, num_results))

    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]
    )


async def handle_scrape_url(arguments: dict) -> CallToolResult:
    """Handle scrape_url tool"""
    url = arguments.get("url", "")
    include_links = arguments.get("include_links", False)

    if not url:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"success": False, "error": "URL is required"})
            )],
            isError=True
        )

    # Run scraper in thread pool
    loop = asyncio.get_event_loop()

    def do_scrape():
        scraper = PooledSmartScraper()
        return scraper.scrape_to_dict(url, include_links=include_links)

    try:
        result = await loop.run_in_executor(None, do_scrape)
        result["success"] = True
        result["content_length"] = len(result.get("content", "") or "")
        result["browser_pooled"] = _browser_pool.is_initialized()

        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        )

    except Exception as e:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": str(e),
                    "url": url
                }, indent=2)
            )],
            isError=True
        )


async def handle_search_and_scrape(arguments: dict) -> CallToolResult:
    """Handle search_and_scrape tool"""
    query = arguments.get("query", "")
    num_results = min(arguments.get("num_results", 3), 5)
    max_content_length = arguments.get("max_content_length", 5000)

    if not query:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"success": False, "error": "Query is required"})
            )],
            isError=True
        )

    loop = asyncio.get_event_loop()

    # First, search
    search_result = await loop.run_in_executor(
        None, lambda: search_full(query, num_results)
    )

    if not search_result.get("success", False):
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps(search_result, indent=2)
            )],
            isError=True
        )

    # Then scrape each result using pooled scraper
    scraper = PooledSmartScraper()
    enriched_results = []

    for result in search_result.get("results", []):
        url = result.get("url", "")
        if not url:
            continue

        try:
            scraped = await loop.run_in_executor(
                None, lambda u=url: scraper.scrape_to_dict(u)
            )

            # Truncate content if needed
            content = scraped.get("content", "") or ""
            if len(content) > max_content_length:
                content = content[:max_content_length] + f"\n\n[Truncated - {len(scraped.get('content', ''))} total chars]"

            enriched_results.append({
                "position": result.get("position"),
                "title": result.get("title"),
                "url": url,
                "snippet": result.get("snippet"),
                "content": content,
                "content_length": len(scraped.get("content", "") or ""),
                "scraped_successfully": True
            })

        except Exception as e:
            enriched_results.append({
                "position": result.get("position"),
                "title": result.get("title"),
                "url": url,
                "snippet": result.get("snippet"),
                "content": None,
                "error": str(e),
                "scraped_successfully": False
            })

    response = {
        "success": True,
        "query": query,
        "results": enriched_results,
        "total_results": len(enriched_results),
        "search_time_ms": search_result.get("search_time_ms", 0),
        "search_cached": search_result.get("cached", False)
    }

    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]
    )


async def handle_extract_urls(arguments: dict) -> CallToolResult:
    """Handle extract_urls tool"""
    url = arguments.get("url", "")
    filter_external = arguments.get("filter_external", False)

    if not url:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"success": False, "error": "URL is required"})
            )],
            isError=True
        )

    from web_scraper import WebScraper, ContentType
    from urllib.parse import urlparse

    loop = asyncio.get_event_loop()

    def do_extract():
        scraper = WebScraper()
        result = scraper.scrape(url, [ContentType.LINKS])
        return result.links or []

    try:
        links = await loop.run_in_executor(None, do_extract)

        # Filter if requested
        if filter_external:
            source_domain = urlparse(url).netloc.lower().replace('www.', '')
            links = [
                link for link in links
                if urlparse(link).netloc.lower().replace('www.', '') != source_domain
            ]

        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "source_url": url,
                    "urls": links,
                    "count": len(links)
                }, indent=2)
            )]
        )

    except Exception as e:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": str(e),
                    "url": url
                }, indent=2)
            )],
            isError=True
        )


async def handle_get_stats(arguments: dict) -> CallToolResult:
    """Handle get_stats tool"""
    stats = {
        "success": True,
        "search_cache": get_cache_stats(),
        "browser_pool": _browser_pool.get_stats()
    }

    return CallToolResult(
        content=[TextContent(
            type="text",
            text=json.dumps(stats, indent=2)
        )]
    )


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
