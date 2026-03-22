# External Integrations

**Analysis Date:** 2026-03-21

## APIs & External Services

**Search Engines:**

- **DuckDuckGo** - Primary search backend, no API key required
  - SDK/Client: `duckduckgo-search` (PyPI package, v8.1.1 installed)
  - Auth: None
  - Used in: `web_search.py` (`WebSearch` class), `backends/duckduckgo.py` (`DuckDuckGoBackend`)
  - Default for all `web_search`, `search_and_scrape`, and `research_with_sources` tool calls

- **Brave Search API** - Optional secondary backend (free tier: 2,000 queries/month)
  - SDK/Client: `requests` (direct REST call to `https://api.search.brave.com/res/v1/web/search`)
  - Auth: `BRAVE_SEARCH_API_KEY` environment variable
  - Used in: `backends/brave.py` (`BraveSearchBackend`)
  - Only activates when `BRAVE_SEARCH_API_KEY` is set; `is_available()` returns False otherwise

- **SearXNG** - Optional self-hosted meta-search backend (no external API)
  - SDK/Client: `requests` (direct REST to configurable `base_url`, default `http://localhost:8080`)
  - Auth: None (self-hosted)
  - Used in: `backends/searxng.py` (`SearXNGBackend`)
  - Availability checked via `GET /config`; fails gracefully if instance unreachable

**Multi-Backend Router:**
- `backends/base.py` (`MultiSearch`) - Routes queries across backends with "fallback" or "merge" modes
- Default mode is "fallback": tries DuckDuckGo first, then Brave, then SearXNG

## Data Storage

**Databases:**

- **SQLite (search cache)** - Persistent L2 cache for search results
  - Connection: Hardcoded path `~/.scraper_search_cache.db`
  - Client: `sqlite3` (stdlib); WAL mode enabled
  - TTL: 24 hours; auto-cleanup on write
  - File permissions: `0600` (owner-only) enforced on Unix
  - Managed by: `web_search.py` (`PersistentSearchCache`)

- **SQLite (sitemap registry)** - Persistent sitemap and URL storage
  - Connection: Hardcoded path `~/.scraper_sitemap_registry.db`
  - Client: `sqlite3` (stdlib); WAL mode enabled
  - File permissions: `0600` (owner-only) enforced on Unix
  - Managed by: `sitemap_registry.py` (`SitemapRegistry`)

**In-Memory Cache:**
- L1 TTL cache for search results (5 min TTL, max 100 entries)
- Managed by: `web_search.py` (`SearchCache`)
- Thread-safe via `threading.Lock`

**File Storage:**
- User CLI config: `~/.scraper_config.json` (output dir prefs, format prefs)
- Scraped output saved to `~/Downloads/scraped/` by default (CLI only, configurable)
- No cloud file storage

**Caching:**
- Two-layer cache: in-memory (L1) + SQLite (L2) for search results
- No external caching service (Redis, Memcached, etc.)

## Authentication & Identity

**Auth Provider:**
- None — no user authentication, no sessions, no identity management
- Brave Search: API key via env var `BRAVE_SEARCH_API_KEY`
- All other integrations are unauthenticated or self-hosted

## Web Scraping Targets (Outbound)

**Chromium / Playwright:**
- Used for JS-heavy sites: `twitter.com`, `x.com`, `reddit.com`, `youtube.com`, `instagram.com`, `facebook.com`, `linkedin.com`, `medium.com`, `substack.com`, `discord.com`
- Pooled in `LazyBrowserPool` singleton (initialized on first JS scrape request)
- Isolated per-request browser contexts prevent cookie/storage leakage
- Tracking/ad domains are aborted at network level (Google Analytics, DoubleClick, Facebook pixel, Twitter ads)

**Static HTTP:**
- `requests` library for synchronous scraping (`web_scraper.py`)
- `httpx[http2]` for async scraping (`async_scraper.py`)
- Robots.txt fetched and cached per domain (`web_scraper.py` `RobotsCache`)
- HEAD pre-check before full scrape to skip non-HTML or oversized responses
- Per-domain rate limiting with exponential backoff (max 30s delay)

**Sitemap Discovery:**
- `sitemap_registry.py` fetches `sitemap.xml` / sitemap index files via `requests`
- Max sitemap size: 50 MB; max child sitemaps: 100
- XML parsed via `defusedxml` (XXE-safe)

## SSRF Protection

**URL Validator:**
- All outbound HTTP requests pass through `url_validator.validate_url()` (`url_validator.py`)
- Blocks: non-http/https schemes, private/loopback/link-local IP ranges, cloud metadata endpoints (`metadata.google.internal`, `metadata.goog`)
- Applied at: `justscrape_mcp.py` (scrape_url, extract_urls entry points), `smart_scraper.py` (`PooledSmartScraper.scrape()`), `sitemap_registry.py`

## Monitoring & Observability

**Error Tracking:**
- None — errors logged to `stderr` only (`print(..., file=sys.stderr)`)
- No Sentry, Datadog, or equivalent

**Logs:**
- Stderr only; format: `[justscrape] Tool '{name}' error: {e}`
- No structured logging, no log files

## CI/CD & Deployment

**Hosting:**
- MCP stdio server: launched by Claude Desktop via `python justscrape_mcp.py`
- No deployment infrastructure; no Docker, no cloud hosting

**CI Pipeline:**
- None detected (no GitHub Actions, no CI config files)

## Environment Configuration

**Required env vars:**
- None (fully functional with no env vars using DuckDuckGo)

**Optional env vars:**
- `BRAVE_SEARCH_API_KEY` - Enables Brave Search backend

**Secrets location:**
- `.env` is gitignored but not used at runtime
- API key read directly from `os.environ.get("BRAVE_SEARCH_API_KEY", "")` in `backends/brave.py`

## Webhooks & Callbacks

**Incoming:**
- None — MCP server communicates only via stdin/stdout

**Outgoing:**
- None — all network calls are client-initiated HTTP GET requests to search APIs and scraped URLs

---

*Integration audit: 2026-03-21*
