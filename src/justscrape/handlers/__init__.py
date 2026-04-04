"""
MCP tool handlers for JustScrape.

Re-exports all handler functions for convenient imports.
"""

from .search import handle_web_search, handle_search_sources
from .scrape import handle_scrape_url, handle_retrieve_source, handle_extract_urls
from .research import (
    handle_search_and_scrape,
    handle_research_with_sources,
    _is_fast_lane_eligible,
    _handle_fast_lane,
)
from .stats import handle_get_stats

__all__ = [
    "handle_web_search",
    "handle_search_sources",
    "handle_scrape_url",
    "handle_retrieve_source",
    "handle_extract_urls",
    "handle_search_and_scrape",
    "handle_research_with_sources",
    "handle_get_stats",
    "_is_fast_lane_eligible",
    "_handle_fast_lane",
]
