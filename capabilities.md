# JustScrape MCP v1 Capabilities

## 1. Purpose

JustScrape is a local retrieval and inspection MCP.

It retrieves web content and reports what happened honestly. It does not attempt to maximize coverage, evade bot detection, or approximate Google.

---

## 2. What This MCP Guarantees

- **Retrieval outcomes are classified, not flattened into success/failure.** Every retrieval returns a status (`usable`, `thin`, `blocked`, `encoding-failure`, `empty`) with confidence and detected patterns.

- **Bot walls and thin pages are returned as data, not errors.** A blocked result is a valid outcome. It does not throw an exception or trigger a retry.

- **JavaScript rendering is explicit and opt-in.** Static retrieval is the default. Playwright-based rendering requires `allow_javascript=true`.

- **Absence of content is a valid signal.** Null content with classification metadata is informative, not a failure state.

- **Results are deterministic for a given request window.** The same URL will produce the same classification unless the source page changes.

---

## 3. Supported Tools

### `search_sources`

Searches DuckDuckGo and returns ranked results with titles, URLs, and snippets.

It does not retrieve page content, rank by quality, or deduplicate results.

### `retrieve_source`

Retrieves a single URL and classifies the result as `usable`, `thin`, `blocked`, or failed.

It does not retry, rank, summarize, or attempt to bypass protections.

### `research_with_sources`

Searches and retrieves the top N results, separating usable sources from failures.

It does not select the "best" source, merge content, or hide failures.

### `extract_urls`

Extracts all links from a page.

It does not classify, filter by relevance, or follow links.

---

## 4. Classification Semantics

### `usable`

Long-form content with paragraph structure. Typically 2,000+ characters with multiple line breaks. High confidence when content exceeds 5,000 characters.

### `thin`

Minimal content. Landing pages, stubs, or pages with fewer than 500 characters of extractable text. This is not an error—some pages are intentionally minimal.

### `blocked`

Bot protection or interstitial page detected. Identified by short content (<1,500 characters) containing patterns like "verify you are human", "cloudflare", "captcha", or "blocked by network security".

A `blocked` result means content was not accessible, not that an error occurred.

### `encoding-failure`

The page was retrieved but output could not be safely represented due to character encoding issues. This is a hard failure.

### `empty`

The page returned no extractable content. Status code may have been 200, but the body was empty or unparseable.

---

## 5. What Works Well

Based on empirical testing:

- Technical blogs (ScrapingBee, Real Python, etc.)
- Documentation sites (official docs, FAQ pages)
- Wikipedia articles
- Simple landing pages
- News articles on static sites

These platforms serve clean HTML that static or JS-based retrieval can extract reliably.

---

## 6. What Does Not Work

The following platforms actively prevent automated retrieval:

- **Medium** — Cloudflare protection returns captcha interstitials
- **Reddit** — Network security blocks return "You've been blocked" messages
- **Twitter/X** — Requires authentication, returns minimal content
- **LinkedIn** — Login walls on most content
- **Facebook** — Heavy bot detection
- **Paywalled sites** — Returns subscription prompts or partial content

This MCP does not attempt to bypass those protections. Results from these platforms will be classified as `blocked` or `thin`.

---

## 7. What Is Intentionally Out of Scope (v1)

The following features are explicitly excluded from v1:

- **No ranking or scoring** — Sources are not ordered by quality or relevance
- **No automatic retries** — Failed retrievals are reported, not retried
- **No selector extraction** — CSS or XPath targeting is not supported
- **No proxy or stealth controls** — All requests use the same IP and standard headers
- **No LLM-based post-processing** — Classification is rule-based, not model-based
- **No topic modeling** — Long ToS/cookie pages may classify as `usable`

These are not roadmap items. They are architectural boundaries that preserve the honesty of v1.

---

## 8. Stability & Versioning

Changes to classification rules or tool semantics require a version bump.

Bug fixes that do not alter observable behavior do not.

The current version is **1.0.0**.

---

## Summary

JustScrape v1 is a retrieval primitive that tells you what it found and how confident it is. It does not pretend to be comprehensive. It does not hide failures. It does not optimize for coverage.

Use it when you need honest retrieval with inspectable outcomes.
