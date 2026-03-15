# P0 Security Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 4 P0-critical issues: SSRF URL validation (#3, #4), XXE protection (#5), and Python 3.12+ compatibility (#6).

**Architecture:** Create a centralized `url_validator.py` module called by all entry points. Replace `xml.etree.ElementTree` with `defusedxml`. Replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()`.

**Tech Stack:** Python stdlib (`ipaddress`, `socket`, `urllib.parse`), `defusedxml` library

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `url_validator.py` | **Create** | Centralized URL validation — scheme checks, private IP blocking, post-redirect validation |
| `justscrape_mcp.py` | **Modify** | Add URL validation in tool handlers, fix `asyncio.get_event_loop()` (4 locations) |
| `web_scraper.py` | **Modify** | Add URL validation before `session.get()` |
| `async_scraper.py` | **Modify** | Add URL validation before `client.get()` |
| `smart_scraper.py` | **Modify** | Add URL validation in source adapters before `requests.get()` |
| `sitemap_registry.py` | **Modify** | Replace `ET.fromstring` with `defusedxml`, add URL validation for sitemap/child URLs, cap child sitemaps |
| `js_scraper.py` | **Modify** | Add URL scheme validation before `page.goto()` |
| `requirements.txt` | **Modify** | Add `defusedxml>=0.7.1` |
| `tests/test_url_validator.py` | **Create** | Tests for URL validation module |
| `tests/test_xxe_protection.py` | **Create** | Tests for XXE/XML bomb protection |

---

## Chunk 1: URL Validator Module + Tests

### Task 1: Create `url_validator.py` with tests

**Files:**
- Create: `url_validator.py`
- Create: `tests/test_url_validator.py`

- [ ] **Step 1: Write failing tests for URL validation**

```python
# tests/test_url_validator.py
import pytest
from url_validator import validate_url, is_safe_url

class TestValidateUrl:
    """Tests for centralized URL validation."""

    def test_allows_http(self):
        ok, reason = validate_url("http://example.com")
        assert ok is True

    def test_allows_https(self):
        ok, reason = validate_url("https://example.com/page")
        assert ok is True

    def test_blocks_file_scheme(self):
        ok, reason = validate_url("file:///etc/passwd")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_data_scheme(self):
        ok, reason = validate_url("data:text/html,<script>alert(1)</script>")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_javascript_scheme(self):
        ok, reason = validate_url("javascript:alert(1)")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_ftp_scheme(self):
        ok, reason = validate_url("ftp://example.com/file")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_no_scheme(self):
        ok, reason = validate_url("example.com")
        assert ok is False
        assert "blocked_scheme" in reason

    def test_blocks_loopback_ipv4(self):
        ok, reason = validate_url("http://127.0.0.1/admin")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_loopback_localhost(self):
        ok, reason = validate_url("http://localhost:8080/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_private_10(self):
        ok, reason = validate_url("http://10.0.0.1/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_private_172(self):
        ok, reason = validate_url("http://172.16.0.1/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_private_192(self):
        ok, reason = validate_url("http://192.168.1.1/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_aws_metadata(self):
        ok, reason = validate_url("http://169.254.169.254/latest/meta-data/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_ipv6_loopback(self):
        ok, reason = validate_url("http://[::1]/")
        assert ok is False
        assert "private_ip" in reason

    def test_blocks_empty_url(self):
        ok, reason = validate_url("")
        assert ok is False

    def test_blocks_none_url(self):
        ok, reason = validate_url(None)
        assert ok is False

    def test_is_safe_url_convenience(self):
        assert is_safe_url("https://example.com") is True
        assert is_safe_url("file:///etc/passwd") is False
        assert is_safe_url("http://127.0.0.1") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\Justin\JustScrape && python -m pytest tests/test_url_validator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'url_validator'`

- [ ] **Step 3: Implement `url_validator.py`**

```python
"""
Centralized URL validation for SSRF protection.

All outbound HTTP requests MUST pass through validate_url() before execution.
Blocks private IPs, non-HTTP schemes, and known-dangerous endpoints.
"""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple

# Schemes allowed for outbound requests
ALLOWED_SCHEMES = {'http', 'https'}

# Known metadata endpoints to block even if DNS resolves to public IP
BLOCKED_HOSTNAMES = {
    'metadata.google.internal',
    'metadata.goog',
}


def validate_url(url: str) -> Tuple[bool, str]:
    """
    Validate that a URL is safe for outbound HTTP requests.

    Checks:
    1. URL is non-empty and parseable
    2. Scheme is http or https
    3. Hostname does not resolve to private/loopback/link-local IP
    4. Hostname is not a known cloud metadata endpoint

    Returns:
        (is_safe, reason) — reason is "ok" if safe, or a description of why it was blocked.
    """
    if not url or not isinstance(url, str):
        return False, "empty_or_invalid_url"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "url_parse_error"

    # Check scheme
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return False, f"blocked_scheme:{scheme or 'none'}"

    hostname = parsed.hostname
    if not hostname:
        return False, "no_hostname"

    # Check known blocked hostnames
    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        return False, f"blocked_hostname:{hostname_lower}"

    # Resolve hostname and check all IPs
    try:
        # Try parsing as IP literal first (avoids DNS lookup)
        try:
            ip = ipaddress.ip_address(hostname)
            if _is_dangerous_ip(ip):
                return False, f"private_ip:{ip}"
            return True, "ok"
        except ValueError:
            pass  # Not an IP literal, resolve via DNS

        # DNS resolution — check all returned addresses
        port = parsed.port or (443 if scheme == 'https' else 80)
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)

        if not addr_infos:
            return False, "dns_no_results"

        for family, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if _is_dangerous_ip(ip):
                return False, f"private_ip:{ip}"

    except socket.gaierror:
        return False, "dns_resolution_failed"
    except Exception:
        return False, "ip_check_error"

    return True, "ok"


def _is_dangerous_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address is private, loopback, link-local, or otherwise dangerous."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def is_safe_url(url: str) -> bool:
    """Convenience wrapper — returns True if URL passes validation."""
    ok, _ = validate_url(url)
    return ok


def validate_url_or_raise(url: str) -> str:
    """Validate URL, raising ValueError if unsafe. Returns the URL if safe."""
    ok, reason = validate_url(url)
    if not ok:
        raise ValueError(f"URL blocked: {reason}")
    return url
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\Justin\JustScrape && python -m pytest tests/test_url_validator.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add url_validator.py tests/test_url_validator.py
git commit -m "feat: add centralized URL validator for SSRF protection (fixes #3)"
```

---

## Chunk 2: Wire URL Validation Into All Entry Points

### Task 2: Add validation to MCP tool handlers + fix asyncio

**Files:**
- Modify: `justscrape_mcp.py`

- [ ] **Step 1: Add `validate_url` import and call in `handle_scrape_url`**

At top of file, add import. In `handle_scrape_url`, validate before scraping.
In `handle_extract_urls`, validate before extracting.
Replace all 4 `asyncio.get_event_loop()` calls with `asyncio.get_running_loop()`.

- [ ] **Step 2: Add URL scheme validation before Playwright `page.goto()`**

In `_scrape_with_pooled_browser`, validate URL before `page.goto()`.

- [ ] **Step 3: Run existing tests**

Run: `cd C:\Users\Justin\JustScrape && python -m pytest tests/ -v`
Expected: All existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add justscrape_mcp.py
git commit -m "fix: add SSRF protection to MCP handlers, fix asyncio deprecation (fixes #3, #4, #6)"
```

### Task 3: Add validation to web_scraper, async_scraper, js_scraper

**Files:**
- Modify: `web_scraper.py`
- Modify: `async_scraper.py`
- Modify: `js_scraper.py`

- [ ] **Step 1: Add validation in `WebScraper.fetch()` before `session.get()`**

- [ ] **Step 2: Add validation in `AsyncWebScraper.fetch()` before `client.get()`**

- [ ] **Step 3: Add validation in `JavaScriptScraper.scrape()` before `page.goto()`**

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

```bash
git add web_scraper.py async_scraper.py js_scraper.py
git commit -m "fix: add SSRF protection to all scraper modules (fixes #3, #4)"
```

### Task 4: Add validation to smart_scraper source adapters

**Files:**
- Modify: `smart_scraper.py`

- [ ] **Step 1: Add validation in each source adapter before `requests.get()`**

Adapters: `_scrape_reddit_json`, `_scrape_devto_api`, `_scrape_github_discussions_html`, `_scrape_stackexchange_api`, `_scrape_stackexchange_stackprinter`

- [ ] **Step 2: Run tests**

- [ ] **Step 3: Commit**

```bash
git add smart_scraper.py
git commit -m "fix: add SSRF protection to source adapters (fixes #3)"
```

---

## Chunk 3: XXE Protection + Sitemap Hardening

### Task 5: Add defusedxml and harden sitemap parser

**Files:**
- Modify: `requirements.txt`
- Modify: `sitemap_registry.py`
- Create: `tests/test_xxe_protection.py`

- [ ] **Step 1: Write failing tests for XXE protection**

```python
# tests/test_xxe_protection.py
import pytest

class TestXXEProtection:
    """Verify sitemap parser is safe against XML attacks."""

    def test_normal_sitemap_parses(self):
        from sitemap_registry import SitemapRegistry
        registry = SitemapRegistry(db_path=":memory:")
        content = b'''<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>'''
        urls, children = registry._parse_sitemap(content, "https://example.com")
        assert len(urls) == 2

    def test_rejects_entity_expansion(self):
        from sitemap_registry import SitemapRegistry
        registry = SitemapRegistry(db_path=":memory:")
        bomb = b'''<?xml version="1.0"?>
        <!DOCTYPE lolz [
          <!ENTITY lol "lol">
          <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
        ]>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>&lol2;</loc></url>
        </urlset>'''
        urls, children = registry._parse_sitemap(bomb, "https://example.com")
        # Should return empty (parse error from defusedxml) rather than expanding
        assert len(urls) == 0

    def test_child_sitemap_cap(self):
        from sitemap_registry import SitemapRegistry
        registry = SitemapRegistry(db_path=":memory:")
        # Build sitemap index with 200 child sitemaps
        entries = "".join(
            f"<sitemap><loc>https://example.com/sitemap{i}.xml</loc></sitemap>"
            for i in range(200)
        )
        content = f'''<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            {entries}
        </sitemapindex>'''.encode()
        urls, children = registry._parse_sitemap(content, "https://example.com")
        assert len(children) <= 100  # Capped
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Add `defusedxml` to requirements.txt, install it**

- [ ] **Step 4: Replace `ET` with `defusedxml.ElementTree` in sitemap_registry.py**

- [ ] **Step 5: Add child sitemap cap (max 100) and URL validation for sitemap URLs**

- [ ] **Step 6: Run all tests**

- [ ] **Step 7: Commit**

```bash
git add requirements.txt sitemap_registry.py tests/test_xxe_protection.py
git commit -m "fix: add XXE protection and sitemap hardening (fixes #5)"
```
