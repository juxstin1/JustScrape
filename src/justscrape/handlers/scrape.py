"""
Scrape-related MCP tool handlers.

Handles: scrape_url, retrieve_source, extract_urls
"""

import asyncio
import json

from mcp.types import TextContent, CallToolResult

from ..browser_pool import PooledSmartScraper, _browser_pool
from ..url_validator import validate_url
from ._shared import _normalize_bool, _build_retrieve_payload


async def handle_retrieve_source(arguments: dict) -> CallToolResult:
    """Handle refined retrieve_source tool with explicit classification."""
    url = arguments.get("url", "")
    allow_javascript = _normalize_bool(arguments.get("allow_javascript"), True)

    if not url or len(url) > 2048:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps({"error": "URL is required (max 2048 chars)"}),
                )
            ],
            isError=True,
        )

    url_ok, url_reason = validate_url(url)
    if not url_ok:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"URL blocked: {url_reason}"}),
                )
            ],
            isError=True,
        )

    loop = asyncio.get_running_loop()

    def do_retrieve():
        scraper = PooledSmartScraper()
        force_method = None if allow_javascript else "static"
        scraped = scraper.scrape_to_dict(url, force_method=force_method)
        payload = _build_retrieve_payload(url, scraped)
        payload["usage_hint"] = {
            "recommended_action": (
                "extract_answer_or_cite"
                if payload["classification"]["status"] == "usable"
                else "choose_another_source"
            ),
            "search_loop_guard": "If classification.status is not usable, move to another source instead of retrying the same URL.",
        }
        return payload

    try:
        result = await loop.run_in_executor(None, do_retrieve)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2))]
        )
    except Exception as e:
        import sys

        print(f"[justscrape] retrieve_source error for {url}: {e}", file=sys.stderr)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": "Retrieval failed. Check server logs for details.",
                            "url": url,
                        },
                        indent=2,
                    ),
                )
            ],
            isError=True,
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
        refined = _build_retrieve_payload(url, result)
        result["success"] = True
        result["content_length"] = len(result.get("content", "") or "")
        result["browser_pooled"] = _browser_pool.is_initialized()
        result["signals"] = refined["signals"]
        result["classification"] = refined["classification"]
        if refined.get("warnings"):
            result["warnings"] = refined["warnings"]
        result["usage_hint"] = {
            "recommended_action": (
                "extract_answer_or_cite"
                if refined["classification"]["status"] == "usable"
                else "choose_another_source"
            ),
            "search_loop_guard": "If classification.status is not usable, pick another source instead of scraping similar pages repeatedly.",
        }

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

    from ..web_scraper import WebScraper, ContentType
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
