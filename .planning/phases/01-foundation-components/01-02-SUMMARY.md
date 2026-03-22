---
phase: 01-foundation-components
plan: "02"
subsystem: result-reranker
tags: [tdd, authority-scoring, freshness, ranking, search-quality]
dependency_graph:
  requires: []
  provides: [result_reranker.ResultReranker, result_reranker.RankedResult]
  affects: [phase-02-integration, smart_scraper.py consumer]
tech_stack:
  added: [python-dateutil fuzzy date parsing]
  patterns: [dataclass-containers, module-level-constant-dicts, tdd-red-green]
key_files:
  created:
    - result_reranker.py
    - tests/test_result_reranker.py
  modified: []
decisions:
  - "Subdomain matching uses two-step lookup: exact netloc first, then base domain (last 2 labels) — handles docs.python.org -> 1.0 via docs.python.org key in tier map"
  - "Unknown domains always return 0.5 per Pitfall 6 — never 0.0 even for general query type"
  - "Freshness gated on _FRESHNESS_INTENTS set — extensible for future 'current-events' intent without modifying logic"
  - "dateutil fuzzy parse sanitized with future-date guard to prevent artifacts"
metrics:
  duration: "2 minutes"
  completed_date: "2026-03-22"
  tasks_completed: 2
  files_changed: 2
requirements:
  - RANK-01
  - RANK-02
---

# Phase 01 Plan 02: ResultReranker — Authority Scoring and Freshness Weighting Summary

**One-liner:** Query-type-aware authority tier maps (code/research/news) with exponential freshness decay for news-only intents, implemented via TDD with 24 passing tests.

## What Was Built

`result_reranker.py` at project root implements `ResultReranker` and `RankedResult` as standalone quality modules. The reranker re-orders search results by source quality so higher-authority sources are scraped first, reducing wasted effort on low-value pages.

### Key Components

**`RankedResult` dataclass** — Enriched search result container with `url`, `title`, `snippet`, `original_position`, `authority_score`, `freshness_score`, `is_blocked`.

**`AUTHORITY_TIERS`** — Module-level dict of per-intent tier maps:
- `code`: stackoverflow.com, github.com, docs.python.org → 1.0; geeksforgeeks.org → 0.8; medium.com → 0.2
- `research`: arxiv.org, wikipedia.org, nature.com → 1.0
- `news`: reuters.com, apnews.com, bbc.com → 1.0; nytimes.com, techcrunch.com → 0.8
- `general`: empty dict (all unknowns fall through to 0.5 default)

**`BLOCKED_DOMAINS`** — answers.com, ehow.com, ask.com, quora.com, pinterest.com, scribd.com, brighthub.com. Blocked domains return 0.0 and `is_blocked=True`.

**`ResultReranker.get_authority_score(url, query_type)`** — Two-step lookup (exact netloc then base domain), www stripping, 0.5 default for unknowns.

**`ResultReranker.get_freshness_score(snippet, query_type)`** — Returns None for code/research intents. For news: dateutil fuzzy parse from snippet, linear decay `1.0 - days/30`, 0.3 penalty when no date found.

**`ResultReranker.rerank(results, query_type)`** — Converts list of dicts to RankedResult list sorted by authority descending, blocked entries pushed to bottom.

## Tests

`tests/test_result_reranker.py` — 24 tests across 4 classes:
- `TestAuthorityScoring` (11 tests): RANK-01 coverage including subdomain, www-stripping, blocked, unknown
- `TestFreshnessScoring` (6 tests): RANK-02 coverage including news decay, code/research None, undated penalty
- `TestReranking` (4 tests): original_position preservation, sort order, blocked marking, return type
- `TestRankedResultDataclass` (3 tests): all field variants

All 24 tests pass.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all fields are wired and computed from real inputs.

## Self-Check: PASSED
