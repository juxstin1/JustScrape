"""Tests for XXE/XML bomb protection in sitemap parser."""

import pytest
import sqlite3
from pathlib import Path


class TestXXEProtection:
    """Verify sitemap parser is safe against XML attacks."""

    def _make_registry(self):
        """Create a temp registry for testing."""
        import tempfile, os
        from justscrape.sitemap_registry import SitemapRegistry
        tmpdir = tempfile.mkdtemp()
        return SitemapRegistry(db_path=os.path.join(tmpdir, "test.db"))

    def test_normal_sitemap_parses(self):
        registry = self._make_registry()
        content = b'''<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>'''
        urls, children = registry._parse_sitemap(content, "https://example.com")
        assert len(urls) == 2
        assert urls[0].url == "https://example.com/page1"
        assert urls[1].url == "https://example.com/page2"

    def test_sitemap_index_parses(self):
        registry = self._make_registry()
        content = b'''<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
            <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
        </sitemapindex>'''
        urls, children = registry._parse_sitemap(content, "https://example.com")
        assert len(children) == 2
        assert len(urls) == 0

    def test_rejects_entity_expansion(self):
        """defusedxml should block DTD entity expansion (billion laughs)."""
        registry = self._make_registry()
        bomb = b'''<?xml version="1.0"?>
        <!DOCTYPE lolz [
          <!ENTITY lol "lol">
          <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
        ]>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>&lol2;</loc></url>
        </urlset>'''
        # defusedxml raises on DTD processing; _parse_sitemap catches ParseError
        urls, children = registry._parse_sitemap(bomb, "https://example.com")
        # Should return empty (blocked by defusedxml) rather than expanding
        assert len(urls) == 0

    def test_rejects_external_entity(self):
        """defusedxml should block external entity references."""
        registry = self._make_registry()
        xxe = b'''<?xml version="1.0"?>
        <!DOCTYPE foo [
          <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>&xxe;</loc></url>
        </urlset>'''
        urls, children = registry._parse_sitemap(xxe, "https://example.com")
        assert len(urls) == 0

    def test_child_sitemap_cap(self):
        """Verify child sitemaps are capped at MAX_CHILD_SITEMAPS."""
        from justscrape.sitemap_registry import MAX_CHILD_SITEMAPS
        registry = self._make_registry()
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
        # _parse_sitemap returns all children; the cap is applied in _process_sitemap
        assert len(children) == 200
        # But MAX_CHILD_SITEMAPS should be <= 100
        assert MAX_CHILD_SITEMAPS <= 100

    def test_empty_sitemap(self):
        registry = self._make_registry()
        content = b'''<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        </urlset>'''
        urls, children = registry._parse_sitemap(content, "https://example.com")
        assert len(urls) == 0
        assert len(children) == 0

    def test_malformed_xml(self):
        registry = self._make_registry()
        content = b"this is not xml at all"
        urls, children = registry._parse_sitemap(content, "https://example.com")
        assert len(urls) == 0
        assert len(children) == 0
