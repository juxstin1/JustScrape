# Build Order — Audit Fixes

28 findings from 3 parallel audits (search quality, scraping resilience, security). Ordered by dependency and severity. Each fix is atomic — can be committed independently.

## Wave 1: Critical (crashes and security holes)

These can crash production or be exploited. No dependencies between them — all parallelizable.

### C1 — SSRF via redirect chain
**File:** `web_scraper.py:120`
**Bug:** `validate_url()` checks the original URL, then `requests` follows redirects to a potentially private IP (169.254.169.254, 10.x, etc.) without re-validating the final URL.
**Fix:** After `allow_redirects=True`, call `validate_url(resp.url)` on the final redirected URL. Reject if it fails.
**Test:** Unit test with a mock redirect from public URL → private IP. Verify rejection.

### C2 — scikit-learn missing from requirements.txt
**File:** `requirements.txt`
**Bug:** `snippet_extractor.py` does `from sklearn.feature_extraction.text import TfidfVectorizer` at import time. Fresh installs crash immediately.
**Fix:** Add `scikit-learn>=1.3.0` to `requirements.txt`.
**Test:** `pip install -r requirements.txt && python -c "from snippet_extractor import SnippetExtractor"` on clean venv.

### C3 — No size cap on static scraper GET
**File:** `web_scraper.py:255`
**Bug:** HEAD pre-check only rejects when `Content-Length` header is present. Chunked/streaming responses with no `Content-Length` are buffered entirely into memory. A 50MB HTML page causes OOM.
**Fix:** Use `stream=True` on `session.get()`, read in chunks up to 10MB cap (matching `smart_scraper._safe_get()`), abort if exceeded.
**Test:** Mock a response that streams 20MB. Verify scraper stops at 10MB.

### C4 — robots.txt fetch hangs all threads
**File:** `web_scraper.py:76`
**Bug:** `RobotFileParser.read()` uses `urllib.request` with no timeout, called inside a threading lock. One slow server blocks all other scraping threads indefinitely.
**Fix:** Fetch robots.txt outside the lock with a 3-second timeout. Acquire lock only to store result. On timeout, assume allowed.
**Test:** Mock a robots.txt server that sleeps 30s. Verify scraper proceeds within 5s.

### C5 — NaN propagation from BM25 crashes JSON serialization
**File:** `snippet_extractor.py:254`
**Bug:** `max(bm25_raw)` can return NaN with degenerate inputs. NaN propagates through scoring to `json.dumps()` which produces invalid JSON (`NaN` is not valid JSON).
**Fix:** After computing `bm25_raw`, replace NaN values with 0.0 using `numpy.nan_to_num()` or a manual guard. Same for TF-IDF scores at line 268.
**Test:** Feed a single-character query against a single-word document. Verify no NaN in output.

---

## Wave 2: High — Quality (wrong results, user-visible)

Fixes that directly improve search quality. Some depend on Wave 1 (C5 must land before H1 matters).

### H1 — Plain text passed as HTML to trafilatura
**File:** `justscrape_mcp.py:780`
**Bug:** `scraper.scrape_to_dict()` returns already-extracted plain text. This is passed as the `html` parameter to `SnippetExtractor.extract_snippets()`, where trafilatura tries to parse it as HTML and gets nothing. Every JS-heavy site produces empty extraction → fallback snippet.
**Fix:** Either pass raw HTML to the extractor (expose `raw_html` from scraper), or detect that content is already plain text and skip trafilatura (go straight to chunking).
**Depends on:** Nothing, but C5 should land first so NaN doesn't mask the fix.

### H2 — "current" misclassifies technical queries as news
**File:** `query_analyzer.py:33`
**Bug:** `_NEWS_PATTERN` matches bare `current`, so "current working directory python" → news intent. Stack Overflow deprioritized, Reuters prioritized.
**Fix:** Require compound phrases: `current\s+events`, `current\s+news`, `currently\s+happening`. Remove standalone `current`.
**Test:** Assert "current directory python" → code intent, "current events middle east" → news intent.

### H3 — Fuzzy date parser reads version numbers as dates
**File:** `result_reranker.py:224`
**Bug:** `dateutil.parser.parse(snippet, fuzzy=True)` interprets "Python 3.12" as March 12, "400 downloads" as year 400. Garbage freshness scores for technical content.
**Fix:** Try explicit date regexes first (`\d{4}-\d{2}-\d{2}`, `Month DD, YYYY`, `DD/MM/YYYY`). Only use fuzzy parsing as last resort, and reject results where year is outside `[current_year - 5, current_year]`.
**Test:** Assert "Python 3.12 released" does NOT produce a date. Assert "March 15, 2026" does.

### H4 — ccTLD authority lookup fails (bbc.co.uk → "co.uk")
**File:** `result_reranker.py:212`
**Bug:** `_base_domain` takes last 2 labels. `bbc.co.uk` → `co.uk`. Authority map has `bbc.co.uk` but it never matches.
**Fix:** Detect known two-label TLDs (`co.uk`, `com.au`, `co.jp`, `org.uk`, `gov.uk`, etc.) and take last 3 labels instead.
**Test:** Assert `_base_domain("docs.bbc.co.uk")` == `"bbc.co.uk"`.

### H5 — Duplicate URLs from SearXNG scraped twice
**File:** `web_search.py:686`
**Bug:** SearXNG can return the same URL from multiple engines. No dedup before scraping → same page scraped twice, wastes concurrency slots.
**Fix:** Deduplicate by normalized URL in `_search_with_searxng` before building the results list.
**Test:** Mock SearXNG returning 3 results with 2 duplicate URLs. Verify only 2 unique results returned.

### H6 — Fallback re-searches when only scraping failed
**File:** `justscrape_mcp.py:881`
**Bug:** If the quality pipeline fails after search succeeded (e.g., reranker or extractor throws), the fallback block re-executes `search_full()` — a second network round-trip to SearXNG.
**Fix:** Preserve `search_result` from the try block in a variable before the pipeline. Use it in the fallback instead of re-searching.
**Depends on:** Nothing.

### H7 — Empty results return success: true
**File:** `justscrape_mcp.py:739`
**Bug:** When all results are blocked by `should_scrape()`, response is `{"success": true, "results": [], "total_results": 0}`. No signal to the AI that results existed but were all filtered.
**Fix:** When `enriched_results` is empty after pipeline, set `success: true` but add `"note": "All search results were filtered (blocked domains or unscrrapeable)"`. Don't set `success: false` since the search itself worked.

### H8 — Empty snippets all deduplicated into one
**File:** `quality_scorer.py:317`
**Bug:** `token_sort_ratio("", "")` returns 100, so all failed scrapes collapse into a single result during dedup. Masks how many results actually failed.
**Fix:** Skip dedup comparison for results where `snippet_text` is empty.

### H9 — Raw JavaScript returned as snippet content
**File:** `snippet_extractor.py:369`
**Bug:** When trafilatura returns empty (JS-only pages), fallback uses `full_content[:500]` which is raw JavaScript. The AI receives `var a = function(){...}` as "content."
**Fix:** Detect JS content (starts with `var `, `function(`, `(function(`, `{`, or has no `<html` tag with high script density). Return empty snippet instead of JS source. Mark as `scraped_successfully: false`.

### H10 — Score cliff at exactly 30 days for news
**File:** `quality_scorer.py:195`
**Bug:** When `freshness_score` is exactly `0.0` (not None), the freshness weight (25%) isn't redistributed. Composite score max is 0.75 instead of 1.0.
**Fix:** Change redistribution guard to trigger when `freshness_score is None or freshness_score == 0.0` for the purpose of weight redistribution.

---

## Wave 3: Medium — Security hardening

### M1 — Search operator injection via site/filetype/exclude_sites
**File:** `web_search.py:922`
**Bug:** `site: "example.com -site:internal.corp.com"` injects extra operators into the SearXNG query.
**Fix:** Restrict `site` and `filetype` values to `[a-zA-Z0-9.\-]` only. Strip everything else. Same for each element of `exclude_sites`.

### M2 — Cache poisoning from compromised SearXNG
**File:** `web_search.py:223`
**Bug:** Malicious SearXNG results cached for 24 hours. Persist even after SearXNG is restored.
**Fix:** Run `validate_url()` on all URLs when serving from cache (not just on first fetch). Document that SearXNG must be trusted.

### M3 — SearXNG URL not validated at startup
**File:** `web_search.py:504`
**Bug:** `SEARXNG_URL` env var accepted without validation. Could point to attacker-controlled server.
**Fix:** At startup, validate scheme is http/https and host is localhost/127.0.0.1 (or explicitly override with `SEARXNG_ALLOW_REMOTE=true`).

### M4 — extract_urls leaks raw exceptions
**File:** `justscrape_mcp.py:1062`
**Bug:** Only handler that returns `str(e)` to caller. Leaks internal paths, library versions, connection errors.
**Fix:** Return static "Extraction failed" string. Log real error to stderr.

### M5 — robots.txt cached forever
**File:** `web_scraper.py:58`
**Bug:** `RobotsCache` has no TTL. A temporarily restrictive robots.txt blocks valid pages for the lifetime of the process.
**Fix:** Store `(parser, timestamp)` tuple. Re-fetch entries older than 24 hours.

### M6 — Abbreviation expansion case-sensitive
**File:** `query_analyzer.py:250`
**Bug:** `"JS"` pattern doesn't match lowercase `"js"` in queries. Most users type lowercase.
**Fix:** Add `re.IGNORECASE` to abbreviation pattern compilation.

---

## Wave 4: Low — Polish

### L1 — Semaphore held across CPU work
**File:** `justscrape_mcp.py:772`
**Fix:** Release semaphore after `run_in_executor` returns, before snippet extraction.

### L2 — docs. substring false positives
**File:** `quality_scorer.py:76`
**Fix:** Change `"docs." in netloc` to `netloc.startswith("docs.")`.

### L3 — Dead code: search_result_dict parameter
**File:** `justscrape_mcp.py:752`
**Fix:** Remove the unused parameter from `scrape_and_extract_one` and the tuple in `candidates`.

### L4 — Confidence always 1.0
**File:** `query_analyzer.py:226`
**Fix:** Adjust formula: `confidence = min(1.0, top_count / boosted_total)` without the +0.3 baseline. Low-evidence queries get low confidence.

### L5 — exclude_sites elements not type-checked
**File:** `justscrape_mcp.py:552`
**Fix:** `exclude_sites = [str(s) for s in exclude_sites if s is not None]` before passing to search.

### L6 — Playwright networkidle 30s timeout
**File:** `justscrape_mcp.py:279`
**Fix:** Change to `wait_until="domcontentloaded"`, reduce timeout to 15s.

---

## Execution Notes

- **Waves 1-2** are the priority. Wave 1 prevents crashes/exploits. Wave 2 is the quality ceiling.
- **Each fix is atomic** — one commit per fix, one test per fix.
- **All code changes go through the user for approval** before commit.
- **Run full test suite (215 tests) after each wave** to catch regressions.
- **Estimated scope:** Wave 1 is ~5 small edits. Wave 2 is ~10 edits, some requiring new logic. Wave 3-4 are straightforward.
