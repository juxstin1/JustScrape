"""Tests for sitemap registry SQLite storage and URL management."""

import pytest
from datetime import datetime, timedelta


class TestSitemapRegistry:
    """Test SitemapRegistry with in-memory database."""

    def _make_registry(self, tmpdir=None):
        import tempfile, os
        from sitemap_registry import SitemapRegistry
        if tmpdir is None:
            tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test_sitemap.db")
        return SitemapRegistry(db_path=db_path)

    def test_init_creates_tables(self):
        registry = self._make_registry()
        stats = registry.get_stats()
        assert stats["total_sitemaps"] == 0
        assert stats["total_urls"] == 0

    def test_extract_domain(self):
        registry = self._make_registry()
        assert registry._extract_domain("https://www.example.com/page") == "example.com"
        assert registry._extract_domain("example.com") == "example.com"
        assert registry._extract_domain("https://docs.python.org") == "docs.python.org"

    def test_has_sitemap_false_for_unknown(self):
        registry = self._make_registry()
        assert registry.has_sitemap("unknown.com") is False

    def test_mark_failed(self):
        registry = self._make_registry()
        registry._mark_failed("example.com", "No sitemap found")
        assert registry.has_sitemap("example.com") is False
        info = registry.get_sitemap_info("example.com")
        assert info is not None
        assert info.status == "failed"
        assert info.error_message == "No sitemap found"

    def test_parse_sitemap_normal(self):
        registry = self._make_registry()
        content = b'''<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url>
                <loc>https://example.com/page1</loc>
                <priority>0.8</priority>
                <changefreq>daily</changefreq>
            </url>
            <url>
                <loc>https://example.com/page2</loc>
                <priority>0.5</priority>
            </url>
        </urlset>'''
        urls, children = registry._parse_sitemap(content, "https://example.com")
        assert len(urls) == 2
        assert urls[0].url == "https://example.com/page1"
        assert urls[0].priority == 0.8
        assert urls[0].change_frequency == "daily"
        assert len(children) == 0

    def test_parse_sitemap_index(self):
        registry = self._make_registry()
        content = b'''<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
            <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
        </sitemapindex>'''
        urls, children = registry._parse_sitemap(content, "https://example.com")
        assert len(urls) == 0
        assert len(children) == 2

    def test_parse_malformed_xml(self):
        registry = self._make_registry()
        urls, children = registry._parse_sitemap(b"not xml", "https://example.com")
        assert len(urls) == 0
        assert len(children) == 0

    def test_is_stale_true_for_unknown(self):
        registry = self._make_registry()
        assert registry.is_stale("unknown.com") is True

    def test_list_domains_empty(self):
        registry = self._make_registry()
        assert registry.list_domains() == []

    def test_generate_sitemap_urls(self):
        registry = self._make_registry()
        urls = registry._generate_sitemap_urls("example.com")
        assert any("sitemap.xml" in u for u in urls)
        assert len(urls) >= 5

    def test_hash_content(self):
        registry = self._make_registry()
        h1 = registry._hash_content(b"hello")
        h2 = registry._hash_content(b"hello")
        h3 = registry._hash_content(b"world")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 64  # SHA-256 hex


class TestSitemapConstants:
    """Test safety constants."""

    def test_child_sitemap_cap(self):
        from sitemap_registry import MAX_CHILD_SITEMAPS
        assert MAX_CHILD_SITEMAPS <= 100

    def test_max_sitemap_size(self):
        from sitemap_registry import MAX_SITEMAP_SIZE
        assert MAX_SITEMAP_SIZE == 50 * 1024 * 1024
