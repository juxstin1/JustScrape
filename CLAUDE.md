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
- `duckduckgo-search>=6.0.0` (installed: 8.1.1) - Primary search backend, no API key required
- `click>=8.1.0` - Interactive CLI in `scrape_premium.py`
- `defusedxml>=0.7.1` - Safe XML parsing in `sitemap_registry.py` (XXE protection)
- `python-dateutil>=2.8.0` - Date parsing
- `pyperclip>=1.8.0` - Optional clipboard support for CLI
- `pytest` (used in `tests/`) - No version pinned in `requirements.txt`
## Key Dependencies
- `mcp 1.26.0` - The entire server architecture; exposes tools via `mcp.server.Server` and `mcp.server.stdio.stdio_server`
- `playwright` - JS rendering falls back silently if not installed; Chromium binaries stored in `.playwright/` (gitignored, users install manually)
- `duckduckgo-search 8.1.1` - Only required external dependency for search; no API key
- `sqlite3` (stdlib) - Two SQLite databases for persistent caching: `~/.scraper_search_cache.db` (search results, 24 hr TTL) and `~/.scraper_sitemap_registry.db` (sitemaps)
- `httpx[http2]` - HTTP/2 multiplexing in `async_scraper.py` (separate from the sync `requests` usage)
## Configuration
- No `.env` file in use; no `python-dotenv` dependency
- `BRAVE_SEARCH_API_KEY` - Optional env var for Brave Search backend (`backends/brave.py`)
- SearXNG backend configured by instantiation (`SearXNGBackend(base_url="http://localhost:8080")`)
- User CLI preferences stored in `~/.scraper_config.json` (owner-only `0600` permissions)
- No build system; plain Python scripts, run directly
- Windows launcher: `scrape.bat` (activates `venv\Scripts\activate.bat`, runs `scrape_premium.py`)
- No `pyproject.toml`, no `setup.py`
## Platform Requirements
- Python 3.12+
- Optional: Playwright Chromium browsers (`playwright install chromium`)
- Optional: Node.js (for `justscrape-worker.js` client)
- Runs as an MCP stdio server; launched by Claude Desktop or any MCP-compliant host
- No web server, no ports, no Docker required
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

## Pattern
## Layers
### MCP Server (`justscrape_mcp.py` — 815 lines)
- Async MCP server using `mcp.server.Server`
- Exposes 4 tools: `web_search`, `scrape_url`, `search_and_scrape`, `extract_urls`
- 2-layer cache: in-memory L1 (5 min TTL) + SQLite L2 (24 hr)
- Lazy browser pool for JS rendering (`LazyBrowserPool` singleton)
- Per-domain rate limiting with exponential backoff
### Worker (`worker.py` — 517 lines)
- Standalone CLI worker with empirically-validated content classification
- Classification engine: `usable | thin | blocked | encoding-failure | empty`
- Pre-filters search results (skips known-blocked domains)
- Parallel scraping via `ThreadPoolExecutor`
### Smart Scraper (`smart_scraper.py` — 1189 lines)
- Facade that chooses static vs JS scraping automatically
- Multi-signal JS fallback detection (not just content length)
- Known JS-heavy domain list (Twitter, Reddit, YouTube, etc.)
- Source adapters: Wikipedia, GitHub, StackOverflow, YouTube, ArXiv, HackerNews
- URL validation via `url_validator.validate_url()` at entry points
### Static Scraper (`web_scraper.py` — 528 lines)
- requests + BeautifulSoup based extraction
- HEAD pre-check for content type/size
- Per-domain rate limiting with `threading.Lock`
- Robots.txt awareness with caching
- Content types: clean_text, full_html, structured, links, images, metadata
### JS Scraper (`js_scraper.py` — 308 lines)
- Playwright-based browser rendering
- Configurable resource blocking (ads, trackers)
- Wait-for-selector and timeout support
- Optional dependency (lazy import pattern)
### Async Scraper (`async_scraper.py` — 281 lines)
- httpx + HTTP/2 async alternative to `web_scraper.py`
- Per-domain concurrency semaphores (max 2 per domain, 10 global)
- Connection pooling
- Drop-in replacement for async contexts
## Data Flow
```
```
```
```
## Entry Points
- `justscrape_mcp.py` — Primary: MCP server for AI model integration
- `worker.py` — Secondary: CLI worker with classification
- `scrape_premium.py` — Alternative: premium scraping features (845 lines)
## Key Abstractions
- `ScrapedContent` dataclass — Universal scrape result container
- `SearchResponse` / `SearchResult` — Search result containers
- `SearchBackend` ABC — Pluggable search backend interface
- `MultiSearch` — Backend router (fallback or merge modes)
- `ContentType` enum — Extraction type selector
- `RobotsCache` — Per-domain robots.txt caching
- `LazyBrowserPool` — Thread-safe Playwright singleton
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
