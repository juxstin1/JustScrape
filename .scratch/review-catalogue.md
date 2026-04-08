# JustScrape Review Catalogue

Living catalogue of bugs, suggested tickets, and review iteration state.
Update this file after each pass. Append new findings; do not delete history — strike through resolved items.

## Iteration Log
- 2026-04-07 — Pass 1 (claude/fix-runover-PAuZc): initial sweep of `src/justscrape/`. 10 findings filed as GH issues. See "Findings" below for issue links once created.

## Searched / To Search
- [x] src/justscrape/web_scraper.py (RobotsCache, session lifecycle)
- [x] src/justscrape/async_scraper.py (semaphore cache, gather)
- [x] src/justscrape/browser_pool.py (page/context cleanup)
- [x] src/justscrape/handlers/research.py (gather error handling)
- [ ] src/justscrape/url_validator.py — SSRF DNS timeout, redirect revalidation
- [ ] src/justscrape/snippet_extractor.py — sklearn/BM25 exception scope
- [ ] src/justscrape/sitemap_registry.py — defusedxml usage, file perms
- [ ] src/justscrape/quality_scorer.py — dedup edge cases (empty corpora)
- [ ] src/justscrape/backends/searxng.py — timeout/error mapping
- [ ] src/justscrape/server.py — MCP cache TTL paths, lazy imports
- [ ] tests/ — coverage gaps for race-condition prone modules

## Findings (Pass 1)
| # | Sev | File:Line | Summary | Issue |
|---|-----|-----------|---------|-------|
| 1 | HIGH | web_scraper.py:105-107 | RobotsCache eviction picks `next(iter)` not oldest by ts | #40 |
| 2 | HIGH | async_scraper.py:206 | `scrape_many` uses `return_exceptions=False` — one failure kills batch | #41 |
| 3 | HIGH | async_scraper.py:42-48 | `_get_domain_semaphores` mutates module dict without async lock; same eviction bug | #42 |
| 4 | HIGH | web_scraper.py session(s) | `requests.Session()` instances created and never closed (FD leak) | #43 |
| 5 | HIGH | browser_pool.py | Playwright page/context not guaranteed closed on goto/extract failure | #44 |
| 6 | MED  | web_scraper.py:82-84 | Defensive tuple unpack pattern is fragile; prefer `rp, ts = entry` | (folded into #45) |
| 7 | MED  | web_scraper.py:79-108 | TOCTOU between TTL check and fetch — duplicate robots.txt I/O under load | #45 |
| 8 | MED  | web_scraper.py ad_patterns | `re.compile` inside hot loop for ad pattern matching | #47 |
| 9 | MED  | web_scraper.py:97-99 | robots.txt decoded as utf-8 with `errors="replace"` (RFC: ISO-8859-1) | #46 |
| 10| LOW  | handlers/research.py gather | `asyncio.gather` without `return_exceptions=True` in enrichment | #48 |

Tracking issue: #49

## Improvement Tickets (non-bug)
- T1: Global pooled `requests.Session` shared across `WebScraper` instances
- T2: `asynccontextmanager` wrapper for pooled browser lifecycle
- T3: Structured logging for cache evictions (domain, reason, age)
- T4: Centralize SSRF/url validation as a single pre-flight gate
- T5: Per-domain circuit breaker for repeatedly-failing hosts

## Review Loop Protocol
1. Pick next unchecked item in "Searched / To Search".
2. Read file end-to-end; verify line numbers before filing.
3. Append finding rows; create GH issue; backfill issue link in table.
4. Commit catalogue update on `claude/fix-runover-PAuZc` with message `chore(review): pass N catalogue update`.
5. When fixing a finding, link the PR back here and strike through the row.
