"""Tests for fast lane — lightweight path for simple queries.

Verifies that simple queries (pizza delivery, weather) skip the heavy pipeline
(reranking, BM25 snippet extraction, quality scoring, dedup) while complex
queries (code errors, comparisons, research) still use the full pipeline.
"""

import asyncio
import json
import unittest.mock as mock
from unittest.mock import MagicMock, patch

import pytest

from justscrape.query_analyzer import QueryAnalyzer, AnalyzedQuery
from justscrape.server import (
    _is_fast_lane_eligible,
    handle_search_and_scrape,
)


class TestFastLaneEligibility:
    """Test _is_fast_lane_eligible decision logic."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    def test_simple_general_query_is_eligible(self):
        """'best pizza delivery near me' → general intent, no entities → fast lane."""
        analyzed = self.analyzer.analyze("best pizza delivery near me")
        assert analyzed.intent == "general"
        assert _is_fast_lane_eligible(analyzed) is True

    def test_weather_query_is_eligible(self):
        """'weather in new york' → general intent → fast lane."""
        analyzed = self.analyzer.analyze("weather in new york")
        assert _is_fast_lane_eligible(analyzed) is True

    def test_simple_factual_query_is_eligible(self):
        """'capital of france' → general intent → fast lane."""
        analyzed = self.analyzer.analyze("capital of france")
        assert _is_fast_lane_eligible(analyzed) is True

    def test_code_query_not_eligible(self):
        """'python import error traceback' → code intent → full pipeline."""
        analyzed = self.analyzer.analyze("python import error traceback")
        assert analyzed.intent == "code"
        assert _is_fast_lane_eligible(analyzed) is False

    def test_howto_query_not_eligible(self):
        """'how to set up docker containers' → how-to intent → full pipeline."""
        analyzed = self.analyzer.analyze("how to set up docker containers")
        assert analyzed.intent == "how-to"
        assert _is_fast_lane_eligible(analyzed) is False

    def test_research_query_not_eligible(self):
        """'what is quantum computing overview' → research intent → full pipeline."""
        analyzed = self.analyzer.analyze("what is quantum computing overview")
        assert analyzed.intent == "research"
        assert _is_fast_lane_eligible(analyzed) is False

    def test_comparison_query_not_eligible(self):
        """'react vs vue pros and cons' → comparison intent → full pipeline."""
        analyzed = self.analyzer.analyze("react vs vue pros and cons")
        assert analyzed.intent == "comparison"
        assert _is_fast_lane_eligible(analyzed) is False

    def test_news_query_not_eligible(self):
        """'latest news AI release today' → news intent → full pipeline."""
        analyzed = self.analyzer.analyze("latest news AI release today")
        assert analyzed.intent == "news"
        assert _is_fast_lane_eligible(analyzed) is False

    def test_query_with_entities_not_eligible(self):
        """Even general-seeming queries with version entities use full pipeline."""
        analyzed = AnalyzedQuery(
            original="update to 3.12",
            intent="general",
            confidence=0.5,
            expanded_queries=["update to 3.12"],
            sub_queries=["update to 3.12"],
            entities=[{"text": "3.12", "type": "version"}],
        )
        assert _is_fast_lane_eligible(analyzed) is False

    def test_query_with_sub_queries_not_eligible(self):
        """Conjunction queries (decomposed) use full pipeline."""
        analyzed = AnalyzedQuery(
            original="cats and dogs",
            intent="general",
            confidence=0.5,
            expanded_queries=["cats and dogs"],
            sub_queries=["cats", "dogs"],
            entities=[],
        )
        assert _is_fast_lane_eligible(analyzed) is False

    def test_lookup_low_confidence_is_eligible(self):
        """Lookup intent with moderate confidence → fast lane."""
        analyzed = AnalyzedQuery(
            original="docs site",
            intent="lookup",
            confidence=0.7,
            expanded_queries=["docs site"],
            sub_queries=["docs site"],
            entities=[],
        )
        assert _is_fast_lane_eligible(analyzed) is True

    def test_lookup_high_confidence_not_eligible(self):
        """Lookup intent with high confidence → full pipeline (authority reranking helps)."""
        analyzed = AnalyzedQuery(
            original="python documentation api reference changelog",
            intent="lookup",
            confidence=0.9,
            expanded_queries=["python documentation api reference changelog"],
            sub_queries=["python documentation api reference changelog"],
            entities=[],
        )
        assert _is_fast_lane_eligible(analyzed) is False


class TestFastLaneIntegration:
    """Integration tests: verify fast lane is used for simple queries."""

    @pytest.mark.asyncio
    async def test_simple_query_returns_fast_lane_flag(self):
        """Simple query response should include fast_lane: true."""
        arguments = {"query": "best pizza delivery near me", "num_results": 2}

        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://www.yelp.com/search?find_desc=pizza+delivery",
                    "title": "Best Pizza Delivery Near Me - Yelp",
                    "snippet": "Top 10 pizza delivery spots...",
                    "position": 1,
                },
                {
                    "url": "https://www.doordash.com/cuisine/pizza/",
                    "title": "Pizza Delivery - DoorDash",
                    "snippet": "Order pizza delivery online...",
                    "position": 2,
                },
            ],
            "search_time_ms": 50,
            "cached": False,
        }

        mock_scraped = {
            "content": "Here are the best pizza delivery options in your area. Tony's Pizza rated 4.8 stars.",
            "title": "Best Pizza Delivery Near Me - Yelp",
        }

        with patch("justscrape.handlers.research.search_full", return_value=mock_search_result):
            with patch("justscrape.handlers.research.PooledSmartScraper") as mock_scraper_class:
                mock_scraper = MagicMock()
                mock_scraper.scrape_to_dict.return_value = mock_scraped
                mock_scraper_class.return_value = mock_scraper

                result = await handle_search_and_scrape(arguments)

                response = json.loads(result.content[0].text)
                assert response["success"] is True
                assert response["fast_lane"] is True
                assert len(response["results"]) > 0

                # Fast lane results should NOT have score_breakdown (that's the full pipeline)
                first = response["results"][0]
                assert "score_breakdown" not in first
                assert first.get("fast_lane") is True
                assert "relevance_score" in first

    @pytest.mark.asyncio
    async def test_complex_query_skips_fast_lane(self):
        """Code query should use full pipeline, not fast lane."""
        arguments = {"query": "python exception handling traceback", "num_results": 2}

        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://docs.python.org/3/tutorial/errors.html",
                    "title": "Exceptions — Python Documentation",
                    "snippet": "Python uses exceptions to handle errors...",
                    "position": 1,
                },
            ],
            "search_time_ms": 50,
            "cached": False,
        }

        mock_scraped = {
            "content": "Python exceptions are raised when errors occur. try/except handles them.",
            "title": "Exceptions — Python Documentation",
        }

        with patch("justscrape.handlers.research.search_full", return_value=mock_search_result):
            with patch("justscrape.handlers.research.PooledSmartScraper") as mock_scraper_class:
                mock_scraper = MagicMock()
                mock_scraper.scrape_to_dict.return_value = mock_scraped
                mock_scraper_class.return_value = mock_scraper

                result = await handle_search_and_scrape(arguments)

                response = json.loads(result.content[0].text)
                assert response["success"] is True
                # Full pipeline — no fast_lane flag
                assert response.get("fast_lane") is not True
                # Full pipeline results have score_breakdown
                if response["results"]:
                    first = response["results"][0]
                    assert "score_breakdown" in first

    @pytest.mark.asyncio
    async def test_fast_lane_does_not_call_reranker(self):
        """Fast lane should skip the ResultReranker entirely."""
        arguments = {"query": "weather in london", "num_results": 1}

        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://weather.com/weather/london",
                    "title": "London Weather",
                    "snippet": "Current weather in London...",
                    "position": 1,
                },
            ],
            "search_time_ms": 30,
            "cached": False,
        }

        mock_scraped = {
            "content": "London weather today: 15°C, partly cloudy.",
            "title": "London Weather",
        }

        with patch("justscrape.handlers.research.search_full", return_value=mock_search_result):
            with patch("justscrape.handlers.research.PooledSmartScraper") as mock_scraper_class:
                with patch("justscrape.handlers.research._result_reranker") as mock_reranker:
                    mock_scraper = MagicMock()
                    mock_scraper.scrape_to_dict.return_value = mock_scraped
                    mock_scraper_class.return_value = mock_scraper

                    await handle_search_and_scrape(arguments)

                    # Reranker should NOT have been called
                    mock_reranker.rerank.assert_not_called()

    @pytest.mark.asyncio
    async def test_fast_lane_does_not_call_snippet_extractor(self):
        """Fast lane should skip the SnippetExtractor entirely."""
        arguments = {"query": "stock price apple", "num_results": 1}

        mock_search_result = {
            "success": True,
            "results": [
                {
                    "url": "https://finance.yahoo.com/quote/AAPL",
                    "title": "AAPL Stock Price",
                    "snippet": "Apple Inc. stock price...",
                    "position": 1,
                },
            ],
            "search_time_ms": 30,
            "cached": False,
        }

        mock_scraped = {
            "content": "AAPL: $185.50 (+1.2%). Apple Inc. market cap: $2.8T.",
            "title": "AAPL Stock Price",
        }

        with patch("justscrape.handlers.research.search_full", return_value=mock_search_result):
            with patch("justscrape.handlers.research.PooledSmartScraper") as mock_scraper_class:
                with patch("justscrape.handlers.research._snippet_extractor") as mock_extractor:
                    mock_scraper = MagicMock()
                    mock_scraper.scrape_to_dict.return_value = mock_scraped
                    mock_scraper_class.return_value = mock_scraper

                    await handle_search_and_scrape(arguments)

                    # Snippet extractor should NOT have been called
                    mock_extractor.extract_snippets.assert_not_called()
