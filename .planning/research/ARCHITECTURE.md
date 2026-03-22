# Architecture Research: Intelligent Search Quality Pipeline

**Domain:** AI-powered search quality for MCP server
**Project:** JustScrape — search quality milestone
**Researched:** 2026-03-21
**Confidence:** HIGH (derived from direct codebase inspection)

---

## Current Pipeline (Integration Point)

The existing `handle_search_and_scrape` in `justscrape_mcp.py` already has a 4-step flow:

```
search → pre-filter → parallel scrape → sort by relevance_score → return
```

The intelligence layer inserts as middleware without touching MCP tool signatures.

Current `relevance_score` function (`0.45*tf + 0.35*title + 0.20*length`) is the target to replace — it runs on full page text which dilutes signal. Scoring on extracted snippets produces dramatically higher discrimination.

---

## Proposed Components

### 1. QueryAnalyzer
**Role:** Parse query intent, expand/rewrite query, classify query type
**Input:** Raw query string
**Output:** `AnalyzedQuery` (intent, query_type, expanded_queries, entities)

- Intent classification: lookup, how-to, comparison, current-event, code, research
- Keyword expansion: synonyms, abbreviations, alternate phrasings
- Entity extraction: library names, language names, version numbers
- Rule-based (no ML dependency) with optional spacy enhancement

### 2. ResultReranker
**Role:** Re-order search results before scraping based on authority + signals
**Input:** Search results + AnalyzedQuery
**Output:** Reranked results with authority scores

- Authority tier map: static dict mapping domains to 0.0–1.0 scores
- Query-type-aware: code queries boost docs/SO, news queries boost freshness
- Pre-scrape filtering: skip known-bad domains for this query type
- **Highest-leverage single addition** — better candidates get scraped first

### 3. SnippetExtractor
**Role:** Extract the specific relevant passage from scraped content
**Input:** Scraped page content + AnalyzedQuery
**Output:** Relevant snippet(s) with position and confidence

- Content chunking: split into logical sections (headings, paragraphs, code blocks)
- Per-chunk relevance scoring against original query
- Window-based extraction: return best chunk(s) within token budget
- Trafilatura for clean text extraction before chunking

### 4. QualityScorer
**Role:** Compute final composite quality score for each result
**Input:** Snippet + metadata + AnalyzedQuery
**Output:** Composite score (0.0–1.0) with breakdown

- Signals: snippet relevance, source authority, freshness, content length adequacy
- Query-type-aware weights (freshness matters for news, authority for code)
- Replaces current `relevance_score` in search_and_scrape flow

### 5. Synthesizer (Optional/Deferred)
**Role:** Combine snippets from multiple sources into coherent result set
**Input:** Scored snippets from multiple sources
**Output:** Deduplicated, ranked snippet collection

- Near-duplicate detection (rapidfuzz)
- Complementary information merging
- Source diversity enforcement (don't return 5 results from same domain)

---

## Data Flow

```
Query
  ↓
QueryAnalyzer → AnalyzedQuery (intent, type, expanded queries)
  ↓
WebSearch (existing) → raw SearchResults
  ↓
ResultReranker → reranked results (authority-scored, filtered)
  ↓
SmartScraper (existing) → scraped pages
  ↓
SnippetExtractor → relevant passages per page
  ↓
QualityScorer → scored results with metadata
  ↓
Synthesizer (optional) → deduplicated, diverse result set
  ↓
MCP Response (structured JSON with snippets + scores + provenance)
```

---

## Integration Strategy

**Key constraint:** No changes to MCP tool signatures. Intelligence is internal middleware.

### Where Components Hook In (`justscrape_mcp.py`)

1. **QueryAnalyzer** — called first in `handle_search_and_scrape`, before `search_full()`
2. **ResultReranker** — called after `search_full()`, before parallel scraping loop
3. **SnippetExtractor** — called inside scraping loop, after each page is fetched
4. **QualityScorer** — replaces current `relevance_score` sorting
5. **Synthesizer** — called after all results scored, before return

### What Stays Unchanged

- `web_search` MCP tool (no scraping involved) — keep current `relevance_score`
- `scrape_url` MCP tool (single URL) — no search pipeline
- `extract_urls` MCP tool — link extraction only
- All scraper engines (web_scraper, js_scraper, async_scraper) — transport layer unchanged

---

## Build Order

```
Phase 1: Foundation (can parallelize 1a, 1b, 1c)
  1a. QueryAnalyzer — intent classification + query expansion
  1b. ResultReranker — authority map + pre-scrape filtering
  1c. SnippetExtractor — chunking + per-chunk scoring

Phase 2: Integration
  2a. Wire components into handle_search_and_scrape
  2b. QualityScorer — composite scoring replacing relevance_score
  2c. Enhanced MCP response format (snippets + scores + metadata)

Phase 3: Advanced (deferred)
  3a. Synthesizer — multi-source dedup + diversity
  3b. Intelligent retry with reformulation
  3c. Neural re-ranking (sentence-transformers, optional dependency)
```

### Dependencies

- 1a, 1b, 1c are independent — can be built in parallel
- 2a depends on all of Phase 1
- 2b depends on 2a (needs wired pipeline to score)
- 2c depends on 2b (enhanced format needs scoring)
- Phase 3 depends on Phase 2 fully working

---

## Performance Impact

- All components are CPU heuristic/pattern-matching transforms
- Expected overhead: <100ms total added to a flow dominated by 1–5 second network I/O
- No LLM calls, no paid APIs needed
- Neural re-ranking (Phase 3) adds ~100ms for cross-encoder inference

---

## Open Questions

- What window size (in sentences) produces best snippet extraction quality? Needs empirical testing.
- Should expanded queries result in multiple parallel search calls or sequential fallback? Architecture supports both — defer to implementation.

---
*Researched: 2026-03-21*
