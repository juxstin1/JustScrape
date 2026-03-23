"""Tests for worker.py tool dispatch and classification."""

import pytest
from justscrape.worker import classify_content, TOOLS


class TestClassifyContent:
    """Test content classification engine."""

    def test_empty_content(self):
        result = classify_content("", "", had_html=False, encoding_error=False, method="static")
        assert result["status"] == "empty"
        assert result["confidence"] == "high"

    def test_encoding_failure(self):
        result = classify_content("some text", "Title", had_html=True, encoding_error=True, method="static")
        assert result["status"] == "encoding-failure"

    def test_blocked_short_content(self):
        result = classify_content(
            "Please verify you are human by completing the captcha",
            "Just a moment...", had_html=True, encoding_error=False, method="static"
        )
        assert result["status"] == "blocked"

    def test_blocked_title_signal(self):
        result = classify_content(
            "short", "Just a moment...", had_html=True, encoding_error=False, method="static"
        )
        assert result["status"] == "blocked"

    def test_thin_content(self):
        result = classify_content(
            "Very short page content.", "Title", had_html=True, encoding_error=False, method="static"
        )
        assert result["status"] == "thin"

    def test_usable_long_content(self):
        content = "This is a real article.\n\n" * 500  # ~12K chars with paragraphs
        result = classify_content(
            content, "Article Title", had_html=True, encoding_error=False, method="static"
        )
        assert result["status"] == "usable"
        assert result["confidence"] == "high"

    def test_usable_medium_content(self):
        content = "Real content here.\n\n" * 150  # ~3K chars with paragraphs
        result = classify_content(
            content, "Title", had_html=True, encoding_error=False, method="static"
        )
        assert result["status"] == "usable"

    def test_blocked_words_in_long_content_not_flagged(self):
        """Long articles about captchas/blocking should NOT be classified as blocked."""
        content = "This is a detailed article about how captcha and cloudflare protection works. " * 100
        result = classify_content(
            content, "Understanding Bot Detection", had_html=True, encoding_error=False, method="static"
        )
        assert result["status"] == "usable"


class TestToolRegistry:
    """Test that all expected tools are registered."""

    def test_all_tools_registered(self):
        expected = {"search_sources", "retrieve_source", "research_with_sources", "extract_urls",
                    "web_search", "scrape_url", "search_and_scrape"}
        assert expected.issubset(set(TOOLS.keys()))

    def test_tools_are_callable(self):
        for name, func in TOOLS.items():
            assert callable(func), f"Tool {name} is not callable"
