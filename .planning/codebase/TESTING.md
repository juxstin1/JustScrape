# Testing

## Framework

- **pytest** (no explicit config file found — runs with defaults)
- Test files in `tests/` directory
- `conftest.py` adds project root to `sys.path`

## Test Files

| File | Lines | What it tests |
|------|-------|---------------|
| `test_smart_scraper.py` | 286 | JS detection, fallback logic, source adapters, URL validation |
| `test_search_worker.py` | 375 | Worker classification, search integration, parallel scraping |
| `test_url_validator.py` | 178 | SSRF protection, IP validation, scheme blocking |
| `test_backends.py` | 110 | Search backend interface, MultiSearch routing |
| `test_xxe_protection.py` | 103 | XML entity injection protection |
| `test_sitemap_registry.py` | 114 | SQLite sitemap storage, URL discovery |
| `test_url_discovery.py` | 97 | Link discovery, junk URL filtering |
| `test_web_scraper.py` | 81 | Static scraper, content extraction |
| `test_worker.py` | 72 | Worker tool invocations |
| `test_async_scraper.py` | 56 | Async httpx scraper |
| **Total** | **1,472** | |

## Testing Patterns

### Monkeypatching
Tests use pytest's `monkeypatch` fixture extensively to stub HTTP responses:
```python
def test_scrape_falls_back_to_javascript_when_static_is_thin(monkeypatch):
    scraper = SmartScraper(min_content_length=200)
    monkeypatch.setattr(scraper.static_scraper, "scrape", lambda url, ct: static_result)
```

### Fake Objects
Custom fake classes for complex dependencies:
```python
class FakeJavaScriptScraper:
    def __enter__(self): return self
    def __exit__(self, *a): return None
    def scrape(self, url, content_types): ...
```

### No Fixtures (Minimal)
- `conftest.py` only does path setup
- No shared fixtures, factories, or test databases
- Each test creates its own instances

### Direct Unit Testing
Tests generally test individual functions/methods directly rather than integration flows:
```python
def test_is_js_heavy_site_detects_known_domains():
    scraper = SmartScraper()
    assert scraper._is_js_heavy_site("https://www.reddit.com/r/python")
```

## Coverage

- **Well-covered**: URL validation, SSRF protection, XXE protection, content classification
- **Moderately covered**: Smart scraper logic, search backends, sitemap registry
- **Lightly covered**: Async scraper, web scraper, worker CLI
- **Not covered**: `justscrape_mcp.py` (MCP server), `scrape_premium.py`, `js_scraper.py` directly

## Running Tests

```bash
pytest tests/
```

No CI/CD configuration found (no GitHub Actions, no tox, no Makefile).
