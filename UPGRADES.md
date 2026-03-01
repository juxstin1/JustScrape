# JustScrape — Free Web Search Efficiency Upgrades

Current state: JustScrape v1 uses a single search backend (DuckDuckGo), sequential scraping, in-memory caching, and global rate limiting. It works, but leaves significant performance and reliability on the table — all fixable without paid APIs.

This document catalogs concrete upgrades organized by impact and complexity.

---

## 1. Multiple Free Search Backends

**Problem:** DuckDuckGo is the only search source. When it rate-limits or returns thin results for a query, there's nowhere to fall back except HTML scraping of the same engine.

**Upgrade:** Add a search backend abstraction and plug in additional free engines.

| Backend | Method | Free Tier | Notes |
|---------|--------|-----------|-------|
| **SearXNG** | Self-hosted instance | Unlimited | Meta-search across 70+ engines. Best long-term option. Requires a server or local Docker container. |
| **Brave Search API** | REST API | 2,000 queries/month | Independent index, high quality. Free tier is generous for personal/MCP use. |
| **Google (via `googlesearch-python`)** | HTML scraping | No official limit | Fragile — Google changes HTML frequently. Use as a fallback, not primary. |
| **Mojeek API** | REST API | 1,000 queries/month | Fully independent crawler-based index. Good for diversity. |
| **Qwant** | HTML scraping | No official limit | EU-based, privacy-focused. Different result set than DDG. |

**Implementation sketch:**

```python
class SearchBackend:
    """Base class for search backends"""
    name: str
    def search(self, query: str, num_results: int) -> SearchResponse: ...

class DuckDuckGoBackend(SearchBackend): ...
class BraveSearchBackend(SearchBackend): ...
class SearXNGBackend(SearchBackend): ...

class MultiSearch:
    """Routes queries across backends with fallback"""
    def __init__(self, backends: list[SearchBackend]):
        self.backends = backends

    def search(self, query, num_results=10):
        for backend in self.backends:
            result = backend.search(query, num_results)
            if result.success and result.total_results > 0:
                return result
        return SearchResponse(...)  # all failed
```

**Files affected:** `web_search.py` (refactor into backend pattern), new `backends/` directory.

**Effort:** Medium. The current `WebSearch` class already has the right interface — it just needs to become one backend among many.

---

## 2. Parallel Scraping of Search Results

**Problem:** `search_and_scrape` and `research_with_sources` scrape results one at a time. Scraping 5 URLs sequentially with a 1-second rate limit = 5+ seconds minimum, often 15-30 seconds total with network latency.

**Upgrade:** Scrape search results concurrently using `asyncio` or `concurrent.futures`.

**Key constraints:**
- Rate limit *per domain*, not globally — scraping 5 different domains in parallel is safe
- Keep a global concurrency cap (e.g., 5 simultaneous requests) to avoid resource exhaustion
- The MCP server already runs async (`justscrape_mcp.py` uses `asyncio`) — use `asyncio.gather` for parallel scrapes

**Implementation sketch:**

```python
async def handle_search_and_scrape(arguments):
    # Search (fast, single request)
    search_result = await run_in_executor(search_full, query, num_results)

    # Scrape all results in parallel
    scrape_tasks = [
        run_in_executor(scraper.scrape_to_dict, r["url"])
        for r in search_result["results"]
    ]
    scraped = await asyncio.gather(*scrape_tasks, return_exceptions=True)
```

**Projected improvement:** 3-5x faster for `search_and_scrape` calls with multiple results. A 5-result query that takes 20 seconds sequentially finishes in ~5 seconds.

**Files affected:** `justscrape_mcp.py` (async gather), `worker.py` (ThreadPoolExecutor), `smart_scraper.py` (per-domain rate limiting).

**Effort:** Low-medium. The async plumbing already exists in the MCP server — just needs `gather` instead of sequential awaits.

---

## 3. Persistent Search Cache (SQLite)

**Problem:** The current `SearchCache` is in-memory with a 5-minute TTL and 100-entry cap. Every server restart loses all cached results. Repeated research sessions re-fetch the same queries.

**Upgrade:** SQLite-backed persistent cache alongside the in-memory hot cache.

**Design:**
- L1: In-memory TTL cache (current, for hot results — 5 min TTL)
- L2: SQLite persistent cache (new — 24-hour TTL, configurable)
- On miss in L1, check L2 before hitting the network
- On successful search, write to both L1 and L2

```
Request → L1 (memory, 5m) → L2 (SQLite, 24h) → Network
```

**Why it matters:** MCP servers restart frequently (Claude Desktop restarts them on config changes, crashes, etc.). A persistent cache survives restarts and avoids burning DuckDuckGo rate limits on repeated queries across sessions.

**Bonus:** The project already uses SQLite for the sitemap registry (`sitemap_registry.py`) — the pattern is established.

**Files affected:** `web_search.py` (add `PersistentSearchCache` class).

**Effort:** Low. SQLite write is ~1ms, read is <1ms. Minimal overhead.

---

## 4. Per-Domain Rate Limiting

**Problem:** The current `RateLimiter` is global — one delay counter for all requests. Scraping `realpython.com` throttles the next request to `wikipedia.org`, even though they're completely independent servers.

**Upgrade:** Track rate limits per domain.

```python
class PerDomainRateLimiter:
    def __init__(self, default_delay=1.0, max_delay=30.0):
        self._domains: dict[str, DomainState] = {}

    def wait(self, url: str):
        domain = urlparse(url).netloc
        state = self._domains.get(domain, DomainState(default_delay))
        # Only wait if recent request to THIS domain
        ...
```

**Impact:** When scraping results from different domains (the common case), requests can fire immediately without artificial delays. A 5-result scrape across 5 domains goes from 5+ seconds of rate-limit waiting to ~0 seconds.

**Files affected:** `web_search.py` (replace global `_rate_limiter`), `web_scraper.py` (add per-domain awareness).

**Effort:** Low.

---

## 5. Snippet-Based Pre-Filtering

**Problem:** `search_and_scrape` blindly scrapes every search result. Many results are clearly irrelevant, paywalled, or low-quality — information visible from the search snippet alone. Full scraping a page that returns `blocked` or `thin` wastes time.

**Upgrade:** Score search results by snippet quality before committing to a full scrape.

**Signals available without scraping:**
- **Domain reputation** — known blocked domains (Medium, Reddit, LinkedIn) can be skipped or deprioritized
- **Snippet length** — very short snippets often indicate thin pages
- **URL patterns** — `/login`, `/signup`, `/terms`, `/privacy` are rarely useful content
- **Snippet keyword overlap** — does the snippet actually contain query-relevant terms?

```python
def should_scrape(result: SearchResult, query: str) -> tuple[bool, str]:
    """Decide if a search result is worth scraping."""
    domain = urlparse(result.url).netloc.lower()

    # Skip known-blocked domains
    if domain in KNOWN_BLOCKED_DOMAINS:
        return False, f"blocked_domain:{domain}"

    # Skip login/signup/legal pages
    path = urlparse(result.url).path.lower()
    if any(p in path for p in ['/login', '/signup', '/terms', '/privacy', '/cookie']):
        return False, f"skip_path:{path}"

    return True, "ok"
```

**Impact:** Avoids wasting 3-10 seconds per blocked/useless result. On a 5-result `search_and_scrape`, this commonly saves 1-3 scrape attempts.

**Files affected:** `justscrape_mcp.py`, `worker.py` (add pre-filter step before scrape loop).

**Effort:** Low.

---

## 6. HEAD Request Pre-Check

**Problem:** The scraper commits to a full GET request (downloading the entire page body) before discovering the response is a redirect chain to a login wall, a 403, or a 50MB PDF.

**Upgrade:** Send a lightweight `HEAD` request first to check status code, content-type, and content-length before committing to a full download.

**What HEAD reveals:**
- **Status code** — 403/401/429 means don't bother with GET
- **Content-Type** — `application/pdf`, `image/*`, `video/*` aren't scrapeable HTML
- **Content-Length** — pages over 5MB are probably not articles
- **Redirect chain** — reveals login-wall redirects (e.g., `linkedin.com/login`)

```python
def pre_check(url: str) -> tuple[bool, dict]:
    """Lightweight HEAD check before full scrape."""
    resp = requests.head(url, allow_redirects=True, timeout=5)

    if resp.status_code in (401, 403, 429):
        return False, {"reason": f"status:{resp.status_code}"}

    content_type = resp.headers.get('content-type', '')
    if not any(t in content_type for t in ['text/html', 'text/plain', 'application/xhtml']):
        return False, {"reason": f"content_type:{content_type}"}

    return True, {"final_url": resp.url, "status": resp.status_code}
```

**Impact:** Saves 2-15 seconds per avoided scrape. HEAD requests complete in <500ms.

**Files affected:** `web_scraper.py` (add `pre_check` to `WebScraper.fetch`), `smart_scraper.py`.

**Effort:** Low.

---

## 7. Connection Pooling and HTTP/2

**Problem:** `WebScraper` creates a `requests.Session` but scraping multiple results still negotiates separate TCP connections. The session does connection pooling within a domain, but not across a batch of diverse URLs efficiently.

**Upgrade:** Switch to `httpx` with HTTP/2 support and async-native design.

**Benefits:**
- **HTTP/2 multiplexing** — multiple requests over a single connection to the same host
- **Async-native** — fits naturally with the MCP server's `asyncio` event loop instead of `run_in_executor`
- **Connection pooling** — configurable pool limits across all domains
- **Better timeout handling** — separate connect/read/write/pool timeouts

```python
import httpx

class AsyncWebScraper:
    def __init__(self):
        self.client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=httpx.Timeout(connect=5, read=15, write=5, pool=10),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10)
        )
```

**Impact:** Eliminates `run_in_executor` overhead in the MCP server. Reduces connection setup latency. HTTP/2 multiplexing helps when scraping multiple pages from the same domain (e.g., multiple Wikipedia articles).

**Files affected:** `web_scraper.py` (rewrite fetch layer), `justscrape_mcp.py` (remove executor wrapping).

**Effort:** Medium. Requires changing the HTTP layer but the scraping/extraction logic stays the same.

---

## 8. Search Result Deduplication and Merging

**Problem:** When using multiple search backends (upgrade #1), the same URL may appear in results from different engines. Additionally, different engines may surface different useful results — merging them gives better coverage.

**Upgrade:** Deduplicate by URL and merge result metadata across backends.

**Strategy:**
- Normalize URLs before comparison (strip tracking params like `utm_*`, `ref`, trailing slashes)
- When the same URL appears from multiple backends, keep the best snippet (longest, most relevant)
- Interleave unique results from each backend (round-robin) for diversity
- Track which backends contributed each result (useful for debugging quality)

```python
def merge_results(backend_results: list[SearchResponse]) -> SearchResponse:
    seen_urls = {}
    merged = []

    for response in backend_results:
        for result in response.results:
            normalized = normalize_url(result.url)
            if normalized not in seen_urls:
                seen_urls[normalized] = result
                merged.append(result)
            else:
                # Keep longer snippet
                existing = seen_urls[normalized]
                if len(result.snippet) > len(existing.snippet):
                    existing.snippet = result.snippet

    return SearchResponse(results=merged, ...)
```

**Files affected:** `web_search.py` (add `merge_results` function, URL normalization).

**Effort:** Low (once multiple backends exist from upgrade #1).

---

## 9. Smarter Query Handling

**Problem:** Queries are passed to DuckDuckGo verbatim. No support for search operators, date filtering, or query reformulation when initial results are poor.

**Upgrade:** Add query preprocessing and operator support.

### 9a. Search Operator Support

Support common operators that DuckDuckGo (and other backends) understand:

```python
# Date-restricted search
search("python asyncio tutorial", date_range="past_year")

# Site-specific search
search("authentication best practices", site="docs.python.org")

# File type search
search("machine learning cheat sheet", filetype="pdf")

# Exclude domains
search("web scraping tutorial", exclude_sites=["w3schools.com"])
```

### 9b. Automatic Query Expansion

When initial search returns few results, try reformulated queries:

```python
def search_with_expansion(query, num_results=10):
    # Try original query first
    result = search(query, num_results)
    if result.total_results >= num_results:
        return result

    # Try without quotes
    expanded = query.replace('"', '')
    result2 = search(expanded, num_results)

    # Try with synonyms or simplified terms
    simplified = simplify_query(query)
    result3 = search(simplified, num_results)

    return merge_results([result, result2, result3])
```

**Files affected:** `web_search.py` (query preprocessing), `justscrape_mcp.py` (expose operator parameters in tool schema).

**Effort:** Low-medium.

---

## 10. Scrape Result Relevance Scoring

**Problem:** `search_and_scrape` returns all successfully scraped content with equal weight. The caller (LLM or user) has to figure out which scraped page actually answers their question. With 5 scraped results, there's often one highly relevant page and several tangential ones.

**Upgrade:** Score scraped content against the original query using lightweight text-matching heuristics (no LLM needed).

**Scoring signals:**
- **Query term frequency** — how often do query terms appear in the scraped content?
- **Title match** — does the page title contain query terms?
- **Content length** — longer, structured content is usually more useful than thin pages
- **Term proximity** — are query terms near each other in the content, or scattered?

```python
def relevance_score(query: str, content: str, title: str) -> float:
    """Score 0.0-1.0 for how relevant content is to query."""
    query_terms = set(query.lower().split())
    content_lower = content.lower()

    # Term frequency (normalized)
    term_hits = sum(content_lower.count(term) for term in query_terms)
    tf_score = min(term_hits / max(len(content.split()), 1) * 100, 1.0)

    # Title match
    title_lower = (title or "").lower()
    title_hits = sum(1 for term in query_terms if term in title_lower)
    title_score = title_hits / max(len(query_terms), 1)

    # Combined
    return 0.6 * tf_score + 0.4 * title_score
```

**Impact:** Results returned pre-sorted by relevance. The LLM can focus on the top result instead of reading all 5. Reduces token consumption when JustScrape feeds into a chat context.

**Files affected:** `worker.py` (add scoring to `research_with_sources`), `justscrape_mcp.py` (add scoring to `search_and_scrape`).

**Effort:** Low.

---

## 11. Robots.txt Awareness

**Problem:** JustScrape doesn't check `robots.txt` before scraping. This means:
- Requests to disallowed paths get blocked server-side anyway (wasted time)
- No signal about which paths are scrapeable before attempting

**Upgrade:** Fetch and cache `robots.txt` per domain. Use it as an efficiency signal (not just an ethical one).

```python
from urllib.robotparser import RobotFileParser

class RobotsCache:
    """Cache robots.txt per domain, check before scraping."""
    _cache: dict[str, RobotFileParser] = {}

    def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        domain = urlparse(url).netloc
        if domain not in self._cache:
            rp = RobotFileParser()
            rp.set_url(f"https://{domain}/robots.txt")
            rp.read()
            self._cache[domain] = rp
        return self._cache[domain].can_fetch(user_agent, url)
```

**Impact:** Avoids wasting 3-10 seconds on requests that will definitely be blocked. Also provides crawl-delay hints that can feed into per-domain rate limiting (upgrade #4).

**Files affected:** `web_scraper.py` (add robots check before fetch), new utility class.

**Effort:** Low. Python's `urllib.robotparser` handles the hard parts.

---

## 12. Lightweight Content-Length Fallback Tuning

**Problem:** The static-to-JS fallback threshold is hardcoded at 200 characters (`smart_scraper.py:33`). This is too aggressive — many legitimate short pages trigger unnecessary Playwright launches (expensive: ~3 seconds cold, ~1 second warm). Conversely, some blocked pages return 300+ characters of "please enable JavaScript" which passes the threshold.

**Upgrade:** Make the fallback smarter with a multi-signal decision.

**Proposed heuristics:**
- **Character count alone is insufficient** — combine with HTML structure signals
- **Check if the page has `<noscript>` content** — indicates JS-dependent rendering
- **Check for `<script>` tags relative to body content** — high script-to-text ratio suggests SPA
- **Configurable threshold per domain** — some sites always need JS, some never do

```python
def needs_javascript(html: str, content_length: int, url: str) -> bool:
    """Multi-signal decision for JS fallback."""
    # Known JS-heavy domains — always use JS
    if is_js_heavy_site(url):
        return True

    # Short content + noscript tag = likely needs JS
    soup = BeautifulSoup(html, 'html.parser')
    has_noscript = bool(soup.find('noscript'))
    script_count = len(soup.find_all('script'))

    if content_length < 200 and (has_noscript or script_count > 5):
        return True

    # Content with "enable JavaScript" patterns
    if content_length < 500 and re.search(r'enable javascript|requires javascript', html, re.I):
        return True

    return False
```

**Files affected:** `smart_scraper.py` (replace simple length check).

**Effort:** Low.

---

## 13. SearXNG Integration (Self-Hosted Meta-Search)

**Problem:** DuckDuckGo is a single point of failure for search. Its rate limits are per-IP and opaque — heavy usage from one machine triggers throttling with no clear backoff signal.

**Upgrade:** Deploy a local SearXNG instance and use it as the primary (or secondary) search backend.

**Why SearXNG:**
- Aggregates results from 70+ search engines (Google, Bing, DuckDuckGo, Brave, etc.)
- Self-hosted = no rate limits from third parties
- Returns deduplicated, merged results automatically
- JSON API out of the box (`/search?q=query&format=json`)
- Docker setup takes 5 minutes

**Deployment:**
```bash
docker run -d --name searxng -p 8080:8080 searxng/searxng
```

**Integration:**
```python
class SearXNGBackend(SearchBackend):
    name = "searxng"

    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url

    def search(self, query, num_results=10):
        resp = requests.get(f"{self.base_url}/search", params={
            "q": query,
            "format": "json",
            "categories": "general",
        })
        data = resp.json()
        results = [
            SearchResult(
                position=i+1,
                title=r["title"],
                url=r["url"],
                snippet=r.get("content", ""),
                source=f"searxng:{r.get('engine', 'unknown')}"
            )
            for i, r in enumerate(data.get("results", [])[:num_results])
        ]
        return SearchResponse(query=query, results=results, ...)
```

**Files affected:** New `backends/searxng.py`, `web_search.py` (add to backend chain).

**Effort:** Low (integration) + one-time Docker setup.

---

## 14. Async-Native MCP Tool Handlers

**Problem:** Every MCP tool handler in `justscrape_mcp.py` wraps synchronous code with `loop.run_in_executor`. This works but adds overhead and prevents true async benefits (like parallel scraping with `gather`).

**Upgrade:** Make the scraping and search layers async-native so the MCP handlers don't need executor wrapping.

**Current:**
```python
async def handle_web_search(arguments):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: search_full(query, num_results))
```

**Proposed:**
```python
async def handle_web_search(arguments):
    result = await async_search(query, num_results)
```

This unlocks:
- `asyncio.gather` for parallel search across backends
- `asyncio.gather` for parallel scraping of results
- `asyncio.wait_for` for per-request timeouts
- True async streaming of results as they complete

**Files affected:** `web_search.py` (add async interface), `web_scraper.py` (add async fetch with `httpx`), `justscrape_mcp.py` (simplify handlers).

**Effort:** Medium. Core change is switching `requests` to `httpx` async client.

---

## 15. DNS and TLS Caching

**Problem:** Every scrape request resolves DNS and negotiates TLS from scratch (or relies on `requests.Session` keep-alive which only helps same-domain). When scraping 5 different domains, that's 5 DNS lookups and 5 TLS handshakes.

**Upgrade:** Use a shared `httpx` client with explicit connection pooling and DNS caching.

- `httpx` with `http2=True` reuses connections aggressively
- Custom DNS resolver with caching (via `dnspython` or OS resolver cache)
- Pre-warm connections to commonly scraped domains

**Impact:** Saves 100-500ms per new domain in DNS + TLS overhead. Matters most when scraping many results quickly (upgrade #2).

**Files affected:** `web_scraper.py` (client initialization).

**Effort:** Low (mostly configuration of `httpx` client).

---

## Priority Matrix

| Upgrade | Impact | Effort | Dependencies |
|---------|--------|--------|-------------|
| **#2 Parallel scraping** | High | Low | None |
| **#4 Per-domain rate limiting** | High | Low | None |
| **#5 Snippet pre-filtering** | High | Low | None |
| **#6 HEAD pre-check** | Medium | Low | None |
| **#3 Persistent cache (SQLite)** | Medium | Low | None |
| **#10 Relevance scoring** | Medium | Low | None |
| **#12 Smarter JS fallback** | Medium | Low | None |
| **#11 Robots.txt awareness** | Low-Medium | Low | None |
| **#1 Multiple search backends** | High | Medium | None |
| **#9 Query operators/expansion** | Medium | Low-Medium | None |
| **#8 Result deduplication** | Medium | Low | #1 |
| **#13 SearXNG integration** | High | Low (code) | Docker host |
| **#14 Async-native handlers** | Medium | Medium | #7 |
| **#7 httpx + HTTP/2** | Medium | Medium | None |
| **#15 DNS/TLS caching** | Low | Low | #7 |

---

## Recommended Implementation Order

**Phase 1 — Quick wins (no new dependencies):**
1. Parallel scraping (#2)
2. Per-domain rate limiting (#4)
3. Snippet pre-filtering (#5)
4. HEAD pre-check (#6)
5. Persistent SQLite cache (#3)

**Phase 2 — Search quality:**
6. Relevance scoring (#10)
7. Smarter JS fallback (#12)
8. Query operators (#9)
9. Robots.txt awareness (#11)

**Phase 3 — Multi-backend search:**
10. Search backend abstraction (#1)
11. SearXNG integration (#13)
12. Result deduplication/merging (#8)

**Phase 4 — Async rewrite:**
13. httpx + HTTP/2 (#7)
14. Async-native MCP handlers (#14)
15. DNS/TLS caching (#15)

---

## What This Does NOT Cover

Consistent with v1's architectural boundaries, these upgrades do NOT include:

- **Paid APIs** — Everything above is free (self-hosted or free-tier)
- **Proxy rotation** — Out of scope for free tooling (free proxies are unreliable)
- **Bot evasion / stealth** — JustScrape is honest retrieval, not a bypass tool
- **LLM-based post-processing** — Classification stays rule-based and deterministic
- **Browser fingerprint spoofing** — Not needed for legitimate retrieval

The goal is making honest retrieval *faster and more reliable*, not circumventing protections.
