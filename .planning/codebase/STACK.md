# Technology Stack

**Analysis Date:** 2026-03-21

## Languages

**Primary:**
- Python 3.12 - All server logic, MCP tools, scrapers, search backends, CLI

**Secondary:**
- JavaScript (ES Modules) - Node.js client wrapper (`justscrape-worker.js`)

## Runtime

**Environment:**
- CPython 3.12 (confirmed installed: `python3 --version` → 3.12.3)

**Package Manager:**
- pip (virtual environment via `venv/` — gitignored)
- Lockfile: None (only `requirements.txt` with minimum versions)

## Frameworks

**Core:**
- `mcp>=1.0.0` (installed: 1.26.0) - Model Context Protocol SDK; exposes Python functions as LLM tools over stdio
- `asyncio` (stdlib) - Async event loop for concurrent scraping in the MCP server

**HTTP / Scraping:**
- `requests>=2.32.0` - Synchronous HTTP for static scraping and adapter requests
- `httpx[http2]>=0.27.0` - Async HTTP/2 client used in `async_scraper.py` for connection-pooled scraping
- `playwright>=1.40.0` - Headless Chromium for JS-heavy sites; lazy-initialized via `LazyBrowserPool` singleton
- `beautifulsoup4>=4.12.0` + `lxml>=4.9.1` - HTML parsing and content extraction

**Search:**
- `duckduckgo-search>=6.0.0` (installed: 8.1.1) - Primary search backend, no API key required

**CLI:**
- `click>=8.1.0` - Interactive CLI in `scrape_premium.py`

**Security:**
- `defusedxml>=0.7.1` - Safe XML parsing in `sitemap_registry.py` (XXE protection)

**Data:**
- `python-dateutil>=2.8.0` - Date parsing
- `pyperclip>=1.8.0` - Optional clipboard support for CLI

**Testing:**
- `pytest` (used in `tests/`) - No version pinned in `requirements.txt`

## Key Dependencies

**Critical:**
- `mcp 1.26.0` - The entire server architecture; exposes tools via `mcp.server.Server` and `mcp.server.stdio.stdio_server`
- `playwright` - JS rendering falls back silently if not installed; Chromium binaries stored in `.playwright/` (gitignored, users install manually)
- `duckduckgo-search 8.1.1` - Only required external dependency for search; no API key

**Infrastructure:**
- `sqlite3` (stdlib) - Two SQLite databases for persistent caching: `~/.scraper_search_cache.db` (search results, 24 hr TTL) and `~/.scraper_sitemap_registry.db` (sitemaps)
- `httpx[http2]` - HTTP/2 multiplexing in `async_scraper.py` (separate from the sync `requests` usage)

## Configuration

**Environment:**
- No `.env` file in use; no `python-dotenv` dependency
- `BRAVE_SEARCH_API_KEY` - Optional env var for Brave Search backend (`backends/brave.py`)
- SearXNG backend configured by instantiation (`SearXNGBackend(base_url="http://localhost:8080")`)
- User CLI preferences stored in `~/.scraper_config.json` (owner-only `0600` permissions)

**Build:**
- No build system; plain Python scripts, run directly
- Windows launcher: `scrape.bat` (activates `venv\Scripts\activate.bat`, runs `scrape_premium.py`)
- No `pyproject.toml`, no `setup.py`

## Platform Requirements

**Development:**
- Python 3.12+
- Optional: Playwright Chromium browsers (`playwright install chromium`)
- Optional: Node.js (for `justscrape-worker.js` client)

**Production:**
- Runs as an MCP stdio server; launched by Claude Desktop or any MCP-compliant host
- No web server, no ports, no Docker required
- Persistent cache files written to `~/` (home directory)

---

*Stack analysis: 2026-03-21*
