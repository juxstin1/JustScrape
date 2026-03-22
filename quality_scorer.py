"""
Quality Scorer — composite result scoring and near-duplicate deduplication.

Computes a final composite score for each search result by blending snippet
relevance, source authority, content freshness, and original search position
signals into a single 0.0–1.0 score.

Implements RANK-04 (composite quality scoring), PIPE-01 (pipeline integration),
and PIPE-04 (deduplication via rapidfuzz).

Query-type-aware weights:
  - news:                relevance=0.35, authority=0.20, freshness=0.25, position=0.20
  - code:                relevance=0.45, authority=0.25, freshness=0.0,  position=0.15
  - general/research/
    how-to/lookup/
    comparison:          relevance=0.45, authority=0.20, freshness=0.0,  position=0.15

When freshness is None (non-news intent), freshness weight is redistributed
proportionally to relevance and authority, keeping position weight unchanged.

Position score formula: max(0.0, 1.0 - (position - 1) * 0.1)
  position 1  → 1.0
  position 10 → 0.1
  position 11 → 0.0

Deduplication uses rapidfuzz token_sort_ratio with lazy import fallback — if
rapidfuzz is not installed, deduplication is skipped and input is returned
unchanged (same pattern as Playwright optional dep).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

from result_reranker import RankedResult
from snippet_extractor import ExtractedSnippet
from query_analyzer import AnalyzedQuery


# ---------------------------------------------------------------------------
# Module-level weight tables (query-type-aware, per D-11)
# ---------------------------------------------------------------------------

# Keys: relevance, authority, freshness, position
_WEIGHTS: Dict[str, Dict[str, float]] = {
    "news": {
        "relevance": 0.35,
        "authority": 0.20,
        "freshness": 0.25,
        "position": 0.20,
    },
    "code": {
        "relevance": 0.45,
        "authority": 0.25,
        "freshness": 0.0,
        "position": 0.15,
    },
}

# Default weights for research / how-to / lookup / comparison / general
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "relevance": 0.45,
    "authority": 0.20,
    "freshness": 0.0,
    "position": 0.15,
}

# Intents that receive freshness scoring (mirrors result_reranker._FRESHNESS_INTENTS)
_FRESHNESS_INTENTS = {"news", "current", "current-events"}

# Domain substring patterns for source type inference, checked in order.
# First match wins.
_SOURCE_TYPE_PATTERNS: List[tuple[str, str]] = [
    # documentation (match before general hosting)
    ("docs.", "documentation"),
    ("readthedocs", "documentation"),
    ("devdocs", "documentation"),
    # repository
    ("github.com", "repository"),
    ("gitlab.com", "repository"),
    ("bitbucket.org", "repository"),
    # wiki
    ("wikipedia.org", "wiki"),
    # forum
    ("stackoverflow.com", "forum"),
    ("stackexchange.com", "forum"),
    ("reddit.com", "forum"),
    ("discourse", "forum"),
    # news
    ("reuters.com", "news"),
    ("apnews.com", "news"),
    ("bbc.com", "news"),
    ("bbc.co.uk", "news"),
    ("nytimes.com", "news"),
    ("theguardian.com", "news"),
    ("techcrunch.com", "news"),
    ("arstechnica.com", "news"),
    ("theverge.com", "news"),
    # blog
    ("medium.com", "blog"),
    ("dev.to", "blog"),
    ("substack.com", "blog"),
    ("hashnode.com", "blog"),
    ("wordpress.com", "blog"),
]


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ScoredResult:
    """A search result with a composite quality score.

    Per RANK-04: final artifact returned by the scoring stage, combining
    all signals into one composite_score (0.0–1.0) for pipeline ranking.
    """

    url: str
    title: str
    snippet_text: str          # Best snippet text
    best_sentence: str         # Most relevant sentence within snippet
    composite_score: float     # 0.0–1.0 final score
    score_breakdown: dict      # {"relevance": float, "authority": float, "freshness": float, "position": float}
    source_url: str
    source_type: str           # Inferred: "documentation"|"forum"|"news"|"repository"|"blog"|"wiki"|"unknown"
    detected_date: Optional[str]  # ISO date string if found, None otherwise
    confidence: float          # From AnalyzedQuery
    original_position: int
    is_code: bool


# ---------------------------------------------------------------------------
# QualityScorer
# ---------------------------------------------------------------------------

class QualityScorer:
    """Compute composite quality scores for search results.

    score() takes an ExtractedSnippet, a RankedResult, and an AnalyzedQuery
    and returns a ScoredResult with a blended composite_score.

    The scoring is purely mathematical — no I/O, no external services.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        snippet: ExtractedSnippet,
        ranked: RankedResult,
        query: AnalyzedQuery,
    ) -> ScoredResult:
        """Compute and return a ScoredResult for the given inputs.

        Empty/whitespace-only snippet text always produces composite_score=0.0.
        """
        # Guard: empty text → zero
        if not snippet.text or not snippet.text.strip():
            return ScoredResult(
                url=ranked.url,
                title=ranked.title,
                snippet_text=snippet.text,
                best_sentence=snippet.best_sentence,
                composite_score=0.0,
                score_breakdown={"relevance": 0.0, "authority": 0.0, "freshness": 0.0, "position": 0.0},
                source_url=snippet.source_url,
                source_type=self.infer_source_type(ranked.url),
                detected_date=None,
                confidence=query.confidence,
                original_position=ranked.original_position,
                is_code=snippet.is_code,
            )

        intent = query.intent
        weights = dict(_WEIGHTS.get(intent, _DEFAULT_WEIGHTS))

        # Compute raw signal scores
        relevance_raw = max(0.0, min(1.0, snippet.score))
        authority_raw = max(0.0, min(1.0, ranked.authority_score))
        position_raw = self._position_score(ranked.original_position)

        # Freshness: only used when intent is a freshness intent AND freshness_score present
        freshness_raw: float = 0.0
        if intent in _FRESHNESS_INTENTS and ranked.freshness_score is not None:
            freshness_raw = max(0.0, min(1.0, ranked.freshness_score))

        # When freshness weight > 0 but freshness_raw == 0 (None score or zero intent weight),
        # redistribute the unused freshness weight to relevance and authority proportionally.
        w_freshness = weights["freshness"]
        if w_freshness > 0.0 and freshness_raw == 0.0:
            # Redistribute when freshness signal is missing or zero
            if ranked.freshness_score is None or ranked.freshness_score == 0.0 or intent not in _FRESHNESS_INTENTS:
                w_relevance = weights["relevance"]
                w_authority = weights["authority"]
                total_non_fresh = w_relevance + w_authority
                if total_non_fresh > 0:
                    scale = (total_non_fresh + w_freshness) / total_non_fresh
                    weights["relevance"] = w_relevance * scale
                    weights["authority"] = w_authority * scale
                    weights["freshness"] = 0.0

        # Final composite
        composite = (
            weights["relevance"] * relevance_raw
            + weights["authority"] * authority_raw
            + weights["freshness"] * freshness_raw
            + weights["position"] * position_raw
        )
        composite = round(max(0.0, min(1.0, composite)), 6)

        breakdown = {
            "relevance": round(weights["relevance"] * relevance_raw, 6),
            "authority": round(weights["authority"] * authority_raw, 6),
            "freshness": round(weights["freshness"] * freshness_raw, 6),
            "position": round(weights["position"] * position_raw, 6),
        }

        return ScoredResult(
            url=ranked.url,
            title=ranked.title,
            snippet_text=snippet.text,
            best_sentence=snippet.best_sentence,
            composite_score=composite,
            score_breakdown=breakdown,
            source_url=snippet.source_url,
            source_type=self.infer_source_type(ranked.url),
            detected_date=None,  # Date extraction not in scope for this module
            confidence=query.confidence,
            original_position=ranked.original_position,
            is_code=snippet.is_code,
        )

    def infer_source_type(self, url: str) -> str:
        """Map a URL to a source type category.

        Categories: "documentation", "forum", "news", "repository", "blog",
        "wiki", "unknown".

        Matching is done by checking whether any known substring appears in the
        lowercased netloc.  First match wins.
        """
        try:
            netloc = urlparse(url).netloc.lower()
        except Exception:
            return "unknown"

        for pattern, source_type in _SOURCE_TYPE_PATTERNS:
            if pattern in netloc:
                return source_type

        return "unknown"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _position_score(position: int) -> float:
        """Convert 1-based original_position to a 0.0–1.0 score.

        Formula: max(0.0, 1.0 - (position - 1) * 0.1)
          position 1  → 1.0
          position 10 → 0.1
          position 11 → 0.0
        """
        return max(0.0, 1.0 - (position - 1) * 0.1)


# ---------------------------------------------------------------------------
# deduplicate_results
# ---------------------------------------------------------------------------

def deduplicate_results(
    results: List[ScoredResult],
    threshold: float = 0.85,
) -> List[ScoredResult]:
    """Remove near-duplicate results by comparing snippet_text similarity.

    Uses rapidfuzz.fuzz.token_sort_ratio for similarity scoring (lazy import).
    If rapidfuzz is not installed, returns *results* unchanged (graceful fallback
    matching the Playwright optional-dep pattern used in this codebase).

    Algorithm (O(n^2) — fine for small result lists):
    1. Sort results by composite_score descending so higher-scored items are
       processed first.
    2. Mark a result as a duplicate if its snippet_text has token_sort_ratio
       > threshold * 100 with any already-kept result.
    3. Return deduplicated list preserving relative score order.

    Args:
        results: List of ScoredResult to deduplicate.
        threshold: Similarity threshold in [0.0, 1.0]. Default 0.85.

    Returns:
        Deduplicated list with highest-scored result kept per near-dup group.
    """
    if not results:
        return results

    # Lazy import — graceful fallback if rapidfuzz not available
    try:
        from rapidfuzz.fuzz import token_sort_ratio  # type: ignore
    except ImportError:
        return results

    # Sort by composite_score descending so best result is encountered first
    sorted_results = sorted(results, key=lambda r: r.composite_score, reverse=True)

    kept: List[ScoredResult] = []
    for candidate in sorted_results:
        # Don't dedup empty snippets — they'd all collapse into one
        if not candidate.snippet_text:
            kept.append(candidate)
            continue
        is_duplicate = False
        for existing in kept:
            if not existing.snippet_text:
                continue
            similarity = token_sort_ratio(
                candidate.snippet_text,
                existing.snippet_text,
            )
            if similarity > threshold * 100:
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(candidate)

    return kept
