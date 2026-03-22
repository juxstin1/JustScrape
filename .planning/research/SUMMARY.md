# Project Research Summary

**Project:** JustScrape — AI-Powered Search Quality
**Domain:** Intelligent search retrieval pipeline for LLM consumption
**Researched:** 2026-03-21
**Confidence:** HIGH

## Executive Summary

JustScrape is being evolved from a competent web scraper into a search quality engine optimized for LLM callers — a category represented by Perplexity, Tavily, and Exa. The key insight from research is that the calling LLM already handles synthesis; JustScrape's job is to return the *right paragraph from the right page*, not a wall of raw HTML. This means the value chain is: understand the query → rank candidates intelligently before scraping → extract the specific answering passage → return structured snippets with scores and provenance. All of this can be done with free, open-source libraries and no paid APIs.

The recommended approach is a 3-phase middleware pipeline inserted into `handle_search_and_scrape` without touching MCP tool signatures. Phase 1 builds three independent components — QueryAnalyzer (intent + expansion), ResultReranker (authority-weighted pre-scrape filtering), and SnippetExtractor (trafilatura + chunked scoring) — that can be developed in parallel. Phase 2 wires them together, replaces the current length-biased relevance scorer, and upgrades the MCP response format to include snippets, scores, and metadata. Phase 3 adds neural re-ranking and intelligent retry as optional enhancements once the core pipeline is validated.

The primary risks center on feedback loops and silent failures: a query reformulation loop without termination guards will burn through backends indefinitely; DuckDuckGo rate-limits silently with `success=True`; and the existing source adapters for StackExchange, Reddit, and GitHub can break silently when sites change their HTML. All three are solvable with explicit caps, backend-switching logic, and minimum-content validation on adapter output.

---

## Key Findings

### Recommended Stack

The stack is intentionally lightweight. Most quality gains come from heuristic transforms, not large models. The dependency size hierarchy matters for deployment: `rank-bm25` is zero-dependency and always available; `scikit-learn` TF-IDF is the next tier; `sentence-transformers` with torch (~500MB–2GB) is optional and should be gated the same way Playwright currently is. `trafilatura` replaces BeautifulSoup for body extraction and is the single highest-ROI new dependency — benchmarks show it outperforms `newspaper3k` and `readability-lxml` on clean body text extraction. `spacy` + `en_core_web_sm` (12MB) enables entity-aware query classification. `rapidfuzz` handles near-duplicate deduplication at negligible cost.

**Core technologies:**
- `trafilatura >=1.8.0`: Clean body text extraction — replaces/supplements BS4 in `web_scraper.py`, prerequisite for snippet scoring
- `rank-bm25 >=0.2.2`: Lexical re-ranking fallback — zero dependencies, always available, baseline scoring
- `scikit-learn >=1.4.0`: TF-IDF cosine similarity — mid-tier fallback when torch unavailable
- `sentence-transformers >=2.7.0` (optional): Neural cross-encoder re-ranking via `cross-encoder/ms-marco-MiniLM-L-6-v2` — highest accuracy, optional dependency
- `spacy >=3.7.0` + `en_core_web_sm`: Query intent/entity detection — identifies code vs research vs news routing
- `rapidfuzz >=3.6.0`: Near-duplicate snippet deduplication — replaces unmaintained `fuzzywuzzy`

**Graceful degradation (matches Playwright pattern):**
1. Best: Neural cross-encoder (sentence-transformers + torch)
2. Good: TF-IDF cosine (scikit-learn)
3. Basic: BM25 lexical (rank-bm25) — always available

See `.planning/research/STACK.md` for full rationale and exclusions.

### Expected Features

The domain has clear table stakes — their absence makes results mediocre compared to Tavily/Exa. The MVP priority order below is informed by the feature dependency graph: intent classification unlocks downstream routing, so it must come first.

**Must have (table stakes):**
- Query intent classification — enables correct routing for all downstream features; without it a "how to" query gets the same treatment as a "what is" query
- Keyword expansion / query rewriting — highest ROI for DuckDuckGo quality; pure text manipulation, no ML required
- Relevance scoring on retrieved URLs — raw search engine rankings optimize for SEO signals, not AI consumption quality
- Content noise removal — the existing BS4 extraction needs query-aware paragraph scoring, not just tag stripping
- Snippet-level extraction — returning a 50KB page when one paragraph answers the question wastes LLM context window
- Thin/blocked content detection with multi-result fallback — partially present, needs to be systematic with scoring
- Source type awareness — code questions should prefer docs/SO; news questions should prefer recent sources

**Should have (competitive differentiators):**
- Semantic re-ranking (neural cross-encoder) — Exa's key differentiator; highest single-feature quality lift
- Freshness-aware ranking — apply only when query contains temporal markers
- Source authority scoring — domain scorelist per query type (docs.python.org = HIGH for Python queries)
- Result deduplication — URL normalization + content fingerprinting before returning
- Confidence/provenance signaling — return score + source URL + publication date alongside every snippet

**Defer (v2+):**
- Query decomposition for multi-part questions — significant complexity, only needed for conjunctive queries
- Intelligent retry with reformulation — requires full pipeline to be stable first; adds loop complexity (P1 pitfall)
- Synthesizer / multi-source merging — nice to have, not blocking quality

See `.planning/research/FEATURES.md` for full technique reference and how Perplexity, Tavily, Exa, and Context7 approach these features.

### Architecture Approach

The architecture inserts as middleware into the existing `handle_search_and_scrape` flow with no changes to MCP tool signatures. The existing 4-step flow (`search → pre-filter → parallel scrape → sort by relevance_score → return`) expands to a 7-step pipeline. The current `relevance_score` function (0.45*tf + 0.35*title + 0.20*length) is the explicit target to replace — its 20% length weight is P2 critical pitfall. All new components are CPU heuristic transforms; expected overhead is <100ms against a pipeline already dominated by 1–5 second network I/O.

**Major components:**
1. **QueryAnalyzer** — parses intent (lookup/how-to/comparison/current-event/code/research), expands query with synonyms and alternate phrasings, extracts entities (library names, version numbers). Rule-based core, optional spacy enhancement.
2. **ResultReranker** — re-orders search results before scraping using authority tier map + query-type-aware weights. Pre-scrape filtering skips known-bad domains per query type. Highest-leverage single addition — better candidates get scraped first.
3. **SnippetExtractor** — splits scraped content into logical sections (headings, paragraphs, code blocks), scores each chunk against query, returns best chunk(s) within token budget. Requires trafilatura for clean body text first.
4. **QualityScorer** — composites snippet relevance + source authority + freshness + content length into a single 0.0–1.0 score with breakdown. Replaces current `relevance_score`.
5. **Synthesizer** (optional/Phase 3) — near-duplicate detection, source diversity enforcement, complementary information merging.

See `.planning/research/ARCHITECTURE.md` for integration hooks and full build order.

### Critical Pitfalls

1. **Query reformulation loops without termination guards (P1)** — a retry loop with no max-attempts or quality-floor exits indefinitely on queries with no good results. Prevent with: hard cap at 3 reformulation attempts, quality floor exit at score >0.3, 15s total wall-clock cap.
2. **Relevance scoring that rewards length over relevance (P2)** — the current 20% length weight in `relevance_score` causes long tangentially-relevant pages to outrank short precise answers. Prevent by removing length weight and scoring on extracted snippet relevance, not full-page length.
3. **DuckDuckGo silent rate-limiting (P3)** — DDG returns `success=True` with `total_results=0` when rate-limited. A reformulation loop interprets this as "no results" and burns more queries against a throttled backend. Prevent by detecting 2+ consecutive zero-result responses and switching to SearXNG immediately.
4. **Source adapter silent failures (P4)** — StackExchange, Reddit, GitHub, and Wikipedia adapters use hardcoded selectors that break silently when sites change HTML. Prevent by validating minimum content length on adapter output and always having a generic fallback path.
5. **Query intent misclassification cascades (P5)** — a code query misclassified as "news" routes to news sources with freshness weights, degrading results across the full pipeline. Prevent with a confidence threshold (>0.7) before applying specialized routing; default to "general" when uncertain.

---

## Implications for Roadmap

Based on research, the architecture's own build order provides a clear phase structure. The three Phase 1 components are independent and can be built in parallel. Integration comes second. Advanced ML features come last as optional enhancements.

### Phase 1: Foundation Components (Parallelizable)

**Rationale:** QueryAnalyzer, ResultReranker, and SnippetExtractor have zero dependencies on each other and zero dependencies on existing code changes. They can be built and unit-tested in isolation before any integration. This is explicitly the recommended build order from architecture research.

**Delivers:** Three independently testable quality modules ready for wiring.

**Addresses (from FEATURES.md table stakes):**
- QueryAnalyzer: intent classification, keyword expansion
- ResultReranker: relevance scoring on retrieved URLs, source type awareness, authority scoring
- SnippetExtractor: snippet-level extraction, content noise removal (via trafilatura)

**Avoids (PITFALLS.md):**
- P5: intent classification with confidence threshold prevents misclassification cascades
- P10: query-type detection runs before any query rewriting (prevents stop-word removal breaking code queries)

**Research flag:** Standard patterns — well-documented text processing domain, no deeper research needed.

### Phase 2: Pipeline Integration

**Rationale:** Depends on all three Phase 1 components existing. Wires them into `handle_search_and_scrape`, replaces the P2 critical-pitfall `relevance_score`, and upgrades MCP response format. This is when quality improvements become user-visible.

**Delivers:** End-to-end improved search quality; structured MCP responses with snippets + scores + provenance metadata.

**Uses (from STACK.md):**
- `trafilatura` replacing BS4 in scraping loop
- `rank-bm25` or `scikit-learn` in QualityScorer (no torch dependency required at this phase)

**Implements (from ARCHITECTURE.md):**
- QualityScorer replacing `relevance_score`
- Wire order: QueryAnalyzer (before `search_full()`) → ResultReranker (before scrape loop) → SnippetExtractor (inside scrape loop) → QualityScorer (sort/return)
- Enhanced MCP response format (snippets, scores, source metadata)

**Avoids (PITFALLS.md):**
- P2: new QualityScorer removes length weight, scores on snippet relevance
- P4: SnippetExtractor includes minimum-content validation on adapter output
- P6: trafilatura body extraction runs before snippet scoring
- P7: original search position included as ~15-20% signal in QualityScorer

**Research flag:** Standard patterns — integration of existing components, no new domain research needed.

### Phase 3: Advanced Features (Deferred)

**Rationale:** Neural re-ranking, intelligent retry with reformulation, and multi-source synthesis all depend on a stable pipeline from Phase 2. Reformulation especially must be added only after termination guards are designed in from the start (P1 critical pitfall). Neural re-ranking adds the optional `sentence-transformers` dependency.

**Delivers:** Highest quality tier — semantic relevance, reformulation resilience, deduplicated multi-source synthesis.

**Uses (from STACK.md):**
- `sentence-transformers >=2.7.0` with `cross-encoder/ms-marco-MiniLM-L-6-v2` (optional, ~80MB model, requires torch)
- `rapidfuzz` for near-duplicate detection in Synthesizer

**Implements (from ARCHITECTURE.md):**
- Synthesizer (dedup + source diversity)
- Intelligent retry with reformulation (max 3 attempts, quality floor, 15s cap)
- Neural cross-encoder re-ranking (optional dependency, same gating as Playwright)

**Avoids (PITFALLS.md):**
- P1: reformulation loop MUST have hard cap (3 attempts), quality floor (>0.3), wall-clock timeout (15s)
- P3: backend-switching logic before reformulation — never reformulate against zero-result DDG, switch to SearXNG first
- P8: per-session Brave query budget (max 10/session, max 100/day)

**Research flag:** Phase 3 may benefit from empirical testing to determine optimal snippet window sizes and reformulation trigger thresholds — not documented externally, needs internal A/B testing.

### Phase Ordering Rationale

- Phase 1 before Phase 2: architectural dependency — can't wire what doesn't exist
- Phase 3 last: reformulation loops are a P1 critical pitfall that require a stable baseline before adding retry complexity; neural re-ranking adds a large optional dependency that should be validated against the heuristic baseline first
- Trafilatura is a Phase 1 dependency (SnippetExtractor requires it) but its integration into the main scraping path is a Phase 2 concern — clean separation
- The three Phase 1 components can be assigned to parallel tracks if developer capacity allows

### Research Flags

Phases needing deeper research during planning:
- **Phase 3 (Reformulation):** Optimal reformulation strategies (broader vs narrower vs different angle) are not well-documented externally. Needs empirical observation of DDG behavior under throttling to tune thresholds.
- **Phase 3 (Neural re-ranking):** Snippet window size for cross-encoder input quality is an open question noted in architecture research — needs empirical testing, not further research.

Phases with standard patterns (skip research-phase):
- **Phase 1:** Text processing, intent classification, BM25/TF-IDF — all well-documented with official library docs.
- **Phase 2:** Pipeline integration and composite scoring — standard patterns, codebase already understood.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All libraries are production-grade; versions confirmed; degradation strategy matches existing Playwright pattern |
| Features | HIGH | Based on direct analysis of Perplexity, Tavily, Exa, Context7 behavior; feature dependency graph is explicit |
| Architecture | HIGH | Derived from direct codebase inspection; integration hooks identified by line; build order validated against dependencies |
| Pitfalls | HIGH | P1–P4 derived from direct codebase analysis; P3 (DDG silent throttling) is a known documented behavior |

**Overall confidence:** HIGH

### Gaps to Address

- **Snippet window size:** Architecture research flags this as an open question — how many sentences constitute an optimal snippet for cross-encoder input. Resolve empirically during Phase 3 implementation, not pre-planning.
- **Reformulation trigger thresholds:** The quality floor (>0.3 stop reformulating) and consecutive zero-result count (2+ = throttle) are reasonable defaults but need validation against real DDG behavior. Treat as tunable parameters, not hardcoded constants.
- **Expanded query strategy:** Architecture notes that expanded queries could trigger multiple parallel search calls or sequential fallback — both are valid. Defer this decision to Phase 2 implementation when the tradeoff between latency and quality can be measured.
- **spacy as hard vs soft dependency:** Architecture treats spacy as optional enhancement to rule-based classification. Final decision on whether to require it or make it optional (like Playwright) should be made in Phase 1 implementation based on classification quality without it.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection (`justscrape_mcp.py`, `web_scraper.py`, `smart_scraper.py`) — architecture integration points, current relevance_score formula, existing adapter patterns
- `trafilatura` official documentation — extraction quality benchmarks vs newspaper3k and readability-lxml
- `sentence-transformers` official documentation — cross-encoder model selection, inference performance
- `rank-bm25` PyPI / documentation — BM25Okapi implementation, zero-dependency footprint
- `spacy` official documentation — `en_core_web_sm` model size and NER capability

### Secondary (MEDIUM confidence)
- Tavily API documentation / behavior analysis — structured result format, `search_depth: advanced`, relevance scoring approach
- Exa documentation — `highlights` parameter as analog for answer-focused snippet extraction
- Perplexity behavior analysis — multi-source retrieval, sub-query decomposition for complex questions
- Context7 documentation — token-budget-aware chunk scoring as analog for snippet extraction

### Tertiary (LOW confidence)
- DuckDuckGo silent throttling behavior — observed pattern, not officially documented; treat as empirical finding requiring validation
- Reformulation quality floor (0.3 threshold) — reasonable default from domain knowledge, not externally validated

---
*Research completed: 2026-03-21*
*Ready for roadmap: yes*
