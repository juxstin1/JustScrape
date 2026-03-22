---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: search-quality
status: stable
stopped_at: All 4 audit waves complete — 27 fixes shipped
last_updated: "2026-03-22T23:00:00.000Z"
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 5
  completed_plans: 5
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-22)

**Core value:** Return the exact relevant snippet, not just a page
**Current focus:** Stable — audit complete, Phase 03 (Advanced Features) next

## Current Position

Phase: 02 (pipeline-integration) — COMPLETE + HARDENED
Audit: 4 waves complete (28 findings, 27 fixed)
Next: Phase 03 (advanced-features) — neural re-ranking, intelligent retry

## What's Live

- **Quality Pipeline**: QueryAnalyzer → SearXNG → ResultReranker → Scrape + SnippetExtractor → QualityScorer → Dedup
- **Search Backend**: Self-hosted SearXNG (Docker) — Google + Bing + 70 engines, no rate limits
- **Snippet-only responses**: ~1,000 tokens per search (was ~5,200)
- **Relevance scores**: 0.63–0.87 range (was ~0.29 before audit fixes)
- **Provenance metadata**: source_type, detected_date, confidence, score_breakdown on every result
- **Input hardened**: bad types coerced, operator injection blocked, SSRF via redirects blocked
- **215 tests passing**

## Audit Summary (2026-03-22)

3-team parallel audit: search quality, scraping resilience, security.

| Wave | Scope | Fixes | Key Wins |
|------|-------|-------|----------|
| 1 — Critical | Crashes + security | 5 | SSRF redirect block, OOM cap, robots.txt hang fix |
| 2 — Quality | Wrong results | 10 | Plain text detection (0.29→0.70), intent fix, date parser fix |
| 3 — Security | Hardening | 6 | Operator injection, cache poisoning, error sanitization |
| 4 — Polish | Efficiency | 6 | Semaphore scope, dead code removal, Playwright timeout |

## Decisions

- [Init]: Free APIs only — no paid search APIs
- [Init]: Quality-only scope — no architecture refactoring
- [Init]: AI-first design — primary consumers are AI models via MCP
- [Phase 01]: Subdomain matching uses two-step lookup (exact netloc then base domain)
- [Phase 01]: Freshness scoring gated on _FRESHNESS_INTENTS set
- [Phase 02]: DuckDuckGo removed — SearXNG is the only backend
- [Phase 02]: Content field returns extracted snippets only, not full page dumps
- [Audit]: Plain text detection in SnippetExtractor — biggest single quality win
- [Audit]: Confidence baseline reduced to +0.1 (was +0.3) — better signal fidelity
- [Audit]: ccTLD handling for authority lookup — known two-label TLD set

## Blockers/Concerns

- [Phase 3]: Optimal reformulation trigger thresholds need validation against real SearXNG behavior
- [Phase 3]: Snippet window size for cross-encoder input quality is an open question
- 0.00 scores still appear when snippet extraction finds nothing relevant — needs fallback scoring

## Session Continuity

Last session: 2026-03-22
Stopped at: All 4 audit waves complete — 27 fixes shipped
Resume file: None
