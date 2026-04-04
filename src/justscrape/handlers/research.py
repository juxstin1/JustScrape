"""
Research-related MCP tool handlers.

Handles: search_and_scrape, research_with_sources
Includes fast lane logic for simple queries.
"""

import asyncio
import json
from typing import Optional

from mcp.types import TextContent, CallToolResult

from ..web_search import search_full, should_scrape, relevance_score
from ..browser_pool import PooledSmartScraper
from ..query_analyzer import QueryAnalyzer, AnalyzedQuery
from ..result_reranker import ResultReranker, RankedResult
from ..snippet_extractor import SnippetExtractor, ExtractedSnippet
from ..quality_scorer import QualityScorer, ScoredResult, deduplicate_results
from ..worker import research_with_sources as research_with_sources_contract
from ._shared import _normalize_bool, _get_scrape_semaphore

# Phase 2 quality pipeline singletons
_query_analyzer = QueryAnalyzer()
_result_reranker = ResultReranker()
_snippet_extractor = SnippetExtractor()
_quality_scorer = QualityScorer()


async def handle_research_with_sources(arguments: dict) -> CallToolResult:
    """Handle refined research_with_sources contract for clients like LM Studio."""
    query = arguments.get("query", "")
    if not isinstance(query, str):
        query = str(query) if query is not None else ""

    try:
        limit = int(arguments.get("limit", arguments.get("num_results", 5)))
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 10))

    allow_javascript = _normalize_bool(arguments.get("allow_javascript"), True)

    try:
        max_content_length = int(arguments.get("max_content_length", 5000))
    except (TypeError, ValueError):
        max_content_length = 5000
    max_content_length = max(100, min(max_content_length, 100000))

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

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: research_with_sources_contract(
            query=query,
            limit=limit,
            allow_javascript=allow_javascript,
            max_content_length=max_content_length,
        ),
    )

    metrics = result.get("metrics", {})
    usable_count = metrics.get("usable_count", 0)
    result["usage_hint"] = {
        "recommended_action": (
            "answer_from_sources" if usable_count > 0 else "inspect_failures_or_reformulate_once"
        ),
        "search_loop_guard": "Do not immediately repeat the same search with minor query rewrites. Check sources, failures, and skipped entries first.",
    }

    if result.get("search_error"):
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2))],
            isError=True,
        )

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, indent=2))]
    )


# =============================================================================
# FAST LANE — lightweight path for simple queries
# =============================================================================

def _is_fast_lane_eligible(analyzed: AnalyzedQuery) -> bool:
    """Decide whether a query can skip the heavy quality pipeline.

    Simple lookups and general questions (pizza delivery, weather, stock price)
    don't benefit from BM25 snippet scoring, authority reranking, or fuzzy dedup.
    The QueryAnalyzer already classifies these — we just check the signals.

    Eligible when ALL of these are true:
    - Intent is "general" or "lookup"
    - No entities detected (no version numbers, libraries, languages)
    - No sub-queries from conjunction decomposition
    - Confidence is low-to-moderate (no strong structural signal)
    """
    if analyzed.intent not in ("general", "lookup"):
        return False
    if analyzed.entities:
        return False
    if len(analyzed.sub_queries) > 1:
        return False
    # Lookup with high confidence still benefits from authority reranking
    if analyzed.intent == "lookup" and analyzed.confidence > 0.8:
        return False
    return True


async def _handle_fast_lane(
    *,
    query: str,
    analyzed: AnalyzedQuery,
    num_results: int,
    max_content_length: int,
    site: Optional[str],
    date_range: Optional[str],
    loop: asyncio.AbstractEventLoop,
) -> CallToolResult:
    """Lightweight search+scrape path that skips reranking, snippet extraction,
    quality scoring, and dedup. Returns basic scraped content ranked by a
    simple relevance score.

    Typically 2-3x faster than the full pipeline for everyday queries.
    """
    import sys

    # Search — no extra padding needed, we trust the top results
    search_result = await loop.run_in_executor(
        None,
        lambda: search_full(query, num_results, site=site, date_range=date_range),
    )

    if not search_result.get("success", False):
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(search_result, indent=2))],
            isError=True,
        )

    # Pre-filter (still respect blocked domains / robots.txt)
    candidates = []
    skipped = []
    for i, r in enumerate(search_result.get("results", [])):
        url = r.get("url", "")
        if not url:
            continue
        ok, reason = should_scrape(url, r.get("snippet", ""))
        if ok and len(candidates) < num_results:
            candidates.append(r)
        else:
            skipped.append({"url": url, "title": r.get("title"), "skip_reason": reason})

    # Parallel scrape — basic content extraction, no snippet scoring
    scraper = PooledSmartScraper()

    async def _scrape_basic(result: dict) -> dict:
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
                    content = content[:max_content_length] + "\n\n[Truncated]"

                score = relevance_score(
                    query,
                    full_content,
                    scraped.get("title") or result.get("title", ""),
                )

                return {
                    "position": result.get("position", 0),
                    "title": scraped.get("title") or result.get("title"),
                    "url": url,
                    "content": content,
                    "best_sentence": result.get("snippet", ""),
                    "content_length": len(full_content),
                    "relevance_score": score,
                    "source_type": "unknown",
                    "detected_date": None,
                    "confidence": analyzed.confidence,
                    "scraped_successfully": True,
                    "fast_lane": True,
                }
            except Exception as e:
                print(f"[justscrape] Fast-lane scrape failed for {url}: {e}", file=sys.stderr)
                return {
                    "position": result.get("position", 0),
                    "title": result.get("title"),
                    "url": url,
                    "content": None,
                    "error": "Scraping failed",
                    "relevance_score": 0.0,
                    "scraped_successfully": False,
                    "fast_lane": True,
                }

    tasks = [_scrape_basic(r) for r in candidates]
    enriched_results = list(await asyncio.gather(*tasks))
    enriched_results.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)

    response = {
        "success": True,
        "query": query,
        "query_intent": analyzed.intent,
        "fast_lane": True,
        "results": enriched_results,
        "skipped": skipped,
        "total_results": len(enriched_results),
        "total_skipped": len(skipped),
        "search_time_ms": search_result.get("search_time_ms", 0),
        "search_cached": search_result.get("cached", False),
        "usage_hint": {
            "recommended_action": (
                "answer_from_results"
                if enriched_results
                else "inspect_skipped_or_reformulate_once"
            ),
            "preferred_new_tool": "research_with_sources",
            "search_loop_guard": "Avoid calling web_search again with minor query rewrites when results or skipped entries are already present.",
        },
    }

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(response, indent=2))]
    )


# =============================================================================
# FULL PIPELINE — heavy path for complex queries
# =============================================================================

async def handle_search_and_scrape(arguments: dict) -> CallToolResult:
    """
    Handle search_and_scrape tool.
    Full quality pipeline: query analysis -> search -> rerank -> scrape+extract -> score -> dedup -> return.
    Graceful fallback to old behavior if new pipeline fails.
    Simple queries are routed to the fast lane (no reranking, no snippet extraction).
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

        # Fast lane: simple queries skip the heavy pipeline (reranking,
        # BM25/TF-IDF snippet extraction, quality scoring, dedup).
        # The QueryAnalyzer already knows when a query is simple — we just
        # act on that signal instead of sending everything through six stages.
        if _is_fast_lane_eligible(analyzed):
            return await _handle_fast_lane(
                query=query,
                analyzed=analyzed,
                num_results=num_results,
                max_content_length=max_content_length,
                site=site,
                date_range=date_range,
                loop=loop,
            )

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
        response["usage_hint"] = {
            "recommended_action": (
                "answer_from_results"
                if enriched_results
                else "inspect_skipped_or_reformulate_once"
            ),
            "preferred_new_tool": "research_with_sources",
            "search_loop_guard": "Avoid calling web_search again with minor query rewrites when results or skipped entries are already present.",
        }

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
            "usage_hint": {
                "recommended_action": (
                    "answer_from_results"
                    if enriched_results
                    else "inspect_skipped_or_reformulate_once"
                ),
                "preferred_new_tool": "research_with_sources",
                "search_loop_guard": "Avoid calling web_search again with minor query rewrites when results or skipped entries are already present.",
            },
        }

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(response, indent=2))]
        )
