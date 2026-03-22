# Directory Structure

## Layout

```
JustScrape/
├── justscrape_mcp.py        # MCP server entry point (815 lines)
├── smart_scraper.py         # Smart facade + source adapters (1189 lines)
├── web_scraper.py           # Static scraper + robots.txt (528 lines)
├── js_scraper.py            # Playwright JS scraper (308 lines)
├── async_scraper.py         # httpx/HTTP2 async scraper (281 lines)
├── web_search.py            # Search + caching + rate limiting (1043 lines)
├── worker.py                # CLI worker + classification (517 lines)
├── scrape_premium.py        # Premium scraping features (845 lines)
├── url_discovery.py         # Link discovery system (328 lines)
├── url_validator.py         # SSRF protection (112 lines)
├── sitemap_registry.py      # SQLite sitemap storage (728 lines)
├── backends/                # Search backend plugins
│   ├── __init__.py          # Auto-discovers backends (28 lines)
│   ├── base.py              # SearchBackend ABC + MultiSearch (125 lines)
│   ├── duckduckgo.py        # DuckDuckGo adapter (43 lines)
│   ├── brave.py             # Brave Search adapter (114 lines)
│   └── searxng.py           # SearXNG adapter (111 lines)
├── tests/                   # Test suite
│   ├── conftest.py          # Path setup (7 lines)
│   ├── test_smart_scraper.py
│   ├── test_web_scraper.py
│   ├── test_async_scraper.py
│   ├── test_backends.py
│   ├── test_search_worker.py
│   ├── test_sitemap_registry.py
│   ├── test_url_discovery.py
│   ├── test_url_validator.py
│   ├── test_worker.py
│   └── test_xxe_protection.py
├── requirements.txt         # Python dependencies
├── mcp.json                 # MCP server configuration
├── scrape.bat               # Windows batch launcher
├── justscrape-worker.js     # Node.js worker wrapper
├── README.md                # Project documentation
├── UPGRADES.md              # Upgrade history
├── capabilities.md          # Feature capabilities doc
└── docs/
    └── superpowers/
        └── plans/           # Historical fix plans
```

## Key Locations

- **Entry points**: `justscrape_mcp.py` (MCP), `worker.py` (CLI)
- **Core scraping**: `smart_scraper.py`, `web_scraper.py`, `js_scraper.py`, `async_scraper.py`
- **Search**: `web_search.py`, `backends/`
- **Discovery**: `url_discovery.py`, `sitemap_registry.py`
- **Security**: `url_validator.py`
- **Tests**: `tests/`

## Naming Conventions

- **Files**: `snake_case.py` — flat module structure (no packages except `backends/`)
- **Classes**: `PascalCase` — `SmartScraper`, `WebScraper`, `SearchBackend`
- **Dataclasses**: `PascalCase` — `ScrapedContent`, `SearchResult`, `SearchResponse`
- **Constants**: `UPPER_SNAKE_CASE` — `BLOCKED_PATTERNS`, `MAX_ADAPTER_RESPONSE_SIZE`
- **Test files**: `test_<module>.py` matching source module names
- **Private helpers**: `_prefix` — `_safe_get()`, `_restrict_file_permissions()`

## Module Dependencies

```
justscrape_mcp.py → web_search, smart_scraper, url_validator
smart_scraper.py  → web_scraper, sitemap_registry, url_validator, js_scraper (lazy)
worker.py         → web_search, web_scraper, smart_scraper (lazy)
web_search.py     → (standalone, uses sqlite3)
async_scraper.py  → web_scraper (types), httpx (optional)
sitemap_registry.py → url_validator, defusedxml
url_discovery.py  → web_scraper
backends/*        → web_search (types)
```

## Notable Patterns

- **Flat module layout**: No `src/` directory, all modules at project root
- **Lazy imports**: JS scraper and SmartScraper imported lazily to avoid Playwright dependency
- **Optional deps**: httpx, playwright are optional; graceful degradation when missing
- **No packaging**: No `pyproject.toml` or `setup.py` — runs directly from directory
