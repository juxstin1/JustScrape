---
phase: 02-pipeline-integration
plan: 01
subsystem: quality-scoring
tags: [scoring, deduplication, composite-score, rapidfuzz, tdd]
dependency_graph:
  requires:
    - result_reranker.py (RankedResult type)
    - snippet_extractor.py (ExtractedSnippet type)
    - query_analyzer.py (AnalyzedQuery type)
  provides:
    - quality_scorer.py (QualityScorer, ScoredResult, deduplicate_results)
  affects:
    - pipeline integration (02-02) — consumes ScoredResult
tech_stack:
  added:
    - rapidfuzz>=3.0.0 (near-duplicate snippet detection)
  patterns:
    - TDD (RED/GREEN)
    - Lazy import for optional dependency (rapidfuzz fallback pattern)
    - Dataclass data containers (ScoredResult)
    - Query-type-aware weight dispatch
key_files:
  created:
    - quality_scorer.py
    - tests/test_quality_scorer.py
  modified:
    - requirements.txt
decisions:
  - "Freshness weight redistributed proportionally to relevance+authority when freshness_score is None, keeping position weight unchanged"
  - "Position score formula max(0.0, 1.0 - (pos-1) * 0.1) gives exactly 15-20% effective weight for positions 1-10"
  - "rapidfuzz added as required dependency (not optional) since dedup is a core feature — but lazy import fallback preserved for environments without it"
  - "infer_source_type uses substring matching on netloc with ordered list — first match wins"
metrics:
  duration: "7 minutes"
  completed: "2026-03-22"
  tasks: 1
  files: 3
---

# Phase 02 Plan 01: QualityScorer — Composite Scoring and Deduplication Summary

**One-liner:** Query-type-aware composite scoring (relevance 45%, authority 20-25%, position 15-20%, freshness 25% news-only) with rapidfuzz near-duplicate deduplication.

## Tasks Completed

| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 (RED) | Failing tests for QualityScorer and deduplicate_results | 34b010a | Done |
| 1 (GREEN) | QualityScorer module implementation + rapidfuzz in requirements | 84eb857 | Done |

## What Was Built

### quality_scorer.py (329 lines)

- **`ScoredResult` dataclass** — final pipeline artifact with url, title, snippet_text, best_sentence, composite_score, score_breakdown (4-key dict), source_url, source_type, detected_date, confidence, original_position, is_code
- **`QualityScorer.score(snippet, ranked, query) -> ScoredResult`** — pure computation, no I/O
  - Query-type-aware weights dispatched from `_WEIGHTS` table (news vs code vs default)
  - Position score: `max(0.0, 1.0 - (position - 1) * 0.1)` → position 1=1.0, position 10=0.1, position 11+=0.0
  - Freshness weight redistributed proportionally to relevance+authority when `freshness_score` is None
  - Empty/whitespace-only snippet short-circuits to composite_score=0.0
- **`QualityScorer.infer_source_type(url) -> str`** — ordered substring matching on netloc; categories: documentation, forum, news, repository, blog, wiki, unknown
- **`deduplicate_results(results, threshold=0.85) -> List[ScoredResult]`** — O(n²) dedup using `rapidfuzz.fuzz.token_sort_ratio`; sorts by composite_score desc before comparing so highest-scored result survives; lazy import fallback returns input unchanged if rapidfuzz missing

### tests/test_quality_scorer.py (463 lines, 32 tests)

32 tests across 7 test classes covering all 8 required behaviors.

## Verification

```
python3 -m pytest tests/test_quality_scorer.py -x -v
32 passed in 0.89s

python3 -c "from quality_scorer import QualityScorer, ScoredResult, deduplicate_results; print('imports OK')"
imports OK

Position 1 composite: 0.71
Position 10 composite: 0.575
Position 1 > Position 10: True
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] rapidfuzz not installed in environment**
- **Found during:** Task 1 GREEN (first test run — 23/32 tests passed, dedup tests failed with ImportError triggering silent fallback)
- **Issue:** `rapidfuzz` was not installed in the system Python environment; the lazy import fallback caused dedup tests to return input unchanged instead of deduplicating
- **Fix:** Installed `rapidfuzz>=3.0.0` via pip and added it to `requirements.txt` under "Phase 2" section
- **Files modified:** requirements.txt
- **Commit:** 84eb857 (included in same feat commit)

## Known Stubs

None — QualityScorer is fully wired with real computation. No placeholder data or hardcoded empty values flow to callers.

## Self-Check: PASSED
