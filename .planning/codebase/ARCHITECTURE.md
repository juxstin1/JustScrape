# Architecture

## Pattern

**Layered architecture** with a smart facade pattern. The codebase follows a progressively-capable scraping pipeline:

1. **MCP Server Layer** (`justscrape_mcp.py`) — Entry point exposing tools via Model Context Protocol
2. **Worker Layer** (`worker.py`) — CLI-oriented tool runner with classification engine
3. **Smart Facade** (`smart_scraper.py`) — Auto-selects best scraping method per URL
4. **Scraper Engines** (`web_scraper.py`, `js_scraper.py`, `async_scraper.py`) — Concrete implementations
5. **Support Systems** (`web_search.py`, `sitemap_registry.py`, `url_discovery.py`, `url_validator.py`) — Search, discovery, validation

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
User/AI → MCP Server (justscrape_mcp.py)
              ↓
         SmartScraper (smart_scraper.py)
              ↓
    ┌─────────┼─────────┐
    ↓         ↓         ↓
WebScraper  JsScraper  AsyncScraper
(static)    (browser)  (httpx/H2)
    ↓         ↓         ↓
    └─────────┼─────────┘
              ↓
     ScrapedContent → classify → return
```

**Search flow:**
```
web_search tool → WebSearch class (web_search.py)
                     ↓
              SearchBackend (backends/)
              ├── DuckDuckGo (default)
              ├── Brave (API key)
              └── SearXNG (self-hosted)
                     ↓
              SearchResponse → cache → return
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
