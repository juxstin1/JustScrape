# Pitfalls Research: AI-Powered Search Quality

**Domain:** Building intelligent search on free APIs
**Project:** JustScrape — search quality milestone
**Researched:** 2026-03-21
**Confidence:** HIGH (derived from direct codebase analysis)

---

## Critical Pitfalls

### P1: Query reformulation loops without termination guards
**Severity:** Critical
**Phase:** Query reformulation / intelligent retry

**The Problem:** A reformulation retry loop with no max-attempts or quality-floor exit condition can loop indefinitely on queries with no good results. Combined with DDG's silent throttling (P3), this burns through all backends producing nothing useful.

**Warning Signs:**
- Latency spikes >10s on single queries
- Backend error rates climbing during sessions
- Zero-result responses after multiple retries

**Prevention:**
- Hard cap: max 3 reformulation attempts per query
- Quality floor: if best result scores >0.3, stop reformulating
- Backend budget: track queries-per-session, stop when budget exhausted
- Timeout: total wall-clock cap of 15s for entire reformulation chain

### P2: Relevance scoring that rewards length over relevance
**Severity:** Critical
**Phase:** Relevance ranking

**The Problem:** The current `relevance_score` in `web_search.py` has a 20% length weight. Long tangentially-relevant pages outrank short precise answers — directly undermining the "exact snippet, not a wall of text" goal.

**Warning Signs:**
- Long Wikipedia articles consistently ranked #1 regardless of query
- Short, precise documentation pages ranked low
- Users report "too much irrelevant content"

**Prevention:**
- Remove or invert length weight in new scoring formula
- Score on snippet relevance (post-extraction), not full-page length
- Penalize results where relevant snippet is <5% of total page content

### P3: DuckDuckGo silent rate-limiting (zero results, success=True)
**Severity:** Critical
**Phase:** Query reformulation

**The Problem:** DDG returns `success=True` with `total_results=0` when rate-limited, not an error. The reformulation loop sees "no results" and reformulates, burning more queries against a throttled backend.

**Warning Signs:**
- Sudden drop from normal result counts to zero
- Multiple consecutive zero-result queries
- Pattern of zero results followed by recovery after delay

**Prevention:**
- Detect zero-result pattern: 2+ consecutive zero-results = suspected throttle
- Back off DDG for 60s on suspected throttle, switch to SearXNG
- Never reformulate against a backend returning zero results — switch backends first

### P4: Source-specific adapters breaking silently
**Severity:** Critical
**Phase:** All scraping phases

**The Problem:** The source adapters in `smart_scraper.py` (StackExchange, Reddit, dev.to, GitHub, Wikipedia, etc.) use hardcoded selectors/patterns. When sites change HTML, adapters return empty/garbage silently. The fallback path for these exact sites is blocked (they're in JS_HEAVY_DOMAINS or have anti-scraping).

**Warning Signs:**
- Adapter returning empty content where it previously returned good content
- Increase in "thin" classifications for previously-reliable domains
- No errors in logs — just degraded quality

**Prevention:**
- Health check: validate adapter output has minimum content length
- Staleness detection: if adapter output quality drops, log warning and fall back to generic scraping
- Don't hard-fail on adapter — always have generic fallback path

---

## Moderate Pitfalls

### P5: Query intent misclassification
**Severity:** Moderate
**Phase:** Query-type detection

**The Problem:** A code query misclassified as "news" gets routed to news sources. A news query classified as "research" gets stale academic results. Wrong classification cascades through the entire pipeline.

**Prevention:**
- Conservative defaults: when uncertain, classify as "general" (no specialized routing)
- Confidence threshold: only apply specialized routing when classification confidence >0.7
- Log classifications for debugging and tuning

### P6: Snippet extraction returning wrong page region
**Severity:** Moderate
**Phase:** Precision extraction

**The Problem:** Nav bars, footers, comment sections, and "related articles" contain keywords that match the query. Without proper content zone detection, the "best snippet" comes from page chrome, not the article body.

**Prevention:**
- Use trafilatura for body extraction BEFORE snippet scoring
- Exclude known non-content zones (nav, footer, sidebar, comments)
- Validate snippet makes sense standalone (not a sentence fragment)

### P7: Re-ranking that discards search engine position signal
**Severity:** Moderate
**Phase:** Relevance ranking

**The Problem:** Completely replacing DDG's ranking with custom scoring throws away valuable signal. DDG's ranking, while imperfect for AI use, encodes click-through data and quality signals we don't have.

**Prevention:**
- Include original position as one signal in composite score (decaying weight)
- Re-rank, don't replace: adjust positions, don't ignore them entirely
- Weight: ~15-20% for original position in composite score

### P8: Brave Search quota burn from reformulation
**Severity:** Moderate
**Phase:** Multi-source synthesis

**The Problem:** Brave's free tier is 2,000 queries/month. If Brave becomes a reformulation fallback backend, a single session with aggressive retry can burn 50+ queries.

**Prevention:**
- Per-session query budget tracking per backend
- Brave: max 10 queries per session, max 100 per day
- Prefer DDG/SearXNG for reformulation; reserve Brave for primary queries only

### P9: Boilerplate content in extraction (cookies, nav, "you might also like")
**Severity:** Moderate
**Phase:** Precision extraction

**The Problem:** Many pages have "Accept cookies", "Subscribe to newsletter", or "You might also like" sections that survive basic HTML cleaning and pollute extracted text.

**Prevention:**
- Trafilatura handles most boilerplate removal
- Additional regex filters for common boilerplate patterns
- Minimum snippet quality: reject snippets that are >50% boilerplate keywords

---

## Minor Pitfalls

### P10: Hardcoded stop-word removal breaking code queries
**Severity:** Minor
**Phase:** Query rewriting

**The Problem:** Stop-word removal that strips "is", "in", "for", "not" breaks code queries like "is in python", "for loop javascript", "not null sql".

**Prevention:**
- Code-intent queries: skip stop-word removal entirely
- Use query-type detection BEFORE any query rewriting

### P11: Rate limiter sleep() inside executor threads
**Severity:** Minor
**Phase:** All phases with parallel scraping

**The Problem:** `PerDomainRateLimiter` in `web_scraper.py` uses `time.sleep()` inside `ThreadPoolExecutor` threads. Under `asyncio.gather` parallelism, multiple threads targeting the same domain create compounding delays.

**Prevention:**
- For async paths, use asyncio.sleep in async rate limiter
- For sync paths, current approach is acceptable

### P12: Cache key collision from operator normalization
**Severity:** Minor
**Phase:** Caching

**The Problem:** Query operators like `site:` and date ranges may be normalized inconsistently between search backends, leading to cache misses for equivalent queries or cache hits returning wrong-backend results.

**Prevention:**
- Normalize query before cache key generation
- Include backend name in cache key

---
*Researched: 2026-03-21*
