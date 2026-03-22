# Concerns

## Technical Debt

### No Packaging
- No `pyproject.toml`, `setup.py`, or `__init__.py` at root
- All modules at project root (flat layout)
- `sys.path` manipulation in `conftest.py` and `backends/base.py`
- Cannot be installed as a package or distributed via pip

### Duplicated Functionality
- Three scraper implementations (`web_scraper.py`, `js_scraper.py`, `async_scraper.py`) with overlapping concerns
- Two entry points (`justscrape_mcp.py`, `worker.py`) with different classification/handling logic
- `_restrict_file_permissions()` duplicated in `web_search.py`, `url_discovery.py`, `sitemap_registry.py`

### Global State
- Module-level mutable state: `_smart_scraper` global in `worker.py`
- `_domain_semaphores` dict in `async_scraper.py` (global, never fully cleaned)
- `RobotsCache._cache` class-level dict in `web_scraper.py`
- `LazyBrowserPool._instance` singleton

### No Configuration System
- All configuration is hardcoded constants at module level
- No `.env` loading, no config file parsing
- API keys (Brave) expected via environment variables but not documented in code

## Security

### Recent Fixes Applied
Recent commits show significant security work:
- SSRF protection via `url_validator.py` at SmartScraper entry points
- XXE protection via `defusedxml` for sitemap parsing
- SQLite safety improvements
- Input size limits on adapter responses
- File permission restrictions on SQLite databases

### Remaining Concerns
- `scrape_premium.py` (845 lines) — not inspected for SSRF validation coverage
- No Content Security Policy or output sanitization for scraped HTML
- SQLite databases created in working directory (portable path concerns)
- No authentication/authorization on MCP server

## Performance

### Potential Bottlenecks
- **Synchronous scraping in worker**: `ThreadPoolExecutor` but blocking `requests.get()` calls
- **Browser pool**: Single Playwright instance shared across all requests
- **SQLite contention**: Both search cache and sitemap registry use SQLite with threading
- **Rate limiter memory**: Per-domain rate limiter dicts grow unbounded (semaphores have cap, but lock dicts in `web_scraper.py` don't)

### Positive Patterns
- HTTP/2 multiplexing in async scraper
- HEAD pre-checks before full scraping
- 2-layer caching (memory + SQLite)
- Per-domain concurrency limits with eviction in async scraper

## Test Coverage Gaps

- `justscrape_mcp.py` — MCP server has no tests (815 lines)
- `scrape_premium.py` — No tests (845 lines)
- `js_scraper.py` — No direct tests (tested indirectly via smart_scraper)
- Integration/E2E testing absent (no tests that exercise full MCP → scrape → return flow)
- No CI/CD pipeline

## Fragile Areas

- **sys.path manipulation**: Breaks if directory structure changes
- **Lazy import pattern**: Import errors silently degrade to fallback mode — hard to debug
- **Domain-specific source adapters**: Hardcoded selectors/patterns in `smart_scraper.py` will break when sites change their HTML
- **Compiled regex patterns**: Large regex at module level (`BLOCKED_REGEX`, `JS_NEEDED_PATTERNS`) — failures are silent misses
