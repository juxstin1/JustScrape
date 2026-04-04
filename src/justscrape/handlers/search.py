"""
Search-related MCP tool handlers.

Handles: web_search, search_sources
"""

import asyncio
import json

from mcp.types import TextContent, CallToolResult

from ..web_search import search_full


async def handle_search_sources(arguments: dict) -> CallToolResult:
    """Handle refined search_sources tool with anti-loop guidance."""
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
                    text=json.dumps({"error": "Query is required (max 1000 chars)"}),
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

    if not result.get("success", False):
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps({"error": result.get("error", "Search failed")}),
                )
            ],
            isError=True,
        )

    response = {
        "query": result.get("query", query),
        "results": result.get("results", []),
        "total_results": result.get("total_results", 0),
        "search_time_ms": result.get("search_time_ms", 0),
        "source": result.get("source", "duckduckgo"),
        "cached": result.get("cached", False),
        "usage_hint": {
            "recommended_next_tool": "research_with_sources",
            "legacy_fallback_tool": "search_and_scrape",
            "search_loop_guard": "Search results are discovery-only. Avoid repeating search_sources/web_search with minor query rewrites; inspect a candidate URL or switch to a research tool.",
        },
    }

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(response, indent=2))]
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

    result = dict(result)
    result["usage_hint"] = {
        "recommended_next_tool": "search_and_scrape",
        "preferred_new_tool": "research_with_sources",
        "search_loop_guard": "Search results are discovery-only. Avoid repeating web_search with minor query rewrites; inspect a candidate URL or switch to a research tool.",
    }

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, indent=2))]
    )
