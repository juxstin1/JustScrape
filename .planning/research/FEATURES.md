# Feature Landscape: AI-Powered Search Quality

**Domain:** AI search tools for LLM consumption (Perplexity, Tavily, Exa, Context7 class)
**Project:** JustScrape — improving search quality milestone
**Researched:** 2026-03-21

---

## Table Stakes

Features where absence makes results mediocre. Every serious AI search tool has these.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Query intent classification | Without it, a "how to" query gets the same treatment as a "what is" query — wrong source types, wrong snippet style | Medium | Classify: lookup, how-to, comparison, current-event, code, research. Each routes differently. |
| Keyword expansion / query rewriting | Literal queries miss synonyms, abbreviations, alternate phrasings. "react hooks tutorial" may not match pages that say "React functional components with useState" | Medium | Expand abbreviations, add synonyms, alternate phrasings. Can be rule-based or LLM-assisted. |
| Relevance scoring on retrieved URLs | Raw search engine rankings optimize for human SEO signals, not AI consumption quality. Without re-ranking, position 1 is often not the best answer | Medium | Score by: title match, snippet match, domain authority for query type, freshness (for news) |
| Content noise removal | Web pages contain nav bars, footers, sidebars, cookie banners, ads. Returning raw text dumps is table stakes failure | Medium | Existing BS4 extraction needs query-aware paragraph scoring, not just tag stripping |
| Snippet-level extraction | Returning a full 50KB page when one paragraph answers the question wastes context window and degrades AI answer quality | High | Locate the specific section/paragraph/code-block that contains the answer |
| Thin/blocked content detection | Login walls, CAPTCHA pages, and 200-word stubs need to be detected and skipped | Low | Already partially present in JustScrape's classification engine — needs to feed back into ranking |
| Multi-result fallback | When result #1 is thin or irrelevant, automatically try result #2–5. Never return empty or garbage | Low-Medium | Already partially present, needs to be systematic with scoring |
| Source type awareness | A Python API question should prefer official docs over blog posts. A news question should prefer recent sources. | Medium | Tag source type: official-docs, wiki, forum, blog, news, code-repo, academic |

---

## Differentiators

Features that separate good from great — what users notice and why they pay for Perplexity/Tavily.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Semantic re-ranking (neural) | Keyword overlap is a weak relevance signal. A neural cross-encoder scores query-document relevance at the semantic level — finds pages that answer the question without using the exact words | High | Exa's differentiator. `cross-encoder/ms-marco-MiniLM` via sentence-transformers runs locally, no API key. Single highest-leverage improvement. |
| Query decomposition for complex questions | Multi-part questions benefit from being split into sub-queries, each searched independently, then answers merged | High | Perplexity's approach. Can be heuristic for conjunction patterns as starting point. |
| Domain-specific search strategies | Coding questions need GitHub/SO/docs. Research needs academic/Wikipedia. News needs recency-weighted sources. A single strategy is mediocre for all three. | Medium | Route based on intent classification. Different backends, result count thresholds, freshness weights per type. |
| Intelligent retry with reformulation | When the first pass yields thin/irrelevant results, reformulate (broader, narrower, different angle) and retry | Medium | Requires feedback loop: score results, detect low quality, trigger reformulation. Tavily does up to 3 reformulation passes. |
| Answer-focused snippet extraction | Locate the paragraph that directly answers the query using sentence-level semantic similarity, not position heuristics | High | The difference between "here's the relevant section" and "here's the exact answer." |
| Freshness-aware ranking | For time-sensitive queries, publication date is a primary signal. "Latest Python version" should not return a 2019 article. | Medium | Date extraction + freshness decay function. Apply only when query contains temporal markers. |
| Source authority scoring | Official documentation and primary sources are more reliable than SEO-optimized blog posts | Medium | Domain scorelist per category (docs.python.org = HIGH for Python queries, medium.com = LOW). Query-type dependent. |
| Result deduplication | Multiple results often point to the same content (mirrors, syndicated articles). Returning 5 near-identical snippets wastes context. | Low-Medium | URL normalization + content fingerprinting (simhash or MinHash) before returning |
| Confidence/provenance signaling | Return not just the snippet but metadata: source URL, publication date, source type, relevance score | Low | Tavily's approach. Minimal additional complexity, high value for AI callers who need to cite sources. |

---

## Anti-Features

Features to deliberately NOT build for this milestone.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| LLM-generated answer synthesis | Generating prose from scraped content requires running an LLM, adds latency, wrong scope — the AI caller IS already an LLM | Return high-quality grounded snippets with sources; let the calling AI synthesize |
| Full-page vector indexing | Building a local vector index is a different product (knowledge base), adds enormous storage complexity | Use lightweight per-query re-ranking instead of persistent indices |
| Paid API integration | Explicitly out of scope per PROJECT.md | Stay with DuckDuckGo, SearXNG, Brave (optional key); improve quality through post-processing |
| Real-time crawling / spidering | Following link chains from seed URLs explodes latency and scope | Use sitemap discovery (already present) for structured sites |
| Multi-turn conversation memory | Tracking context across MCP calls requires session state | Each MCP call is stateless; AI caller maintains context |
| Custom fine-tuned models | Training/fine-tuning requires data and infrastructure far beyond this milestone | Use pre-trained off-the-shelf cross-encoders (no training required) |

---

## Feature Dependencies

```
Query intent classification
    ├── Domain-specific search strategies  (routing depends on intent)
    ├── Freshness-aware ranking            (apply only for time-sensitive intent)
    ├── Source authority scoring            (authority weights differ by query type)
    └── Answer-focused snippet extraction  (extraction strategy differs by intent)

Keyword expansion / query rewriting
    └── Intelligent retry with reformulation  (reformulation is advanced expansion)

Relevance scoring on retrieved URLs
    ├── Semantic re-ranking (neural)          (neural scoring is the premium form)
    ├── Source authority scoring               (one signal in composite score)
    └── Freshness-aware ranking               (one signal in composite score)

Content noise removal
    ├── Snippet-level extraction              (clean content is prerequisite)
    └── Answer-focused snippet extraction     (sentence scoring invalid on noisy text)

Snippet-level extraction
    └── Answer-focused snippet extraction     (answer-focused is a refinement)

Thin/blocked content detection
    ├── Multi-result fallback                 (fallback triggers on thin/blocked)
    └── Intelligent retry with reformulation  (triggers when all results score low)
```

---

## MVP Recommendation

Prioritize in this order:

1. **Query intent classification** — Unlocks correct routing for everything downstream
2. **Keyword expansion / query rewriting** — Highest ROI for DuckDuckGo quality. Pure text manipulation, no ML
3. **Relevance scoring on retrieved URLs** — Score results before fetching. Skip obviously irrelevant URLs
4. **Source type awareness + authority scoring** — Code questions skip news sites. Python questions prefer python.org
5. **Snippet-level extraction** — Most impactful user-visible improvement. Return the answering paragraph, not the page
6. **Confidence/provenance signaling** — Low complexity, high value. Return score + metadata alongside every result

Defer (second pass):
- Semantic re-ranking (neural): High value but requires sentence-transformers dependency
- Query decomposition: Significant complexity. Only needed for multi-part questions
- Result deduplication: Nice to have, not blocking quality

---

## Technique Reference: How Top Tools Do It

### Perplexity
Runs retrieval (search API + scraping) then LLM synthesis. Uses multiple search sources simultaneously. Pro search uses follow-up sub-queries for complex questions. Key insight: quality comes from LLM synthesis on top of retrieval — JustScrape doesn't synthesize, so retrieval quality must be higher.

### Tavily
Purpose-built for AI agents. Returns structured JSON with snippets, scores, metadata per result. `search_depth: advanced` triggers deeper crawling. Applies BM25 + neural re-ranking. `include_answer` extracts a short direct answer. Key insight: the product is the structured metadata — every result has a relevance score.

### Exa
Neural (embedding-based) search as primary index. `highlights` parameter extracts specific sentences matching the query. Key insight: `highlights` is exactly what snippet-level extraction should do — locate query-relevant sentences within a document.

### Context7
Domain-specific to software documentation. Resolve library → get canonical doc → query by topic. Returns exact documentation sections using pre-indexed, chunked docs. Token-budget-aware. Key insight: chunking + per-chunk scoring is the analog — fetch page, chunk into sections, score each chunk, return best.

---
*Researched: 2026-03-21*
