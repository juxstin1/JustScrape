---
phase: 01-foundation-components
plan: 01
subsystem: query-analysis
tags: [tdd, query-analyzer, intent-classification, entity-extraction, no-ml]
dependency_graph:
  requires: []
  provides: [QueryAnalyzer, AnalyzedQuery]
  affects: [reranker, extractor, smart_scraper]
tech_stack:
  added: []
  patterns: [compiled-regex-at-module-level, dataclass-containers, type-hints]
key_files:
  created:
    - query_analyzer.py
    - tests/test_query_analyzer.py
  modified: []
decisions:
  - "Zero ML dependencies: all classification via compiled regex + lookup tables (D-01)"
  - "How-to and comparison patterns get signal boost (3x, 2x) to win over incidental keyword matches"
  - "Zero-match queries return ('general', 0.5) rather than ('lookup', 0.5) so D-03 general fallback applies consistently"
metrics:
  duration_seconds: 142
  completed_date: "2026-03-22"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
requirements:
  - QUERY-01
  - QUERY-02
  - QUERY-03
  - QUERY-04
---

# Phase 01 Plan 01: QueryAnalyzer Foundation Summary

**One-liner:** Rules-based query analyzer with regex intent classification (6 intents), abbreviation/term expansion, conjunction decomposition, and regex entity extraction — zero ML dependencies.

## What Was Built

`query_analyzer.py` at project root exports `QueryAnalyzer` and `AnalyzedQuery`. The module implements all four QUERY requirements using only Python stdlib:

- **QUERY-01 (classify_intent):** Six compiled regex patterns at module level (`_CODE_PATTERN`, `_NEWS_PATTERN`, `_HOW_TO_PATTERN`, `_RESEARCH_PATTERN`, `_COMPARISON_PATTERN`, `_LOOKUP_PATTERN`). Match counts per intent, with signal boosting for structural indicators (how-to 3x, comparison 2x). Confidence < 0.7 returns "general" per D-03.
- **QUERY-02 (expand_query):** 12-entry abbreviation map (JS, TS, ML, AI, SQL, k8s, etc.) + 12-entry term expansion map (react hooks, docker, git, etc.). Original query always first.
- **QUERY-03 (decompose_query):** Single `_CONJUNCTION_PATTERN` splits on `and`, `vs`, `or`, `compared to` only. Returns `[query]` when no conjunction found.
- **QUERY-04 (extract_entities):** `_VERSION_PATTERN` for semantic versions, `_LANGUAGE_NAMES` set (24 languages), `_LIBRARY_NAMES` set (40 libraries). Span tracking prevents duplicate entities.

`tests/test_query_analyzer.py` contains 19 tests across 5 test classes covering all QUERY requirements.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Zero-match fallback returned "lookup" instead of "general"**
- **Found during:** Task 2 GREEN phase (test_low_confidence_returns_general failure)
- **Issue:** The zero-match fallback returned `("lookup", 0.5)` — confidence 0.5 < 0.7 triggers D-03 but intent was already set to "lookup" before the check ran
- **Fix:** Changed zero-match fallback to return `("general", 0.5)` — consistent with D-03 semantics
- **Files modified:** query_analyzer.py
- **Commit:** f00a0d5

**2. [Rule 1 - Bug] How-to intent beaten by incidental code keyword matches**
- **Found during:** Task 2 GREEN phase (test_howto_intent failure)
- **Issue:** "how to debug python exception" classified as "code" because `_CODE_PATTERN` matched more tokens (debug, exception) than `_HOW_TO_PATTERN` (how to)
- **Fix:** Added signal boosting — how-to matches multiplied by 3 (structural indicator), comparison by 2 — so structural query patterns win over incidental domain keywords
- **Files modified:** query_analyzer.py
- **Commit:** f00a0d5

## Known Stubs

None — all required functionality is implemented and all tests pass.

## Self-Check

- query_analyzer.py: FOUND
- tests/test_query_analyzer.py: FOUND
- Commit 3636d99 (test RED): FOUND
- Commit f00a0d5 (feat GREEN): FOUND

## Self-Check: PASSED
