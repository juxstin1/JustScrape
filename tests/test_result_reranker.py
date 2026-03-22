"""Tests for result_reranker.py — RANK-01 (authority scoring) and RANK-02 (freshness weighting)."""

import pytest
from datetime import datetime, timedelta
from result_reranker import ResultReranker, RankedResult


class TestAuthorityScoring:
    """Tests for RANK-01: query-type-aware authority scoring."""

    def setup_method(self):
        self.reranker = ResultReranker()

    def test_code_stackoverflow_authoritative(self):
        score = self.reranker.get_authority_score("https://stackoverflow.com/questions/123", "code")
        assert score == 1.0

    def test_research_stackoverflow_standard(self):
        score = self.reranker.get_authority_score("https://stackoverflow.com/questions/123", "research")
        assert score == 0.5

    def test_code_github_authoritative(self):
        score = self.reranker.get_authority_score("https://github.com/user/repo", "code")
        assert score == 1.0

    def test_news_reuters_authoritative(self):
        score = self.reranker.get_authority_score("https://reuters.com/article/1", "news")
        assert score == 1.0

    def test_unknown_domain_defaults_to_standard(self):
        score = self.reranker.get_authority_score("https://unknownblog123.com/post", "code")
        assert score == 0.5

    def test_blocked_domain_returns_zero(self):
        score = self.reranker.get_authority_score("https://answers.com/q/1", "code")
        assert score == 0.0

    def test_blocked_ehow(self):
        score = self.reranker.get_authority_score("https://ehow.com/how-to-do-something", "code")
        assert score == 0.0

    def test_subdomain_matching(self):
        score = self.reranker.get_authority_score("https://docs.python.org/3/library/os.html", "code")
        assert score == 1.0

    def test_www_stripping(self):
        score = self.reranker.get_authority_score("https://www.stackoverflow.com/questions/123", "code")
        assert score == 1.0

    def test_unknown_domain_never_zero(self):
        """Per Pitfall 6: unknown domains MUST return 0.5, never 0.0."""
        score = self.reranker.get_authority_score("https://randomsite-xyz-123.net/page", "code")
        assert score != 0.0
        assert score == 0.5

    def test_general_query_type_unknown_domain(self):
        score = self.reranker.get_authority_score("https://somesite.org/article", "general")
        assert score == 0.5


class TestFreshnessScoring:
    """Tests for RANK-02: freshness weighting for time-sensitive queries."""

    def setup_method(self):
        self.reranker = ResultReranker()

    def test_news_recent_article_high_freshness(self):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%B %d, %Y")
        snippet = f"Published {yesterday}. New developments in the story."
        score = self.reranker.get_freshness_score(snippet, "news")
        assert score is not None
        assert score > 0.8

    def test_news_old_article_low_freshness(self):
        old_date = (datetime.now() - timedelta(days=90)).strftime("%B %d, %Y")
        snippet = f"Published {old_date}. Background on the ongoing situation."
        score = self.reranker.get_freshness_score(snippet, "news")
        assert score is not None
        assert score < 0.3

    def test_no_freshness_for_code_intent(self):
        snippet = "How to use Python generators for lazy evaluation."
        score = self.reranker.get_freshness_score(snippet, "code")
        assert score is None

    def test_no_freshness_for_research_intent(self):
        snippet = "A study on neural networks published in Nature."
        score = self.reranker.get_freshness_score(snippet, "research")
        assert score is None

    def test_no_date_news_gets_penalty(self):
        snippet = "Some news article without any date information in it."
        score = self.reranker.get_freshness_score(snippet, "news")
        assert score == 0.3

    def test_news_moderately_old_article(self):
        two_weeks_ago = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        snippet = f"Article from {two_weeks_ago} about market trends."
        score = self.reranker.get_freshness_score(snippet, "news")
        assert score is not None
        assert 0.3 < score < 0.8


class TestReranking:
    """Tests for ResultReranker.rerank() combining authority and freshness."""

    def setup_method(self):
        self.reranker = ResultReranker()

    def test_rerank_preserves_original_position(self):
        results = [
            {"url": "https://stackoverflow.com/q/1", "title": "SO answer", "snippet": "code snippet", "position": 1},
            {"url": "https://unknownblog.com/post", "title": "Blog post", "snippet": "random content", "position": 2},
            {"url": "https://github.com/user/repo", "title": "GitHub repo", "snippet": "open source", "position": 3},
        ]
        ranked = self.reranker.rerank(results, "code")
        original_positions = {r.url: r.original_position for r in ranked}
        assert original_positions["https://stackoverflow.com/q/1"] == 1
        assert original_positions["https://unknownblog.com/post"] == 2
        assert original_positions["https://github.com/user/repo"] == 3

    def test_rerank_sorts_by_authority(self):
        results = [
            {"url": "https://unknownblog.com/post", "title": "Blog", "snippet": "content", "position": 1},
            {"url": "https://stackoverflow.com/q/1", "title": "SO", "snippet": "code", "position": 2},
            {"url": "https://answers.com/q/1", "title": "Answers", "snippet": "answer", "position": 3},
        ]
        ranked = self.reranker.rerank(results, "code")
        # Higher authority should sort first; blocked domains last
        assert ranked[0].authority_score >= ranked[1].authority_score
        assert ranked[-1].is_blocked is True

    def test_blocked_domains_marked(self):
        results = [
            {"url": "https://answers.com/q/1", "title": "Answers", "snippet": "answer", "position": 1},
            {"url": "https://ehow.com/how-to", "title": "eHow", "snippet": "how to", "position": 2},
            {"url": "https://stackoverflow.com/q/1", "title": "SO", "snippet": "code", "position": 3},
        ]
        ranked = self.reranker.rerank(results, "code")
        blocked_urls = {r.url for r in ranked if r.is_blocked}
        assert "https://answers.com/q/1" in blocked_urls
        assert "https://ehow.com/how-to" in blocked_urls
        assert "https://stackoverflow.com/q/1" not in blocked_urls

    def test_rerank_returns_ranked_result_objects(self):
        results = [
            {"url": "https://stackoverflow.com/q/1", "title": "SO", "snippet": "code", "position": 1},
        ]
        ranked = self.reranker.rerank(results, "code")
        assert len(ranked) == 1
        assert isinstance(ranked[0], RankedResult)


class TestRankedResultDataclass:
    """Tests for RankedResult dataclass fields."""

    def test_fields(self):
        result = RankedResult(
            url="https://example.com/page",
            title="Example Page",
            snippet="Some content here",
            original_position=1,
            authority_score=0.8,
            freshness_score=None,
            is_blocked=False,
        )
        assert result.url == "https://example.com/page"
        assert result.title == "Example Page"
        assert result.snippet == "Some content here"
        assert result.original_position == 1
        assert result.authority_score == 0.8
        assert result.freshness_score is None
        assert result.is_blocked is False

    def test_fields_with_freshness(self):
        result = RankedResult(
            url="https://reuters.com/article/1",
            title="Breaking News",
            snippet="Just happened today",
            original_position=1,
            authority_score=1.0,
            freshness_score=0.95,
            is_blocked=False,
        )
        assert result.freshness_score == 0.95

    def test_blocked_field(self):
        result = RankedResult(
            url="https://answers.com/q/1",
            title="Answers",
            snippet="answer content",
            original_position=5,
            authority_score=0.0,
            freshness_score=None,
            is_blocked=True,
        )
        assert result.is_blocked is True
        assert result.authority_score == 0.0
