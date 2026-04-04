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
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
)

# Import handlers from the new handler modules
from .handlers import (
    handle_web_search,
    handle_search_sources,
    handle_scrape_url,
    handle_retrieve_source,
    handle_research_with_sources,
    handle_search_and_scrape,
    handle_extract_urls,
    handle_get_stats,
)

# Backward-compatible re-exports so existing imports from justscrape.server still work
from .handlers.research import _is_fast_lane_eligible, _handle_fast_lane  # noqa: F401
from .browser_pool import LazyBrowserPool, PooledSmartScraper  # noqa: F401

# Initialize MCP server
server = Server("justscrape")


# Tool definitions
@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools"""
    return [
        Tool(
            name="research_with_sources",
            description="""Recommended default for answering questions with web evidence.
Searches, retrieves, classifies, and separates usable sources from failures in one call.
Use this instead of looping search-only tools with small query rewrites.
If usable sources are returned, answer from them instead of searching again.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "limit": {
                        "type": "integer",
                        "description": "Number of candidate results to retrieve (default: 5, max: 10)",
                        "default": 5,
                    },
                    "allow_javascript": {
                        "type": "boolean",
                        "description": "Allow JS rendering for difficult pages (default: true)",
                        "default": True,
                    },
                    "max_content_length": {
                        "type": "integer",
                        "description": "Max characters per returned source (default: 5000)",
                        "default": 5000,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="retrieve_source",
            description="""Retrieve one URL and classify the outcome.
Returns explicit classification.status: usable, thin, blocked, encoding-failure, or empty.
If the status is not usable, treat that as a real result and move on instead of retrying the same page.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to retrieve"},
                    "allow_javascript": {
                        "type": "boolean",
                        "description": "Allow Playwright JS rendering if static scraping is insufficient",
                        "default": True,
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="search_sources",
            description="""Search-only discovery tool.
Returns ranked URLs and snippets without page content.
Use at most once to discover candidates, then switch to research_with_sources or retrieve_source.
Do not loop this with minor query rewrites unless the search intent materially changes.""",
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
            name="search_and_scrape",
            description="""Legacy alias for research_with_sources.
Searches and scrapes top results in one call.
Prefer research_with_sources for new integrations because it separates usable sources from failures.""",
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
            name="scrape_url",
            description="""Legacy alias for retrieve_source.
Scrapes a single URL and returns content plus classification hints.
Prefer retrieve_source for new integrations because it returns an explicit outcome contract.""",
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
            name="web_search",
            description="""Legacy alias for search_sources.
Search-only discovery tool that returns titles, URLs, and snippets.
Prefer research_with_sources for question answering, and avoid repeating web_search with minor query rewrites.""",
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
        if name == "search_sources":
            return await handle_search_sources(arguments)
        elif name == "retrieve_source":
            return await handle_retrieve_source(arguments)
        elif name == "research_with_sources":
            return await handle_research_with_sources(arguments)
        elif name == "web_search":
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


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
