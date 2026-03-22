# Phase 1: Foundation Components - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Build three independently testable quality modules: QueryAnalyzer, ResultReranker, and SnippetExtractor. Each module is a standalone Python file with its own tests. They are NOT wired into the pipeline yet (that's Phase 2). This phase delivers three importable modules ready to integrate.

</domain>

<decisions>
## Implementation Decisions

### Intent Detection (QueryAnalyzer)
- **D-01:** Rules-only approach — pattern matching + keyword lists, zero ML dependencies. No spacy.
- **D-02:** Six intent categories: code, research, news, how-to, lookup, comparison. Each returns with a confidence score (0.0–1.0).
- **D-03:** When confidence < 0.7, classify as "general" and use wider-net mode (fetch more results — 10 instead of 5).
- **D-04:** Aggressive query expansion — abbreviations + alternate phrasings + related terms (e.g., "react hooks" also generates "react useState useEffect").
- **D-05:** Query decomposition triggers on conjunctions only — split on "and", "vs", "or", "compared to". Simple and predictable.
- **D-06:** Entity extraction via regex patterns — library names, language names, version numbers. No NLP dependency.

### Authority Tiers (ResultReranker)
- **D-07:** Five authority tiers: Authoritative (1.0) / Trusted (0.8) / Standard (0.5) / Low (0.2) / Blocked (0.0).
- **D-08:** Authority map is query-type-dependent — different maps for code, research, news, etc. (e.g., Stack Overflow = Authoritative for code, Standard for research).
- **D-09:** Freshness penalty applied ONLY to news/current-event queries. Docs and code don't age the same way — no decay for non-temporal queries.
- **D-10:** Curated domain blocklist — known SEO farms, content scrapers, low-quality aggregators always filtered out (score = 0.0, never scraped).
- **D-11:** Original search position preserved as one signal (will be used as ~15-20% weight in Phase 2's composite scorer).

### Snippet Extraction (SnippetExtractor)
- **D-12:** Hybrid chunking — split on headings (h1-h6) first, then split large sections into paragraphs. Keeps logical sections together while maintaining scoring granularity.
- **D-13:** Return top 2-3 best-scoring chunks per result. Not just 1, but not unlimited — covers multi-part answers.
- **D-14:** Blended scoring — BM25 + TF-IDF cosine averaged for better discrimination than either alone. Uses rank-bm25 + scikit-learn.
- **D-15:** Code blocks treated as atomic chunks — never split mid-code-block. Preserved whole and boosted when query has code intent.
- **D-16:** Trafilatura for clean text extraction before chunking. Replaces current BS4-based extraction for snippet use cases.

### Claude's Discretion
- Exact regex patterns for intent classification keywords
- Specific domains in each authority tier (initial set — can be tuned)
- BM25/TF-IDF weight blend ratio (50/50 is fine starting point)
- Chunk size threshold for splitting large heading-sections into paragraphs
- Test structure and fixture design

</decisions>

<specifics>
## Specific Ideas

- "Context7 level" — the benchmark is Context7's ability to find the exact documentation snippet from a vague query. Chunking + per-chunk scoring is the analog.
- Exa's `highlights` feature as model — locate query-relevant sentences within a document, not return the document.
- Tavily's structured metadata approach — every result has a relevance score alongside the content.
- The existing `relevance_score` function in `web_search.py` (line 482) has a 20% length weight that rewards long pages over precise answers — this is the anti-pattern to avoid.

</specifics>

<canonical_refs>
## Canonical References

No external specs — requirements are fully captured in decisions above.

### Research documents (inform implementation details)
- `.planning/research/STACK.md` — Library recommendations with versions and rationale
- `.planning/research/FEATURES.md` — Feature landscape, MVP priorities, competitor techniques
- `.planning/research/ARCHITECTURE.md` — Component boundaries, data flow, integration strategy
- `.planning/research/PITFALLS.md` — Critical pitfalls P2 (length-biased scoring), P5 (intent misclassification), P6 (wrong page region extraction), P10 (stop-word removal breaking code queries)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `web_search.py:relevance_score()` (line 460) — Current scoring logic. The TF and title-match components are reusable; the length weight must be removed/replaced.
- `web_search.py:SearchResult` dataclass — Can carry additional fields (authority_score, snippet) without breaking existing consumers.
- `smart_scraper.py:_try_source_adapter()` (line 91) — Domain detection pattern reusable for authority tier lookup.
- `worker.py:classify_content()` (line 74) — Content classification pattern (usable/thin/blocked) — similar approach works for query intent.
- `web_search.py:should_scrape()` — Existing pre-filter logic that can be extended with authority-based filtering.

### Established Patterns
- **Lazy import pattern** — Used for Playwright, should be used for scikit-learn and rank-bm25 (optional enhanced scoring).
- **Compiled regex at module level** — Used for BLOCKED_PATTERNS, JS_NEEDED_PATTERNS. Same pattern for intent classification keywords.
- **Dataclass containers** — `ScrapedContent`, `SearchResult`, `SearchResponse`. New modules should follow same pattern for `AnalyzedQuery`, `RankedResult`, `ExtractedSnippet`.
- **Per-domain maps** — `JS_HEAVY_DOMAINS` in smart_scraper.py. Same pattern for authority tier maps.

### Integration Points
- QueryAnalyzer will be called BEFORE `search_full()` in Phase 2
- ResultReranker will process `SearchResponse.results` list
- SnippetExtractor will process `ScrapedContent.content` strings
- All three modules are standalone in Phase 1 — no imports into existing code yet

</code_context>

<deferred>
## Deferred Ideas

- Wiring modules into the live pipeline — Phase 2
- Neural cross-encoder re-ranking — Phase 3
- Intelligent retry with reformulation — Phase 3
- Multi-source dedup — Phase 2 (PIPE-04)
- Composite quality scoring — Phase 2 (PIPE-01)

</deferred>

---

*Phase: 01-foundation-components*
*Context gathered: 2026-03-21*
