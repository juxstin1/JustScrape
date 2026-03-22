# JustScrape — Developer Guide & Future Direction

## Current State (March 2026)

JustScrape is a working MCP server that delivers search results to AI models at ~1,000 tokens per query. The full quality pipeline is live:

```
QueryAnalyzer → SearXNG → ResultReranker → Scrape + SnippetExtractor → QualityScorer → Dedup
```

**Stats:** 39 Python files, ~12,000 lines, 215 tests passing, 16 test files.

**What works well:**
- SearXNG self-hosted search — no rate limits, no API keys, aggregates Google + Bing + 70 engines
- Snippet extraction — BM25 + TF-IDF scoring returns only the relevant chunks, not full pages
- Composite scoring — results ranked by relevance + authority + freshness + position
- Graceful degradation — Playwright missing? Falls back to static. Pipeline crashes? Falls back to old behavior.

**What's rough:**
- Some results score 0.00 when snippet extractor can't find relevant chunks (fallback text with no scoring)
- Non-English content extraction is untested territory
- Single-word queries tend to return fewer results (broad queries + strict extraction = low recall)
- No retry/reformulation when results are poor

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                 justscrape_mcp.py (MCP Server)              │
│                                                             │
│  Quality Pipeline (search_and_scrape):                      │
│  ┌──────────────┐ ┌───────────────┐ ┌───────────────────┐  │
│  │QueryAnalyzer │→│ ResultReranker│→│ SnippetExtractor  │  │
│  └──────────────┘ └───────────────┘ └───────────────────┘  │
│  ┌──────────────┐ ┌───────────────┐                        │
│  │QualityScorer │→│   Dedup       │                        │
│  └──────────────┘ └───────────────┘                        │
│                                                             │
│  Other tools: web_search, scrape_url, extract_urls          │
└─────────────────────────────────┬───────────────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
             ┌───────────┐ ┌───────────┐ ┌───────────┐
             │web_search │ │smart_scra.│ │async_scra.│
             │ (SearXNG) │ │(static+JS)│ │(httpx/H2) │
             └─────┬─────┘ └───────────┘ └───────────┘
                   ▼
             ┌───────────┐
             │ SearXNG   │ Docker: localhost:8080
             │ (70+ eng) │
             └───────────┘
```

### Key Files

| File | Lines | What It Does |
|------|-------|-------------|
| `justscrape_mcp.py` | ~950 | MCP server, pipeline orchestration, tool handlers |
| `web_search.py` | ~1000 | Search orchestration, 2-layer cache, SearXNG integration |
| `smart_scraper.py` | ~1200 | Static/JS auto-routing, source adapters |
| `query_analyzer.py` | ~300 | Intent classification, query expansion, entity extraction |
| `result_reranker.py` | ~250 | Authority scoring, freshness weighting |
| `snippet_extractor.py` | ~350 | trafilatura + BM25/TF-IDF chunk scoring |
| `quality_scorer.py` | ~330 | Composite scoring, source type inference, dedup |
| `web_scraper.py` | ~530 | Static scraping, robots.txt, rate limiting |
| `url_validator.py` | ~200 | SSRF protection |

### Data Flow

1. AI model calls `search_and_scrape` via MCP with a query
2. `QueryAnalyzer` classifies intent (code/news/research/etc.), expands query, extracts entities
3. `web_search.py` sends query to SearXNG, gets ~10 results
4. `ResultReranker` scores each result by domain authority (per query type) and freshness
5. Top N non-blocked results are scraped concurrently (semaphore-limited)
6. `SnippetExtractor` runs trafilatura on each page, chunks the text, scores chunks via BM25+TF-IDF
7. `QualityScorer` computes composite score per result (relevance 45% + authority 20% + freshness 0-25% + position 15%)
8. `deduplicate_results` removes near-identical snippets via rapidfuzz
9. Response returned with only the relevant extracted chunks + provenance metadata

### Token Budget

| Results | Tokens | What's Included |
|---------|--------|----------------|
| 1 | ~350 | Best snippet + metadata |
| 2 | ~850 | Two snippets + metadata |
| 3 | ~1,200 | Three snippets + metadata |

Previous architecture returned ~5,200 tokens for 3 results (full page dumps).

## Roadmap

### Phase 3: Advanced Features (Next)

**Neural Re-ranking** — When `sentence-transformers` is installed, re-rank results using a cross-encoder model for semantic relevance. When absent, fall back to BM25/TF-IDF (same pattern as Playwright).

**Intelligent Retry** — When initial results score below a quality floor (0.3), automatically:
1. Reformulate the query using expanded variants from QueryAnalyzer
2. Retry the search
3. Hard limit: 3 attempts, 15 seconds total wall-clock

### Future Ideas

**Better Snippet Scoring (0.00 problem)**
Some results currently score 0.00 because the snippet extractor's fallback path doesn't run scoring. When a page is successfully scraped but extraction finds no relevant chunks, we should still score the fallback text against the query rather than returning score=0.1 blindly. This is the single biggest quality win remaining.

**Multi-Query Synthesis**
For complex queries ("compare React and Svelte performance"), search each sub-query independently, scrape the best result per sub-query, then return a merged response. QueryAnalyzer already decomposes these — just need to wire the sub-queries into parallel searches.

**Adaptive Extraction**
Different content types need different extraction strategies:
- Code documentation → extract code blocks + surrounding explanation
- News articles → extract lead paragraph + key facts
- Forum posts → extract accepted answer or highest-voted
- API docs → extract function signatures + parameters

The intent classification from QueryAnalyzer could drive this selection.

**SearXNG Engine Tuning**
SearXNG's default config queries all engines. Tuning which engines are queried per intent type could improve both speed and relevance:
- Code queries → prioritize Stack Overflow, GitHub, MDN engines
- News → prioritize Google News, Bing News, Reuters engines
- Research → prioritize Google Scholar, Wikipedia engines

**Streaming Results**
MCP currently requires complete responses. If/when MCP adds streaming support, we could return results as they're scraped rather than waiting for all to complete. This would improve perceived latency from ~5-10s to <1s for the first result.

**Result Caching by Semantic Similarity**
The current cache is exact-match on query string. A semantic cache using embeddings could serve cached results for "python exception handling" when someone asks "how to handle errors in python". Requires an embedding model — could use a small local one.

## Contributing

### Running Tests

```bash
python -m pytest tests/ -q          # Full suite (215 tests)
python -m pytest tests/ -x -v       # Stop on first failure, verbose
python -m pytest tests/test_pipeline_integration.py -v  # Pipeline only
```

### Adding a Search Backend

1. Create `backends/your_backend.py`
2. Implement `SearchBackend` ABC from `backends/base.py`
3. Must implement `search(query, num_results, region, date_range) → SearchResponse`
4. Optionally implement `is_available() → bool` for health checks
5. Wire into `web_search.py`'s `WebSearch.search()` fallback chain

### Adding a Source Adapter

Source adapters in `smart_scraper.py` handle sites that need special extraction (Reddit JSON API, Stack Exchange API, etc.):

1. Add detection logic in `_try_source_adapter()`
2. Implement the adapter method (e.g., `_fetch_reddit_json()`)
3. Return a `ScrapedContent` object

### Quality Pipeline Extension Points

- **New scoring signal** → Add to `QualityScorer.score()` and update weight distribution
- **New entity type** → Add regex pattern to `QueryAnalyzer.extract_entities()`
- **New authority tier** → Add domain patterns to `AUTHORITY_TIERS` in `result_reranker.py`
- **New source type** → Add to `_SOURCE_TYPE_PATTERNS` in `quality_scorer.py`

### SearXNG Setup

```bash
# First time
mkdir -p ~/searxng
# settings.yml must have formats: [html, json] and limiter: false
sudo docker run -d --name searxng -p 8080:8080 \
  -v ~/searxng/settings.yml:/etc/searxng/settings.yml \
  searxng/searxng

# Daily use
sudo docker start searxng   # Start
sudo docker stop searxng     # Stop
sudo docker logs searxng     # Debug

# Test
curl "http://localhost:8080/search?q=test&format=json" | python -m json.tool
```

## Design Principles

1. **Snippet, not page.** Return the exact relevant chunk. An AI model doesn't need 5,000 chars of HTML to answer "what's the syntax for Python try/except."

2. **Free or die.** No paid APIs, no API keys, no rate limits. Self-hosted SearXNG is the only search backend. If it's not running, return a clear error with the docker command to fix it.

3. **Graceful degradation, not crashes.** Playwright missing? Static scrape. Pipeline fails? Old behavior. Extraction finds nothing? Fallback text. Every component has a fallback path.

4. **Token-efficient.** Every token in the response should earn its place. Metadata is compact. Content is extracted, not dumped. ~1,000 tokens for 3 results.

5. **Testable in isolation.** Each quality module (QueryAnalyzer, ResultReranker, SnippetExtractor, QualityScorer) is independently testable with no external dependencies.
