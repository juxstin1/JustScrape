"""
Unit tests for quality_scorer.py — QualityScorer and deduplicate_results.

Tests cover:
- Composite score weighted blend in 0.0-1.0 range
- Original position signal contributes ~15-20% weight
- freshness_score=None handled by redistributing weight
- Relevance dominates authority signal
- Near-duplicate snippet deduplication via rapidfuzz
- Higher-scored result is kept when deduping
- Distinct results preserved even from same domain
- Zero-length or empty snippet gets score 0.0
"""

import pytest
from dataclasses import dataclass
from typing import Optional, List

from result_reranker import RankedResult
from snippet_extractor import ExtractedSnippet
from query_analyzer import AnalyzedQuery


# -----------------------------------------------------------------------
# Helpers to build fixture objects
# -----------------------------------------------------------------------

def make_ranked(
    url: str = "https://docs.python.org/3/library/re.html",
    title: str = "Python re module",
    snippet: str = "Regular expressions in Python",
    original_position: int = 1,
    authority_score: float = 1.0,
    freshness_score: Optional[float] = None,
    is_blocked: bool = False,
) -> RankedResult:
    return RankedResult(
        url=url,
        title=title,
        snippet=snippet,
        original_position=original_position,
        authority_score=authority_score,
        freshness_score=freshness_score,
        is_blocked=is_blocked,
    )


def make_snippet(
    text: str = "Regular expressions are a powerful tool for matching patterns.",
    chunk_index: int = 0,
    score: float = 0.8,
    is_code: bool = False,
    source_url: str = "https://docs.python.org/3/library/re.html",
    best_sentence: str = "Regular expressions are a powerful tool.",
) -> ExtractedSnippet:
    return ExtractedSnippet(
        text=text,
        chunk_index=chunk_index,
        score=score,
        is_code=is_code,
        source_url=source_url,
        best_sentence=best_sentence,
    )


def make_query(
    original: str = "python regular expressions",
    intent: str = "code",
    confidence: float = 0.9,
) -> AnalyzedQuery:
    return AnalyzedQuery(
        original=original,
        intent=intent,
        confidence=confidence,
        expanded_queries=[],
        sub_queries=[],
        entities=[],
    )


# -----------------------------------------------------------------------
# Import under test (must succeed before tests run)
# -----------------------------------------------------------------------

from quality_scorer import QualityScorer, ScoredResult, deduplicate_results


# -----------------------------------------------------------------------
# Tests: composite_score signal presence and range
# -----------------------------------------------------------------------

class TestQualityScorerRange:
    """Composite score must always be in [0.0, 1.0]."""

    def test_score_in_range_all_signals_present(self):
        """Composite score with all signals present is in 0.0-1.0."""
        scorer = QualityScorer()
        ranked = make_ranked(freshness_score=0.8, original_position=2)
        snippet = make_snippet(score=0.7)
        query = make_query(intent="news")
        result = scorer.score(snippet, ranked, query)
        assert isinstance(result, ScoredResult)
        assert 0.0 <= result.composite_score <= 1.0

    def test_score_in_range_no_freshness(self):
        """Composite score without freshness signal is still in 0.0-1.0."""
        scorer = QualityScorer()
        ranked = make_ranked(freshness_score=None, original_position=3)
        snippet = make_snippet(score=0.6)
        query = make_query(intent="code")
        result = scorer.score(snippet, ranked, query)
        assert 0.0 <= result.composite_score <= 1.0

    def test_score_breakdown_keys_present(self):
        """score_breakdown contains all four signal keys."""
        scorer = QualityScorer()
        result = scorer.score(make_snippet(), make_ranked(), make_query())
        expected_keys = {"relevance", "authority", "freshness", "position"}
        assert expected_keys == set(result.score_breakdown.keys())


# -----------------------------------------------------------------------
# Tests: position signal
# -----------------------------------------------------------------------

class TestPositionSignal:
    """Original search position must contribute meaningfully (~15-20%)."""

    def test_position_1_scores_higher_than_position_10(self):
        """Position 1 produces a higher composite than position 10 (all else equal)."""
        scorer = QualityScorer()
        snippet = make_snippet(score=0.6)
        query = make_query(intent="code")
        ranked_top = make_ranked(original_position=1, authority_score=0.5)
        ranked_bottom = make_ranked(original_position=10, authority_score=0.5)
        top_result = scorer.score(snippet, ranked_top, query)
        bottom_result = scorer.score(snippet, ranked_bottom, query)
        assert top_result.composite_score > bottom_result.composite_score

    def test_position_signal_bounded_difference(self):
        """Difference between position 1 and position 10 is in [0.10, 0.35] (bounded weight)."""
        scorer = QualityScorer()
        snippet = make_snippet(score=0.6)
        query = make_query(intent="code")
        ranked_top = make_ranked(original_position=1, authority_score=0.5)
        ranked_bottom = make_ranked(original_position=10, authority_score=0.5)
        top_result = scorer.score(snippet, ranked_top, query)
        bottom_result = scorer.score(snippet, ranked_bottom, query)
        diff = top_result.composite_score - bottom_result.composite_score
        # position weight is 0.15-0.20, score diff for pos1 vs pos10 is 0.9
        # so diff = weight * 0.9 ≈ 0.135–0.18
        assert 0.10 <= diff <= 0.35, f"Position diff {diff:.3f} out of expected range"

    def test_position_above_10_gets_zero(self):
        """Position 11+ maps to position score 0.0."""
        scorer = QualityScorer()
        snippet = make_snippet(score=0.5)
        query = make_query(intent="general")
        ranked = make_ranked(original_position=11)
        result = scorer.score(snippet, ranked, query)
        assert result.score_breakdown["position"] == 0.0


# -----------------------------------------------------------------------
# Tests: freshness weight redistribution
# -----------------------------------------------------------------------

class TestFreshnessRedistribution:
    """When freshness_score is None, weight must be redistributed — not dropped."""

    def test_freshness_none_scores_comparable_to_freshness_present(self):
        """Non-news query (freshness=None) produces valid score not zero."""
        scorer = QualityScorer()
        ranked = make_ranked(freshness_score=None)
        snippet = make_snippet(score=0.7)
        query = make_query(intent="research")
        result = scorer.score(snippet, ranked, query)
        assert result.composite_score > 0.0

    def test_freshness_breakdown_is_zero_when_none(self):
        """Freshness component in score_breakdown is 0.0 when freshness_score is None."""
        scorer = QualityScorer()
        ranked = make_ranked(freshness_score=None)
        snippet = make_snippet(score=0.8)
        query = make_query(intent="code")
        result = scorer.score(snippet, ranked, query)
        assert result.score_breakdown["freshness"] == 0.0

    def test_freshness_applied_for_news_query(self):
        """Freshness component is non-zero for news query with freshness_score set."""
        scorer = QualityScorer()
        ranked = make_ranked(freshness_score=0.9, original_position=1)
        snippet = make_snippet(score=0.7)
        query = make_query(intent="news")
        result = scorer.score(snippet, ranked, query)
        assert result.score_breakdown["freshness"] > 0.0


# -----------------------------------------------------------------------
# Tests: relevance dominance
# -----------------------------------------------------------------------

class TestRelevanceDominance:
    """Snippet relevance score must dominate authority."""

    def test_high_relevance_low_authority_beats_low_relevance_high_authority(self):
        """snippet.score=0.9 authority=0.2 scores higher than snippet.score=0.3 authority=1.0."""
        scorer = QualityScorer()
        query = make_query(intent="code")

        high_rel_low_auth = scorer.score(
            make_snippet(score=0.9),
            make_ranked(authority_score=0.2, original_position=5),
            query,
        )
        low_rel_high_auth = scorer.score(
            make_snippet(score=0.3),
            make_ranked(authority_score=1.0, original_position=5),
            query,
        )
        assert high_rel_low_auth.composite_score > low_rel_high_auth.composite_score


# -----------------------------------------------------------------------
# Tests: empty/zero-length snippet
# -----------------------------------------------------------------------

class TestEmptySnippet:
    def test_empty_text_gets_zero_score(self):
        """Zero-length snippet text produces composite_score of 0.0."""
        scorer = QualityScorer()
        snippet = make_snippet(text="", score=0.0, best_sentence="")
        ranked = make_ranked()
        query = make_query()
        result = scorer.score(snippet, ranked, query)
        assert result.composite_score == 0.0

    def test_whitespace_only_text_gets_zero_score(self):
        """Whitespace-only snippet text produces composite_score of 0.0."""
        scorer = QualityScorer()
        snippet = make_snippet(text="   \n\t  ", score=0.0, best_sentence="")
        ranked = make_ranked()
        query = make_query()
        result = scorer.score(snippet, ranked, query)
        assert result.composite_score == 0.0


# -----------------------------------------------------------------------
# Tests: ScoredResult fields
# -----------------------------------------------------------------------

class TestScoredResultFields:
    def test_scored_result_carries_metadata(self):
        """ScoredResult contains url, title, snippet_text, best_sentence, etc."""
        scorer = QualityScorer()
        snippet = make_snippet(
            text="The re module provides regex support.",
            best_sentence="The re module provides regex support.",
            source_url="https://docs.python.org/3/library/re.html",
        )
        ranked = make_ranked(
            url="https://docs.python.org/3/library/re.html",
            title="Python re module",
            original_position=1,
        )
        query = make_query()
        result = scorer.score(snippet, ranked, query)
        assert result.url == "https://docs.python.org/3/library/re.html"
        assert result.title == "Python re module"
        assert result.snippet_text == "The re module provides regex support."
        assert result.best_sentence == "The re module provides regex support."
        assert result.original_position == 1
        assert result.source_url == "https://docs.python.org/3/library/re.html"

    def test_source_type_inferred(self):
        """source_type is inferred from URL domain."""
        scorer = QualityScorer()
        docs_result = scorer.score(
            make_snippet(source_url="https://docs.python.org/3/library/re.html"),
            make_ranked(url="https://docs.python.org/3/library/re.html"),
            make_query(),
        )
        assert docs_result.source_type == "documentation"

        forum_result = scorer.score(
            make_snippet(source_url="https://stackoverflow.com/questions/123"),
            make_ranked(url="https://stackoverflow.com/questions/123"),
            make_query(),
        )
        assert forum_result.source_type == "forum"

    def test_is_code_preserved(self):
        """is_code flag is preserved from ExtractedSnippet."""
        scorer = QualityScorer()
        snippet = make_snippet(is_code=True)
        result = scorer.score(snippet, make_ranked(), make_query())
        assert result.is_code is True

    def test_confidence_from_query(self):
        """confidence is taken from AnalyzedQuery."""
        scorer = QualityScorer()
        query = make_query(confidence=0.75)
        result = scorer.score(make_snippet(), make_ranked(), query)
        assert result.confidence == 0.75


# -----------------------------------------------------------------------
# Tests: infer_source_type
# -----------------------------------------------------------------------

class TestInferSourceType:
    def test_documentation_domains(self):
        scorer = QualityScorer()
        assert scorer.infer_source_type("https://docs.python.org/3/") == "documentation"
        assert scorer.infer_source_type("https://readthedocs.io/en/latest/") == "documentation"

    def test_forum_domains(self):
        scorer = QualityScorer()
        assert scorer.infer_source_type("https://stackoverflow.com/q/123") == "forum"
        assert scorer.infer_source_type("https://www.reddit.com/r/python") == "forum"

    def test_news_domains(self):
        scorer = QualityScorer()
        assert scorer.infer_source_type("https://www.reuters.com/article") == "news"
        assert scorer.infer_source_type("https://www.bbc.com/news/tech") == "news"

    def test_repository_domain(self):
        scorer = QualityScorer()
        assert scorer.infer_source_type("https://github.com/user/repo") == "repository"

    def test_blog_domains(self):
        scorer = QualityScorer()
        assert scorer.infer_source_type("https://medium.com/@author/post") == "blog"
        assert scorer.infer_source_type("https://dev.to/author/post") == "blog"

    def test_wiki_domain(self):
        scorer = QualityScorer()
        assert scorer.infer_source_type("https://en.wikipedia.org/wiki/Python") == "wiki"

    def test_unknown_domain(self):
        scorer = QualityScorer()
        assert scorer.infer_source_type("https://some-random-blog.example.com/post") == "unknown"


# -----------------------------------------------------------------------
# Tests: deduplicate_results
# -----------------------------------------------------------------------

class TestDeduplicateResults:
    """deduplicate_results removes near-identical snippets, keeps highest-scored."""

    def _make_scored_result(
        self,
        snippet_text: str,
        composite_score: float,
        url: str = "https://example.com",
    ) -> ScoredResult:
        return ScoredResult(
            url=url,
            title="Test",
            snippet_text=snippet_text,
            best_sentence=snippet_text[:50] if snippet_text else "",
            composite_score=composite_score,
            score_breakdown={"relevance": composite_score, "authority": 0.5, "freshness": 0.0, "position": 0.5},
            source_url=url,
            source_type="unknown",
            detected_date=None,
            confidence=0.8,
            original_position=1,
            is_code=False,
        )

    def test_removes_near_duplicate_snippets(self):
        """Near-identical snippets (>85% similarity) are collapsed to one."""
        text_a = "Python is a high-level programming language known for readability."
        text_b = "Python is a high-level programming language, known for readability."
        results = [
            self._make_scored_result(text_a, 0.7, "https://a.com"),
            self._make_scored_result(text_b, 0.6, "https://b.com"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1

    def test_keeps_higher_scored_when_deduping(self):
        """When two snippets are near-duplicates, the one with higher score is kept."""
        text_a = "Python is a high-level programming language known for readability."
        text_b = "Python is a high-level programming language, known for readability."
        # text_a has higher score
        results = [
            self._make_scored_result(text_a, 0.9, "https://a.com"),
            self._make_scored_result(text_b, 0.4, "https://b.com"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0].composite_score == 0.9

    def test_keeps_lower_scored_when_it_has_higher_score(self):
        """When lower-scored input has higher composite_score, it is kept."""
        text_a = "Python is a high-level programming language known for readability."
        text_b = "Python is a high-level programming language, known for readability."
        # second result has higher score despite being second in list
        results = [
            self._make_scored_result(text_a, 0.4, "https://a.com"),
            self._make_scored_result(text_b, 0.9, "https://b.com"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1
        assert deduped[0].composite_score == 0.9

    def test_preserves_distinct_results_from_same_domain(self):
        """Distinct snippets from the same domain are both kept."""
        text_a = "Python is a high-level programming language."
        text_b = "Django is a web framework built with Python."
        results = [
            self._make_scored_result(text_a, 0.8, "https://example.com/a"),
            self._make_scored_result(text_b, 0.7, "https://example.com/b"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 2

    def test_preserves_all_distinct_results(self):
        """All distinct snippets are returned unchanged."""
        results = [
            self._make_scored_result("Python syntax and semantics overview.", 0.9, "https://a.com"),
            self._make_scored_result("Django ORM query optimization techniques.", 0.7, "https://b.com"),
            self._make_scored_result("FastAPI async request handling.", 0.8, "https://c.com"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 3

    def test_empty_list_returns_empty(self):
        """Empty input returns empty output."""
        assert deduplicate_results([]) == []

    def test_single_result_returned_unchanged(self):
        """Single result is returned as-is."""
        results = [self._make_scored_result("Python is great.", 0.8)]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1

    def test_custom_threshold_respected(self):
        """Custom threshold=0.5 deduplicates results at lower similarity."""
        text_a = "Python programming language"
        text_b = "Python programming lang"  # ~similar but may not hit 0.85
        results = [
            self._make_scored_result(text_a, 0.8, "https://a.com"),
            self._make_scored_result(text_b, 0.6, "https://b.com"),
        ]
        # With very low threshold, these should be considered duplicates
        deduped_strict = deduplicate_results(results, threshold=0.5)
        assert len(deduped_strict) == 1

    def test_default_threshold_85(self):
        """Default threshold=0.85 is the dedup boundary."""
        # Texts with ~50% similarity should NOT be deduped at default threshold
        text_a = "Python is a programming language with clear syntax and dynamic typing."
        text_b = "Java is a statically typed object-oriented language used in enterprise."
        results = [
            self._make_scored_result(text_a, 0.8, "https://a.com"),
            self._make_scored_result(text_b, 0.7, "https://b.com"),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 2
