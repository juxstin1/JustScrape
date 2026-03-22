---
phase: 1
slug: foundation-components
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-21
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (no config file — runs with defaults) |
| **Config file** | none — existing tests run without config |
| **Quick run command** | `pytest tests/test_query_analyzer.py tests/test_result_reranker.py tests/test_snippet_extractor.py -x -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_query_analyzer.py tests/test_result_reranker.py tests/test_snippet_extractor.py -x -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | 01 | 1 | QUERY-01 | unit | `pytest tests/test_query_analyzer.py -k intent -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | QUERY-02 | unit | `pytest tests/test_query_analyzer.py -k expand -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | QUERY-03 | unit | `pytest tests/test_query_analyzer.py -k decompose -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | QUERY-04 | unit | `pytest tests/test_query_analyzer.py -k entity -q` | ❌ W0 | ⬜ pending |
| TBD | 02 | 1 | RANK-01 | unit | `pytest tests/test_result_reranker.py -k authority -q` | ❌ W0 | ⬜ pending |
| TBD | 02 | 1 | RANK-02 | unit | `pytest tests/test_result_reranker.py -k freshness -q` | ❌ W0 | ⬜ pending |
| TBD | 03 | 1 | EXTRACT-01 | unit | `pytest tests/test_snippet_extractor.py -k trafilatura -q` | ❌ W0 | ⬜ pending |
| TBD | 03 | 1 | EXTRACT-02 | unit | `pytest tests/test_snippet_extractor.py -k chunk -q` | ❌ W0 | ⬜ pending |
| TBD | 03 | 1 | EXTRACT-03 | unit | `pytest tests/test_snippet_extractor.py -k score -q` | ❌ W0 | ⬜ pending |
| TBD | 03 | 1 | EXTRACT-04 | unit | `pytest tests/test_snippet_extractor.py -k semantic -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_query_analyzer.py` — stubs for QUERY-01..04
- [ ] `tests/test_result_reranker.py` — stubs for RANK-01..02
- [ ] `tests/test_snippet_extractor.py` — stubs for EXTRACT-01..04
- [ ] `pip install trafilatura rank-bm25` — new dependencies
- [ ] Update `requirements.txt` with new dependencies

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
