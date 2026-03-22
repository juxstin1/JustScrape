# Requirements: JustScrape — God-Status Search Quality

**Defined:** 2026-03-21
**Core Value:** Return the exact relevant snippet, not just a page

## v1 Requirements

### Query Understanding

- [ ] **QUERY-01**: System classifies query intent (code, research, news, how-to, lookup, comparison)
- [ ] **QUERY-02**: System expands queries with synonyms, alternate phrasings, and abbreviation expansion
- [ ] **QUERY-03**: System decomposes complex multi-part questions into independent sub-queries
- [ ] **QUERY-04**: System detects entities in queries (library names, language names, version numbers)

### Relevance Ranking

- [ ] **RANK-01**: System scores search results by source authority (domain-based tier map, query-type aware)
- [ ] **RANK-02**: System applies freshness weighting for time-sensitive queries (date extraction + decay)
- [ ] **RANK-03**: System re-ranks results using neural cross-encoder semantic scoring (optional dependency)
- [ ] **RANK-04**: System preserves original search position as one signal in composite re-ranking

### Content Extraction

- [ ] **EXTRACT-01**: System extracts clean body text using trafilatura before snippet scoring
- [ ] **EXTRACT-02**: System chunks content into logical sections (headings, paragraphs, code blocks)
- [ ] **EXTRACT-03**: System scores each chunk against query and returns the most relevant snippet(s)
- [ ] **EXTRACT-04**: System uses sentence-level semantic matching to locate the exact answering passage

### Search Pipeline

- [ ] **PIPE-01**: System computes composite quality score (relevance + authority + freshness) for every result
- [ ] **PIPE-02**: System returns provenance metadata (source URL, type, date, confidence) alongside each result
- [ ] **PIPE-03**: System auto-reformulates and retries when results score below quality floor (max 3 attempts, 15s cap)
- [ ] **PIPE-04**: System deduplicates near-identical snippets from multiple sources before returning
- [ ] **PIPE-05**: System integrates all components into `search_and_scrape` without changing MCP tool signatures

## v2 Requirements

### Advanced Intelligence

- **ADV-01**: System supports multi-turn context awareness across MCP calls
- **ADV-02**: System builds persistent domain authority knowledge from usage patterns
- **ADV-03**: System provides configurable token budget for snippet extraction
- **ADV-04**: System supports structured answer extraction (API signatures, version numbers)

### Monitoring

- **MON-01**: System logs query classifications and reformulation attempts for quality tuning
- **MON-02**: System tracks per-backend health and auto-disables degraded backends
- **MON-03**: System monitors source adapter health and alerts on silent failures

## Out of Scope

| Feature | Reason |
|---------|--------|
| LLM-generated answer synthesis | Calling AI is already an LLM — JustScrape retrieves, not generates |
| Paid API integration | Must stay free per project constraint |
| Full-page vector indexing | Different product (knowledge base), massive storage complexity |
| Real-time crawling/spidering | Explodes latency and scope — use sitemap discovery instead |
| Custom fine-tuned models | Requires data/infrastructure beyond this milestone |
| Human-facing UI/CLI | AI-first, MCP-only focus |
| Architecture/packaging cleanup | Not touching plumbing per project scope |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| QUERY-01 | TBD | Pending |
| QUERY-02 | TBD | Pending |
| QUERY-03 | TBD | Pending |
| QUERY-04 | TBD | Pending |
| RANK-01 | TBD | Pending |
| RANK-02 | TBD | Pending |
| RANK-03 | TBD | Pending |
| RANK-04 | TBD | Pending |
| EXTRACT-01 | TBD | Pending |
| EXTRACT-02 | TBD | Pending |
| EXTRACT-03 | TBD | Pending |
| EXTRACT-04 | TBD | Pending |
| PIPE-01 | TBD | Pending |
| PIPE-02 | TBD | Pending |
| PIPE-03 | TBD | Pending |
| PIPE-04 | TBD | Pending |
| PIPE-05 | TBD | Pending |

**Coverage:**
- v1 requirements: 17 total
- Mapped to phases: 0
- Unmapped: 17

---
*Requirements defined: 2026-03-21*
*Last updated: 2026-03-21 after initial definition*
