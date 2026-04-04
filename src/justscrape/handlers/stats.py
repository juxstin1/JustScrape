"""
Stats MCP tool handler.

Handles: get_stats
"""

import json

from mcp.types import TextContent, CallToolResult

from ..web_search import get_cache_stats
from ..browser_pool import _browser_pool


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
