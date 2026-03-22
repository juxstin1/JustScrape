# Coding Conventions

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
Used throughout to avoid hard dependency on Playwright:
```python
# In worker.py
_smart_scraper = None
def get_smart_scraper():
    global _smart_scraper
    if _smart_scraper is None:
        try:
            from smart_scraper import SmartScraper
            _smart_scraper = SmartScraper()
        except ImportError:
            _smart_scraper = "static_only"
    return _smart_scraper
```

### Thread-Safe Singleton (LazyBrowserPool)
```python
class LazyBrowserPool:
    _instance = None
    _lock = threading.Lock()
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
```

### Compiled Regex at Module Level
```python
BLOCKED_REGEX = re.compile('|'.join(BLOCKED_PATTERNS), re.IGNORECASE)
```

### Per-Domain Rate Limiting
Both sync (threading.Lock dict) and async (asyncio.Semaphore dict) variants with eviction caps.

### Streaming Response Pattern
```python
resp = requests.get(url, stream=True)
chunks = []
for chunk in resp.iter_content(chunk_size=8192):
    size += len(chunk)
    if size > MAX_SIZE:
        resp.close()
        return None
    chunks.append(chunk)
```

### Source Adapter Pattern (smart_scraper.py)
Specialized extraction for known domains (Wikipedia, GitHub, StackOverflow, etc.) with fallback to generic scraping.

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
