# JustScrape — God-Status Web Search for AI

## What This Is

JustScrape is an MCP server that gives AI models (Claude, GPT, etc.) web search and scraping capabilities. The goal is to make it the best free web search tool for AI — better results than Perplexity, Tavily, or Exa, without requiring paid API keys. When an AI calls `search_and_scrape`, it should get back exactly the relevant snippet it needs, not a wall of scraped text or irrelevant pages.

## Core Value

**Return the exact relevant snippet, not just a page.** Every search should deliver precisely what the AI needs to answer the user's question — the right source, the right section, clean and ready to use.

## Requirements

### Validated

- ✓ Static web scraping with content extraction — existing
- ✓ JavaScript rendering via Playwright — existing
- ✓ Async HTTP/2 scraping via httpx — existing
- ✓ Multi-backend search (DuckDuckGo, SearXNG, Brave) — existing
- ✓ Content classification (usable/thin/blocked/empty) — existing
- ✓ 2-layer caching (memory + SQLite) — existing
- ✓ Per-domain rate limiting — existing
- ✓ SSRF protection and URL validation — existing
- ✓ Sitemap-based URL discovery — existing
- ✓ Source-specific adapters (Wikipedia, GitHub, SO, etc.) — existing
- ✓ MCP server with 4 tools — existing
- ✓ Query-type detection — rules-based intent classification (code/research/news/how-to/lookup/comparison) — Phase 1
- ✓ Smart query reformulation — expansion with synonyms, related terms, abbreviation resolution — Phase 1
- ✓ Source authority scoring — 5-tier query-type-aware domain authority maps — Phase 1
- ✓ Snippet-level extraction — trafilatura + hybrid chunking + BM25/TF-IDF scoring — Phase 1
- ✓ Precision content extraction — sentence-level semantic matching for exact answers — Phase 1
- ✓ Domain-aware search strategies — per-query-type authority maps and freshness weighting — Phase 1

### Active

- [ ] Multi-source synthesis — combine information from multiple pages into a coherent answer
- [ ] Relevance-based result ranking — composite scoring wired into live pipeline
- [ ] Result quality scoring — score each result on relevance, freshness, authority before returning
- [ ] Intelligent retry with reformulation — when results are poor, automatically reformulate and retry

### Out of Scope

- Paid API integrations — must stay free (DuckDuckGo, SearXNG, free sources only)
- Human-facing UI/CLI improvements — this is AI-first, MCP-only focus
- Architecture/packaging cleanup — not touching plumbing, purely search quality
- Building a general-purpose web browser — we extract and return, not navigate
- Real-time streaming of results — MCP tools return complete responses

## Context

- Existing codebase: ~8,600 lines of Python across 11 modules + 11 test files
- Architecture: layered (MCP server → SmartScraper → scraper engines) with search backends
- Current search backends: DuckDuckGo (free, default), SearXNG (self-hosted), Brave (API key)
- Known issues: results are often irrelevant to the actual query intent; scraped content is noisy
- Benchmark: Context7's ability to find the exact documentation snippet from a vague query
- Competitors to beat: Perplexity (paid), Tavily (paid API), Exa (paid API)
- Target users: AI models calling via MCP — results must be AI-consumable
- Use cases: coding answers, research deep-dives, current events — all three equally important

## Constraints

- **Cost**: No paid APIs — all search and scraping must use free sources
- **Interface**: MCP protocol — all improvements surface through existing/new MCP tools
- **Scope**: Search quality only — no architecture refactoring, no packaging changes
- **Compatibility**: Must maintain backward compatibility with existing MCP tool signatures

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Free APIs only | User constraint — no budget for paid search APIs | — Pending |
| Quality-only scope | User wants results improvement, not code cleanup | — Pending |
| AI-first design | Primary consumers are AI models via MCP, not humans | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-21 after initialization*
