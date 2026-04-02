"""
Pipeline Integration Tests — verify full quality pipeline wiring in handle_search_and_scrape.

Tests end-to-end flow: query analysis -> search -> rerank -> scrape+extract -> score -> dedup -> return.
Verifies provenance metadata (source_type, detected_date, confidence, score_breakdown) on every result.
Confirms backward compatibility of response structure and MCP tool signatures.
"""

import asyncio
import json
import sys
import unittest.mock as mock
from unittest.mock import MagicMock, patch

import pytest

from justscrape.server import (
    handle_research_with_sources,
    handle_retrieve_source,
    handle_search_and_scrape,
    handle_search_sources,
    list_tools,
)


class TestPipelineIntegration:
    """Integration tests for the wired quality pipeline."""

    @pytest.mark.asyncio
    async def test_response_has_composite_score_and_score_breakdown(self):
        """Results include composite_score and score_breakdown from QualityScorer."""
        query = "python exception handling"
        arguments = {"query": query, "num_results": 2}

        # Mock search_full to return canned results
        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://docs.python.org/3/tutorial/errors.html",
                    "title": "Exceptions — Python Documentation",
                    "snippet": "Python uses exceptions to handle errors...",
                    "position": 1,
                },
                {
                    "url": "https://stackoverflow.com/questions/12345",
                    "title": "How to handle exceptions in Python?",
                    "snippet": "Use try/except blocks...",
                    "position": 2,
                },
            ],
            "search_time_ms": 100,
            "cached": False,
        }

        # Mock scraper to return canned content
        mock_scraped = {
            "content": "Python exceptions are raised when errors occur. try/except handles them.",
            "title": "Exceptions — Python Documentation",
        }

        with patch("justscrape.server.search_full", return_value=mock_search_result):
            with patch("justscrape.server.PooledSmartScraper") as mock_scraper_class:
                mock_scraper = MagicMock()
                mock_scraper.scrape_to_dict.return_value = mock_scraped
                mock_scraper_class.return_value = mock_scraper

                result = await handle_search_and_scrape(arguments)

                response_text = result.content[0].text
                response = json.loads(response_text)

                assert response["success"] is True
                assert len(response["results"]) > 0

                first_result = response["results"][0]
                assert "relevance_score" in first_result
                assert isinstance(first_result["relevance_score"], float)
                assert "score_breakdown" in first_result
                assert isinstance(first_result["score_breakdown"], dict)
                assert "relevance" in first_result["score_breakdown"]
                assert "authority" in first_result["score_breakdown"]

    @pytest.mark.asyncio
    async def test_response_has_provenance_metadata(self):
        """Results include source_type, detected_date, confidence from QualityScorer."""
        query = "javascript async await"
        arguments = {"query": query, "num_results": 2}

        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://developer.mozilla.org/en-US/docs/Learn/JavaScript/Asynchronous",
                    "title": "Asynchronous JavaScript — MDN",
                    "snippet": "Async/await makes async code easier to read...",
                    "position": 1,
                },
            ],
            "search_time_ms": 50,
            "cached": False,
        }

        mock_scraped = {
            "content": "Async/await is a modern JavaScript pattern for handling promises.",
            "title": "Asynchronous JavaScript — MDN",
        }

        with patch("justscrape.server.search_full", return_value=mock_search_result):
            with patch("justscrape.server.PooledSmartScraper") as mock_scraper_class:
                mock_scraper = MagicMock()
                mock_scraper.scrape_to_dict.return_value = mock_scraped
                mock_scraper_class.return_value = mock_scraper

                result = await handle_search_and_scrape(arguments)

                response_text = result.content[0].text
                response = json.loads(response_text)

                first_result = response["results"][0]
                assert "source_type" in first_result
                assert isinstance(first_result["source_type"], str)
                assert "confidence" in first_result
                assert isinstance(first_result["confidence"], float)
                # detected_date may be None for non-news content
                assert "detected_date" in first_result

    @pytest.mark.asyncio
    async def test_results_sorted_by_composite_score(self):
        """Results are sorted by composite_score descending (not old relevance_score)."""
        query = "rust borrow checker"
        arguments = {"query": query, "num_results": 3}

        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://docs.rust-lang.org/book/ch04-02.html",
                    "title": "Ownership",
                    "snippet": "...",
                    "position": 1,
                },
                {
                    "url": "https://stackoverflow.com/questions/54568",
                    "title": "Borrow checker error",
                    "snippet": "...",
                    "position": 2,
                },
                {
                    "url": "https://medium.com/rust-article",
                    "title": "Understanding borrow checker",
                    "snippet": "...",
                    "position": 3,
                },
            ],
            "search_time_ms": 80,
            "cached": False,
        }

        mock_scraped = {
            "content": "Rust's borrow checker ensures memory safety without data races.",
            "title": "Ownership",
        }

        with patch("justscrape.server.search_full", return_value=mock_search_result):
            with patch("justscrape.server.PooledSmartScraper") as mock_scraper_class:
                mock_scraper = MagicMock()
                mock_scraper.scrape_to_dict.return_value = mock_scraped
                mock_scraper_class.return_value = mock_scraper

                result = await handle_search_and_scrape(arguments)

                response_text = result.content[0].text
                response = json.loads(response_text)

                results = response["results"]
                if len(results) > 1:
                    # Verify descending order by composite_score
                    for i in range(len(results) - 1):
                        assert (
                            results[i]["relevance_score"]
                            >= results[i + 1]["relevance_score"]
                        )

    @pytest.mark.asyncio
    async def test_backward_compatibility_response_structure(self):
        """Response JSON has all existing keys: success, query, results, total_results."""
        query = "kubernetes deployment"
        arguments = {"query": query}

        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/",
                    "title": "Deployments",
                    "snippet": "...",
                    "position": 1,
                }
            ],
            "search_time_ms": 60,
            "cached": False,
        }

        mock_scraped = {
            "content": "Kubernetes deployments manage pod replicas.",
            "title": "Deployments",
        }

        with patch("justscrape.server.search_full", return_value=mock_search_result):
            with patch("justscrape.server.PooledSmartScraper") as mock_scraper_class:
                mock_scraper = MagicMock()
                mock_scraper.scrape_to_dict.return_value = mock_scraped
                mock_scraper_class.return_value = mock_scraper

                result = await handle_search_and_scrape(arguments)

                response_text = result.content[0].text
                response = json.loads(response_text)

                # Verify existing keys present
                assert "success" in response
                assert "query" in response
                assert "results" in response
                assert "total_results" in response
                assert "skipped" in response
                assert response["success"] is True
                assert response["query"] == query

    @pytest.mark.asyncio
    async def test_fallback_on_pipeline_exception(self):
        """When new pipeline raises exception, fallback produces valid results with relevance_score."""
        query = "test fallback query"
        arguments = {"query": query}

        # Force QueryAnalyzer to raise exception
        with patch(
            "justscrape.server._query_analyzer.analyze",
            side_effect=Exception("Analyzer failed"),
        ):
            # Mock old-path search_full
            mock_search_result = {
                "success": True,
                "results": [
                    {
                        "url": "https://example.com",
                        "title": "Test",
                        "snippet": "...",
                        "position": 1,
                    }
                ],
                "search_time_ms": 50,
                "cached": False,
            }

            mock_scraped = {"content": "Fallback content", "title": "Test"}

            with patch("justscrape.server.search_full", return_value=mock_search_result):
                with patch("justscrape.server.PooledSmartScraper") as mock_scraper_class:
                    mock_scraper = MagicMock()
                    mock_scraper.scrape_to_dict.return_value = mock_scraped
                    mock_scraper_class.return_value = mock_scraper

                    result = await handle_search_and_scrape(arguments)

                    response_text = result.content[0].text
                    response = json.loads(response_text)

                    assert response["success"] is True
                    assert len(response["results"]) > 0
                    # Fallback uses old relevance_score
                    first_result = response["results"][0]
                    assert "relevance_score" in first_result
                    assert first_result["scraped_successfully"] is True

    @pytest.mark.asyncio
    async def test_tool_signature_unchanged(self):
        """handle_search_and_scrape accepts same parameters as before (backward compat)."""
        # Test all original parameters work
        arguments = {
            "query": "test query",
            "num_results": 3,
            "max_content_length": 5000,
            "site": "docs.python.org",
            "date_range": "2024",
        }

        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://docs.python.org",
                    "title": "Python",
                    "snippet": "...",
                    "position": 1,
                }
            ],
            "search_time_ms": 40,
            "cached": False,
        }

        mock_scraped = {"content": "Python docs content", "title": "Python"}

        with patch("justscrape.server.search_full", return_value=mock_search_result):
            with patch("justscrape.server.PooledSmartScraper") as mock_scraper_class:
                mock_scraper = MagicMock()
                mock_scraper.scrape_to_dict.return_value = mock_scraped
                mock_scraper_class.return_value = mock_scraper

                result = await handle_search_and_scrape(arguments)

                response = json.loads(result.content[0].text)
                assert response["success"] is True


class TestRefinedToolContract:
    """Verify the refined LM Studio-friendly MCP contract is exposed and stable."""

    @pytest.mark.asyncio
    async def test_list_tools_exposes_refined_tools_first(self):
        tools = await list_tools()
        names = [tool.name for tool in tools]

        assert "research_with_sources" in names
        assert "retrieve_source" in names
        assert "search_sources" in names
        assert names.index("research_with_sources") < names.index("web_search")

    @pytest.mark.asyncio
    async def test_handle_search_sources_includes_usage_hint(self):
        mock_search_result = {
            "success": True,
            "query": "python scraping",
            "results": [
                {
                    "url": "https://example.com/article",
                    "title": "Example Article",
                    "snippet": "Helpful snippet",
                    "position": 1,
                }
            ],
            "total_results": 1,
            "search_time_ms": 25,
            "source": "duckduckgo",
            "cached": False,
        }

        with patch("justscrape.server.search_full", return_value=mock_search_result):
            result = await handle_search_sources({"query": "python scraping"})

        response = json.loads(result.content[0].text)
        assert "success" not in response
        assert response["usage_hint"]["recommended_next_tool"] == "research_with_sources"
        assert "search_loop_guard" in response["usage_hint"]

    @pytest.mark.asyncio
    async def test_handle_retrieve_source_returns_classification_and_warning(self):
        mock_scraped = {
            "title": "Day 15 | Fishtank Live Season 5 Recap",
            "content": "Navigation\nShow transcript\nComments\nShare\nSave\nDownload\n"
            + ("transcript placeholder " * 60),
            "status_code": 200,
            "scrape_method": "javascript_pooled",
        }

        with patch("justscrape.server.validate_url", return_value=(True, "ok")):
            with patch("justscrape.server.PooledSmartScraper") as mock_scraper_class:
                mock_scraper = MagicMock()
                mock_scraper.scrape_to_dict.return_value = mock_scraped
                mock_scraper_class.return_value = mock_scraper

                result = await handle_retrieve_source(
                    {
                        "url": "https://www.youtube.com/watch?v=abc123",
                        "allow_javascript": True,
                    }
                )

        response = json.loads(result.content[0].text)
        assert response["signals"]["method"] == "javascript"
        assert "classification" in response
        assert response["usage_hint"]["recommended_action"] in {
            "extract_answer_or_cite",
            "choose_another_source",
        }
        assert "warnings" in response

    @pytest.mark.asyncio
    async def test_handle_research_with_sources_includes_anti_loop_hint(self):
        mock_result = {
            "query": "python scraping",
            "sources": [
                {
                    "url": "https://example.com/article",
                    "title": "Example",
                    "status": "usable",
                    "content_length": 1200,
                    "content": "Useful content",
                }
            ],
            "failures": [],
            "skipped": [],
            "metrics": {
                "total": 1,
                "usable_count": 1,
                "usable_rate": 1.0,
            },
        }

        with patch(
            "justscrape.server.research_with_sources_contract",
            return_value=mock_result,
        ):
            result = await handle_research_with_sources({"query": "python scraping"})

        response = json.loads(result.content[0].text)
        assert response["usage_hint"]["recommended_action"] == "answer_from_sources"
        assert "search_loop_guard" in response["usage_hint"]


class TestNoRegressions:
    """Verify existing Phase 1 tests still pass."""

    def test_query_analyzer_tests_pass(self):
        """Existing QueryAnalyzer tests pass."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_query_analyzer.py", "-x", "-q"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"QueryAnalyzer tests failed: {result.stdout}"

    def test_result_reranker_tests_pass(self):
        """Existing ResultReranker tests pass."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_result_reranker.py", "-x", "-q"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"ResultReranker tests failed: {result.stdout}"

    def test_snippet_extractor_tests_pass(self):
        """Existing SnippetExtractor tests pass."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_snippet_extractor.py", "-x", "-q"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"SnippetExtractor tests failed: {result.stdout}"

    def test_quality_scorer_tests_pass(self):
        """Existing QualityScorer tests pass."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_quality_scorer.py", "-x", "-q"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"QualityScorer tests failed: {result.stdout}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
