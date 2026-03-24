"""Tests for async scraper module."""

import pytest
from justscrape.async_scraper import _get_domain_semaphore, _domain_semaphores, _MAX_DOMAIN_SEMAPHORES


class TestDomainSemaphores:
    """Test per-domain concurrency limiting."""

    def setup_method(self):
        _domain_semaphores.clear()

    def test_creates_semaphore_for_new_domain(self):
        sem = _get_domain_semaphore("https://example.com/page")
        assert sem is not None
        assert "example.com" in _domain_semaphores

    def test_reuses_semaphore_for_same_domain(self):
        sem1 = _get_domain_semaphore("https://example.com/page1")
        sem2 = _get_domain_semaphore("https://example.com/page2")
        assert sem1 is sem2

    def test_different_domains_get_different_semaphores(self):
        sem1 = _get_domain_semaphore("https://example.com/")
        sem2 = _get_domain_semaphore("https://other.com/")
        assert sem1 is not sem2

    def test_evicts_when_at_capacity(self):
        # Fill to capacity
        for i in range(_MAX_DOMAIN_SEMAPHORES):
            _get_domain_semaphore(f"https://domain{i}.com/")

        assert len(_domain_semaphores) == _MAX_DOMAIN_SEMAPHORES

        # Adding one more should evict the oldest
        _get_domain_semaphore("https://new-domain.com/")
        assert len(_domain_semaphores) == _MAX_DOMAIN_SEMAPHORES
        assert "new-domain.com" in _domain_semaphores

    def test_max_domain_semaphores_is_bounded(self):
        assert _MAX_DOMAIN_SEMAPHORES <= 1000


class TestAsyncWebScraperImport:
    """Test that async scraper can be imported and configured."""

    def test_httpx_availability_flag(self):
        from justscrape.async_scraper import HTTPX_AVAILABLE
        # httpx should be installed per requirements.txt
        assert HTTPX_AVAILABLE is True

    def test_scraper_creation(self):
        from justscrape.async_scraper import AsyncWebScraper
        scraper = AsyncWebScraper()
        assert scraper.client is not None
        assert scraper._closed is False
