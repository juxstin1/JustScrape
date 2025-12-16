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
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
)

# Import our modules
from web_search import WebSearch, search_full
from smart_scraper import SmartScraper, scrape_article


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
Use this to find information, discover URLs, or research topics.

Returns: JSON with query, results array, and metadata.""",
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
Returns clean text optimized for LLM consumption.

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
        scraper = SmartScraper()
        return scraper.scrape_to_dict(url, include_links=include_links)

    try:
        result = await loop.run_in_executor(None, do_scrape)
        result["success"] = True
        result["content_length"] = len(result.get("content", "") or "")

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

    # Then scrape each result
    scraper = SmartScraper()
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
        "search_time_ms": search_result.get("search_time_ms", 0)
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
