<!-- GSD:project-start source:PROJECT.md -->
## Project

**JustScrape — God-Status Web Search for AI**

JustScrape is an MCP server that gives AI models (Claude, GPT, etc.) web search and scraping capabilities. The goal is to make it the best free web search tool for AI — better results than Perplexity, Tavily, or Exa, without requiring paid API keys. When an AI calls `search_and_scrape`, it should get back exactly the relevant snippet it needs, not a wall of scraped text or irrelevant pages.

**Core Value:** **Return the exact relevant snippet, not just a page.** Every search should deliver precisely what the AI needs to answer the user's question — the right source, the right section, clean and ready to use.

### Constraints

- **Cost**: No paid APIs — all search and scraping must use free sources
- **Interface**: MCP protocol — all improvements surface through existing/new MCP tools
- **Scope**: Search quality only — no architecture refactoring, no packaging changes
- **Compatibility**: Must maintain backward compatibility with existing MCP tool signatures
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.12 - All server logic, MCP tools, scrapers, search backends, CLI
- JavaScript (ES Modules) - Node.js client wrapper (`justscrape-worker.js`)
## Runtime
- CPython 3.12 (confirmed installed: `python3 --version` → 3.12.3)
- pip (virtual environment via `venv/` — gitignored)
- Lockfile: None (only `requirements.txt` with minimum versions)
## Frameworks
- `mcp>=1.0.0` (installed: 1.26.0) - Model Context Protocol SDK; exposes Python functions as LLM tools over stdio
- `asyncio` (stdlib) - Async event loop for concurrent scraping in the MCP server
- `requests>=2.32.0` - Synchronous HTTP for static scraping and adapter requests
- `httpx[http2]>=0.27.0` - Async HTTP/2 client used in `async_scraper.py` for connection-pooled scraping
- `playwright>=1.40.0` - Headless Chromium for JS-heavy sites; lazy-initialized via `LazyBrowserPool` singleton
- `beautifulsoup4>=4.12.0` + `lxml>=4.9.1` - HTML parsing and content extraction
- `trafilatura>=2.0.0` - Content extraction for snippet scoring in SnippetExtractor
- `rank-bm25>=0.2.2` - BM25 relevance scoring in SnippetExtractor
- `rapidfuzz>=3.0.0` - Near-duplicate detection in QualityScorer dedup
- `scikit-learn>=1.0.0` - TF-IDF vectorization in SnippetExtractor
- `click>=8.1.0` - Interactive CLI in `scrape_premium.py`
- `defusedxml>=0.7.1` - Safe XML parsing in `sitemap_registry.py` (XXE protection)
- `python-dateutil>=2.8.0` - Date parsing
- `pyperclip>=1.8.0` - Optional clipboard support for CLI
- `pytest` (used in `tests/`) - No version pinned in `requirements.txt`
## Key Dependencies
- `mcp 1.26.0` - The entire server architecture; exposes tools via `mcp.server.Server` and `mcp.server.stdio.stdio_server`
- `playwright` - JS rendering falls back silently if not installed; Chromium binaries stored in `.playwright/` (gitignored, users install manually)
- `SearXNG` (Docker) - Self-hosted meta-search engine; aggregates Google, Bing, 70+ engines; the only search backend
- `sqlite3` (stdlib) - Two SQLite databases for persistent caching: `~/.scraper_search_cache.db` (search results, 24 hr TTL) and `~/.scraper_sitemap_registry.db` (sitemaps)
- `httpx[http2]` - HTTP/2 multiplexing in `async_scraper.py` (separate from the sync `requests` usage)
## Configuration
- No `.env` file in use; no `python-dotenv` dependency
- SearXNG backend at `http://localhost:8080` (configurable via `SEARXNG_URL` env var)
- SearXNG config at `~/searxng/settings.yml` (mounted into Docker container)
- User CLI preferences stored in `~/.scraper_config.json` (owner-only `0600` permissions)
- No build system; plain Python scripts, run directly
- Windows launcher: `scrape.bat` (activates `venv\Scripts\activate.bat`, runs `scrape_premium.py`)
- No `pyproject.toml`, no `setup.py`
## Platform Requirements
- Python 3.12+
- Optional: Playwright Chromium browsers (`playwright install chromium`)
- Optional: Node.js (for `justscrape-worker.js` client)
- Runs as an MCP stdio server; launched by Claude Desktop or any MCP-compliant host
- Docker required for SearXNG search backend (`sudo docker start searxng`)
- Persistent cache files written to `~/` (home directory)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Code Style
- **Python 3.x** with type hints (typing module)
- **Dataclasses** for data containers (`ScrapedContent`, `SearchResult`, `SearchResponse`)
- **Enums** for type-safe options (`ContentType`)
- **ABCs** for interfaces (`SearchBackend`)
- **No formatter/linter config** found (no ruff, black, flake8 configs)
- **Docstrings**: Module-level docstrings on all files; class/method docstrings inconsistent
## Naming
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private: `_prefix` for internal helpers
- Regex patterns: `UPPER_SNAKE_CASE` compiled at module level
## Patterns
### Lazy Import Pattern
### Thread-Safe Singleton (LazyBrowserPool)
### Compiled Regex at Module Level
### Per-Domain Rate Limiting
### Streaming Response Pattern
### Source Adapter Pattern (smart_scraper.py)
## Error Handling
- **Try/except with fallback**: Most scraping operations wrap in try/except, return None or degraded result
- **Classification over booleans**: Worker uses explicit status classification (`usable | thin | blocked | encoding-failure | empty`) instead of boolean success
- **Graceful degradation**: Missing optional deps (httpx, playwright) cause fallback to simpler methods, not crashes
- **No custom exception hierarchy**: Uses built-in exceptions only
## Import Style
- Standard library first, then third-party, then local modules
- Relative imports not used (flat module structure)
- `conftest.py` adds project root to `sys.path` for tests
- `backends/base.py` also manipulates `sys.path` for project root access
## Configuration
- No config files (no `.env`, no YAML/TOML config)
- Constants defined at module level
- MCP config in `mcp.json`
- API keys expected via environment variables (Brave Search)
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Quality Pipeline (search_and_scrape)
The core pipeline that runs when an AI calls `search_and_scrape`:
1. **QueryAnalyzer** (`query_analyzer.py`) — intent classification, query expansion, entity extraction
2. **SearXNG** (`web_search.py` → `backends/searxng.py`) — self-hosted meta-search, Google + Bing + 70 engines
3. **ResultReranker** (`result_reranker.py`) — per-query-type authority scoring, freshness weighting
4. **Parallel scrape + SnippetExtractor** (`snippet_extractor.py`) — trafilatura extraction, BM25+TF-IDF chunk scoring
5. **QualityScorer** (`quality_scorer.py`) — composite scoring (relevance + authority + freshness + position)
6. **Dedup** (`quality_scorer.deduplicate_results`) — rapidfuzz near-duplicate removal

Content returned is only the relevant extracted chunks (~1,000 tokens), not the full page (~5,000+ tokens).

## Layers
### MCP Server (`justscrape_mcp.py`)
- Async MCP server using `mcp.server.Server`
- Exposes 4 tools: `web_search`, `scrape_url`, `search_and_scrape`, `extract_urls`
- `search_and_scrape` runs the full quality pipeline with graceful fallback
- 2-layer cache: in-memory L1 (5 min TTL) + SQLite L2 (24 hr)
- Lazy browser pool for JS rendering (`LazyBrowserPool` singleton)
- Per-domain rate limiting with exponential backoff
### Quality Modules
- `query_analyzer.py` — `AnalyzedQuery` dataclass with intent, confidence, expanded queries, entities
- `result_reranker.py` — `RankedResult` dataclass with authority/freshness scores, `AUTHORITY_TIERS` per query type
- `snippet_extractor.py` — `ExtractedSnippet` dataclass with BM25+TF-IDF score, best_sentence
- `quality_scorer.py` — `ScoredResult` dataclass with composite score, provenance metadata, dedup function
### Search (`web_search.py`)
- Single backend: self-hosted SearXNG at `SEARXNG_URL` (default `http://localhost:8080`)
- 2-layer cache with query operator support (site:, filetype:, date range)
- Returns `SearchResponse` / `SearchResult` dataclasses
### Scrapers
- `smart_scraper.py` — Facade: static vs JS auto-routing, source adapters (Wikipedia, GitHub, SO, etc.)
- `web_scraper.py` — Static: requests + BeautifulSoup, HEAD pre-check, robots.txt, rate limiting
- `async_scraper.py` — Async: httpx + HTTP/2, per-domain semaphores, connection pooling
- `js_scraper.py` — Browser: Playwright (optional dep), resource blocking, wait-for-selector
## Cross-Cutting Concerns
- **SSRF Protection**: `url_validator.py` validates all outbound URLs
- **Rate Limiting**: Per-domain in both sync and async scrapers
- **Caching**: 2-layer (memory + SQLite) in MCP server, per-domain in search
- **XML Security**: `defusedxml` used for sitemap parsing (XXE protection)
- **File Permissions**: `_restrict_file_permissions()` on SQLite DBs
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
