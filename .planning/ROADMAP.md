# Roadmap: JustScrape — God-Status Search Quality

## Overview

Three phases transform JustScrape from a competent scraper into a search quality engine. Phase 1 builds three independent middleware components (query understanding, result re-ranking, snippet extraction) in isolation. Phase 2 wires them into the live pipeline, replaces the flawed relevance scorer, and ships structured MCP responses — this is when quality becomes user-visible. Phase 3 adds the optional neural re-ranking and reformulation-with-retry to reach the quality ceiling.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation Components** - Build QueryAnalyzer, ResultReranker, and SnippetExtractor as independently testable modules
- [ ] **Phase 2: Pipeline Integration** - Wire components into search pipeline, replace relevance scorer, ship structured MCP responses
- [ ] **Phase 3: Advanced Features** - Add neural re-ranking and intelligent retry with reformulation

## Phase Details

### Phase 1: Foundation Components
**Goal**: Three independently testable quality modules exist and are ready to be wired into the pipeline
**Depends on**: Nothing (first phase)
**Requirements**: QUERY-01, QUERY-02, QUERY-03, QUERY-04, RANK-01, RANK-02, EXTRACT-01, EXTRACT-02, EXTRACT-03, EXTRACT-04
**Success Criteria** (what must be TRUE):
  1. QueryAnalyzer correctly classifies a query's intent (code, research, news, how-to, lookup, comparison) and returns a confidence score; queries below 0.7 confidence default to "general"
  2. QueryAnalyzer produces expanded query variants (synonyms, alternate phrasings, abbreviations) and extracts named entities (library names, version numbers, language names) from a query
  3. QueryAnalyzer decomposes a multi-part question into independent sub-queries that can each be searched separately
  4. ResultReranker re-orders a list of search results by source authority tier (query-type aware) and freshness weight, returning results with scores and their original position preserved
  5. SnippetExtractor takes a scraped page, extracts clean body text via trafilatura, splits it into logical sections, scores each chunk against the query, and returns the highest-scoring chunk(s)
**Plans**: 3 plans
Plans:
- [x] 01-01-PLAN.md — QueryAnalyzer: intent classification, query expansion, decomposition, entity extraction
- [x] 01-02-PLAN.md — ResultReranker: authority scoring with per-query-type maps, freshness weighting
- [x] 01-03-PLAN.md — SnippetExtractor: trafilatura extraction, hybrid chunking, BM25+TF-IDF scoring, sentence matching

### Phase 2: Pipeline Integration
**Goal**: End-to-end improved search quality is live; `search_and_scrape` returns structured snippets with scores and provenance metadata without any change to MCP tool signatures
**Depends on**: Phase 1
**Requirements**: RANK-04, PIPE-01, PIPE-02, PIPE-04, PIPE-05
**Success Criteria** (what must be TRUE):
  1. Calling `search_and_scrape` routes through the full pipeline: QueryAnalyzer before search, ResultReranker before scraping, SnippetExtractor inside the scrape loop, QualityScorer for final sort
  2. Each result returned includes a composite quality score (relevance + authority + freshness + original position), source URL, inferred source type, detected date, and confidence — alongside the snippet
  3. Near-identical snippets from multiple sources are deduplicated before the response is returned
  4. The length-biased relevance scorer is replaced; short precise answers outrank long tangentially-relevant pages
  5. All existing MCP tool signatures are unchanged and all existing tests pass
**Plans**: 2 plans
Plans:
- [ ] 02-01-PLAN.md — QualityScorer: composite scoring (relevance + authority + freshness + position) and rapidfuzz dedup
- [ ] 02-02-PLAN.md — Pipeline wiring: integrate all components into handle_search_and_scrape with provenance metadata

### Phase 3: Advanced Features
**Goal**: Neural semantic re-ranking and intelligent reformulation-with-retry are available, with the reformulation loop protected by hard termination guards
**Depends on**: Phase 2
**Requirements**: RANK-03, PIPE-03
**Success Criteria** (what must be TRUE):
  1. When `sentence-transformers` is installed, results are re-ranked using a cross-encoder model; when it is absent, the system falls back to BM25/TF-IDF without error (same gating pattern as Playwright)
  2. When initial results score below the quality floor, the system automatically reformulates the query and retries, switching backends if DuckDuckGo returns consecutive zero-result responses
  3. Reformulation never exceeds 3 attempts and always terminates within 15 seconds total wall-clock time, regardless of backend behavior
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation Components | 2/3 | In Progress|  |
| 2. Pipeline Integration | 0/2 | Not started | - |
| 3. Advanced Features | 0/TBD | Not started | - |
