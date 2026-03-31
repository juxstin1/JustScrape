# Changelog

All notable changes to JustScrape are documented here.

## [Unreleased]

## [2.0.1] — 2026-03-30

### Added
- **LM Studio-first MCP contract** — added `research_with_sources`, `retrieve_source`, and `search_sources` so clients see answer-oriented tools before the legacy aliases
- **Legacy shim bootstrap** — `justscrape_mcp.py` now loads the repo-local `.venv` site-packages in-process, which keeps LM Studio on one PID while still using the updated checkout

### Changed
- **Legacy tool guidance** — `web_search`, `scrape_url`, and `search_and_scrape` now return `usage_hint` and `search_loop_guard` metadata so models stop re-searching and start answering from retrieved sources
- **README install notes** — documented the refined tool surface and the LM Studio local development path that should be restarted and version-checked after upgrades

### Fixed
- **detected_date always None** — pipeline now passes parsed dates from reranker through to scored output instead of hardcoding None (3d5130a)
- **Playwright Chromium binary missing** — browsers weren't installed, causing silent fallback to static-only scraping on every JS-rendered page. Official docs pages returned "Loading..." or empty content while the authority reranker promoted them to the top — worst results ranked highest
- **LM Studio stale checkout drift** — local LM Studio entrypoints now forward into the active repo instead of running old copies from `C:\Users\Justin\justscrape` or `C:\Users\Justin\mcp\justscrape`
- **`trafilatura` import crash on `lxml` 6** — added `lxml_html_clean` so the extraction stack boots cleanly in fresh environments
- **Automated research chasing YouTube watch pages** — unsupported watch URLs are now classified as poor retrieval targets and skipped in the parallel research worker
- **Pipeline integration subprocesses using the wrong interpreter** — regression tests now shell out with `sys.executable` instead of a broken `python3` stub on Windows

## [2.0.0] — 2026-03-22

Complete rewrite of the search quality pipeline. JustScrape now returns the exact relevant snippet instead of dumping full pages.

### Added
- **Quality Pipeline** — full search_and_scrape flow: QueryAnalyzer → SearXNG → ResultReranker → Scrape + SnippetExtractor → QualityScorer → Dedup
- **QueryAnalyzer** (`query_analyzer.py`) — intent classification (code/news/research/how-to/lookup/comparison), query expansion, entity extraction, sub-query decomposition
- **ResultReranker** (`result_reranker.py`) — per-query-type authority scoring with 5-tier domain maps, freshness weighting for news, blocked domain filtering
- **SnippetExtractor** (`snippet_extractor.py`) — trafilatura content extraction, hybrid chunking, BM25 + TF-IDF relevance scoring, best-sentence extraction
- **QualityScorer** (`quality_scorer.py`) — composite scoring (relevance + authority + freshness + position), source type inference, rapidfuzz near-duplicate removal
- **SearXNG as sole search backend** — self-hosted Docker container aggregating Google + Bing + 70 engines. No rate limits, no API keys
- **Provenance metadata** on every result — source_type, detected_date, confidence, score_breakdown
- **Integration tests** (`tests/test_pipeline_integration.py`) — 10 tests covering full pipeline, backward compatibility, and fallback behavior
- **DEVELOPERS.md** — architecture guide, roadmap, contribution instructions
- **buildOrder.md** — prioritized fix plan from 3-team audit

### Changed
- **Content is now snippet-only** — returns extracted relevant chunks (~1,000 tokens) instead of full page dumps (~5,200 tokens). 77% token reduction.
- **Relevance scores jumped from ~0.29 to ~0.70** — plain text detection in snippet extractor was the biggest single improvement
- **Playwright fallback** — JS-heavy sites fall back to static scraping when Playwright unavailable instead of crashing silently
- **Input validation hardened** — all MCP tool handlers coerce bad types (int query, string num_results, etc.) instead of crashing
- **README rewritten** — explains what JustScrape actually does with a real example walkthrough

### Fixed

#### Wave 1 — Critical (crashes and security)
- **SSRF via redirect chain** — re-validate final URL after HTTP redirects in HEAD pre-check
- **scikit-learn missing from requirements.txt** — fresh installs crashed at import
- **No size cap on static GET** — streaming with 10MB cap prevents OOM on large pages
- **robots.txt thread hang** — fetch outside lock with 3s timeout and 24hr TTL
- **NaN propagation from BM25** — guard against NaN/Inf in scoring prevents JSON serialization crash

#### Wave 2 — Quality (wrong results)
- **Plain text passed as HTML to trafilatura** — detect already-extracted text and skip HTML parsing. Single biggest quality improvement.
- **"current" misclassified as news** — "current working directory python" no longer gets news intent
- **Fuzzy date parser read version numbers as dates** — "Python 3.12" no longer parsed as March 12
- **ccTLD authority lookup failed** — bbc.co.uk now correctly matches authority tiers
- **Duplicate URLs from SearXNG** — deduplicate before scraping
- **Fallback re-searched unnecessarily** — reuses cached search result
- **Empty results returned success:true** — adds note field when all results filtered
- **Empty snippets collapsed by dedup** — skip dedup for empty snippet_text
- **Raw JavaScript returned as content** — detect JS indicators and return empty instead
- **30-day freshness score cliff** — redistribute weight when freshness is exactly 0.0

#### Wave 3 — Security hardening
- **Search operator injection** — sanitize site/filetype/exclude_sites to alphanumeric only
- **Cache poisoning** — validate URLs when serving from cache
- **SearXNG URL validation** — reject non-http(s) schemes at startup
- **extract_urls error leak** — sanitize exception messages, log to stderr
- **Case-insensitive abbreviation expansion** — "js", "ml", "ai" now expand correctly

#### Wave 4 — Polish
- **Semaphore held across CPU work** — release after network I/O, before snippet extraction
- **docs. false positives** — startswith instead of substring match
- **Dead code removed** — unused search_result_dict parameter
- **Confidence saturation** — reduced baseline from +0.3 to +0.1
- **exclude_sites type checking** — coerce elements to strings
- **Playwright timeout** — 15s domcontentloaded instead of 30s networkidle

### Removed
- **DuckDuckGo as search backend** — unreliable, rate-limited, returns empty results. SearXNG replaces it entirely.
- **Brave Search references** — no paid APIs

### Dependencies Added
- `scikit-learn>=1.3.0` — TF-IDF vectorization in SnippetExtractor
- `trafilatura>=2.0.0` — content extraction
- `rank-bm25>=0.2.2` — BM25 relevance scoring
- `rapidfuzz>=3.0.0` — near-duplicate detection

### Infrastructure
- **SearXNG Docker container** required — `sudo docker run -d --name searxng -p 8080:8080 -v ~/searxng/settings.yml:/etc/searxng/settings.yml searxng/searxng`
- **215 tests passing** across 16 test files

---

## [1.0.0] — Pre-2026

Original JustScrape: MCP server with DuckDuckGo search, static + JS scraping, relevance scoring by content length. Functional but returned full page dumps and scored by length bias.
