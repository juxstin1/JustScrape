"""Tests for URL discovery system."""

import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestURLDiscovery:
    """Test URLDiscovery JSON storage and filtering."""

    def _make_discovery(self, tmpdir):
        """Create a URLDiscovery instance with temp storage."""
        from justscrape.url_discovery import URLDiscovery
        discovery = URLDiscovery()
        discovery.storage_dir = Path(tmpdir)
        discovery.sources_file = Path(tmpdir) / 'sources.json'
        discovery.discovered_file = Path(tmpdir) / 'discovered.json'
        discovery._save_sources([])
        discovery._save_discovered({})
        return discovery

    def test_add_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            discovery = self._make_discovery(tmpdir)
            assert discovery.add_source("https://example.com") is True
            assert discovery.add_source("https://example.com") is False  # Duplicate
            assert len(discovery.get_sources()) == 1

    def test_add_source_prepends_https(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            discovery = self._make_discovery(tmpdir)
            discovery.add_source("example.com")
            sources = discovery.get_sources()
            assert sources[0] == "https://example.com"

    def test_remove_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            discovery = self._make_discovery(tmpdir)
            discovery.add_source("https://example.com")
            assert discovery.remove_source("https://example.com") is True
            assert discovery.remove_source("https://example.com") is False
            assert len(discovery.get_sources()) == 0

    def test_junk_filter(self):
        from justscrape.url_discovery import URLDiscovery
        discovery = URLDiscovery.__new__(URLDiscovery)
        urls = [
            "https://example.com/page",
            "https://doubleclick.net/ad",
            "https://example.com/ads/banner",
            "https://example.com/article",
            "javascript:alert(1)",
            "mailto:test@example.com",
        ]
        filtered, junk_count = discovery._filter_junk(urls)
        assert "https://example.com/page" in filtered
        assert "https://example.com/article" in filtered
        assert "https://doubleclick.net/ad" not in filtered
        assert "javascript:alert(1)" not in filtered
        assert junk_count >= 3

    def test_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            discovery = self._make_discovery(tmpdir)
            discovery._save_discovered({
                "https://example.com/python-tutorial": {"discovered_from": "src", "timestamp": "2026-01-01"},
                "https://example.com/java-guide": {"discovered_from": "src", "timestamp": "2026-01-01"},
                "https://other.com/rust-book": {"discovered_from": "src", "timestamp": "2026-01-01"},
            })
            matches = discovery.search("python")
            assert len(matches) == 1
            assert "python" in matches[0]

    def test_clear_discovered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            discovery = self._make_discovery(tmpdir)
            discovery._save_discovered({
                "https://a.com": {}, "https://b.com": {},
            })
            count = discovery.clear_discovered()
            assert count == 2
            assert discovery.get_stats()["total_discovered"] == 0

    def test_get_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            discovery = self._make_discovery(tmpdir)
            discovery.add_source("https://example.com")
            stats = discovery.get_stats()
            assert stats["total_sources"] == 1
            assert stats["total_discovered"] == 0

    def test_max_discovered_urls_cap(self):
        from justscrape.url_discovery import MAX_DISCOVERED_URLS
        assert MAX_DISCOVERED_URLS == 100000
