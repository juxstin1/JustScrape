"""Tests for search backend adapters."""

import pytest
from backends.base import SearchBackend, MultiSearch
from web_search import SearchResponse, SearchResult


class FakeBackend(SearchBackend):
    """Test backend that returns controlled results."""

    name = "fake"

    def __init__(self, results=None, success=True, available=True):
        self._results = results or []
        self._success = success
        self._available = available

    def search(self, query, num_results=10, region="wt-wt", date_range=None):
        return SearchResponse(
            query=query,
            results=self._results,
            total_results=len(self._results),
            search_time_ms=10,
            source=self.name,
            success=self._success,
        )

    def is_available(self):
        return self._available


class TestMultiSearchFallback:
    """Test MultiSearch fallback mode."""

    def test_returns_first_successful(self):
        r = SearchResult(position=1, title="Test", url="https://example.com", snippet="snip", source="fake")
        b1 = FakeBackend(results=[], success=True)
        b2 = FakeBackend(results=[r], success=True)
        ms = MultiSearch([b1, b2], mode="fallback")
        result = ms.search("test")
        assert result.success
        assert len(result.results) == 1

    def test_skips_unavailable_backends(self):
        r = SearchResult(position=1, title="Test", url="https://example.com", snippet="snip", source="fake")
        b1 = FakeBackend(results=[r], available=False)
        b2 = FakeBackend(results=[r], available=True)
        ms = MultiSearch([b1, b2], mode="fallback")
        result = ms.search("test")
        assert result.success

    def test_no_backends_returns_error(self):
        ms = MultiSearch([], mode="fallback")
        result = ms.search("test")
        assert not result.success
        assert "No search backends" in result.error

    def test_all_fail_returns_error(self):
        b1 = FakeBackend(success=False)
        ms = MultiSearch([b1], mode="fallback")
        result = ms.search("test")
        assert not result.success


class TestMultiSearchMerge:
    """Test MultiSearch merge mode."""

    def test_merges_results(self):
        r1 = SearchResult(position=1, title="A", url="https://a.com", snippet="a", source="b1")
        r2 = SearchResult(position=1, title="B", url="https://b.com", snippet="b", source="b2")
        b1 = FakeBackend(results=[r1])
        b2 = FakeBackend(results=[r2])
        ms = MultiSearch([b1, b2], mode="merge")
        result = ms.search("test")
        assert result.success
        assert len(result.results) == 2


class TestBraveBackend:
    """Test Brave backend configuration."""

    def test_not_available_without_key(self):
        from backends.brave import BraveSearchBackend
        b = BraveSearchBackend(api_key="")
        assert b.is_available() is False

    def test_available_with_key(self):
        from backends.brave import BraveSearchBackend
        b = BraveSearchBackend(api_key="test-key")
        assert b.is_available() is True

    def test_returns_error_without_key(self):
        from backends.brave import BraveSearchBackend
        b = BraveSearchBackend(api_key="")
        result = b.search("test")
        assert not result.success
        assert "No Brave API key" in result.error


class TestDuckDuckGoBackend:
    """Test DuckDuckGo backend."""

    def test_is_available(self):
        from backends.duckduckgo import DuckDuckGoBackend
        b = DuckDuckGoBackend()
        assert b.is_available() is True

    def test_name(self):
        from backends.duckduckgo import DuckDuckGoBackend
        assert DuckDuckGoBackend.name == "duckduckgo"
