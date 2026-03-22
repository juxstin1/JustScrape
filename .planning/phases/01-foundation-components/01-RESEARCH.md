# Phase 1: Foundation Components - Research

**Researched:** 2026-03-21
**Domain:** Python text analysis — query understanding, result ranking, snippet extraction
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Intent Detection (QueryAnalyzer)**
- D-01: Rules-only approach — pattern matching + keyword lists, zero ML dependencies. No spacy.
- D-02: Six intent categories: code, research, news, how-to, lookup, comparison. Each returns with a confidence score (0.0–1.0).
- D-03: When confidence < 0.7, classify as "general" and use wider-net mode (fetch more results — 10 instead of 5).
- D-04: Aggressive query expansion — abbreviations + alternate phrasings + related terms (e.g., "react hooks" also generates "react useState useEffect").
- D-05: Query decomposition triggers on conjunctions only — split on "and", "vs", "or", "compared to". Simple and predictable.
- D-06: Entity extraction via regex patterns — library names, language names, version numbers. No NLP dependency.

**Authority Tiers (ResultReranker)**
- D-07: Five authority tiers: Authoritative (1.0) / Trusted (0.8) / Standard (0.5) / Low (0.2) / Blocked (0.0).
- D-08: Authority map is query-type-dependent — different maps for code, research, news, etc. (e.g., Stack Overflow = Authoritative for code, Standard for research).
- D-09: Freshness penalty applied ONLY to news/current-event queries. Docs and code don't age the same way — no decay for non-temporal queries.
- D-10: Curated domain blocklist — known SEO farms, content scrapers, low-quality aggregators always filtered out (score = 0.0, never scraped).
- D-11: Original search position preserved as one signal (will be used as ~15-20% weight in Phase 2's composite scorer).

**Snippet Extraction (SnippetExtractor)**
- D-12: Hybrid chunking — split on headings (h1-h6) first, then split large sections into paragraphs. Keeps logical sections together while maintaining scoring granularity.
- D-13: Return top 2-3 best-scoring chunks per result. Not just 1, but not unlimited — covers multi-part answers.
- D-14: Blended scoring — BM25 + TF-IDF cosine averaged for better discrimination than either alone. Uses rank-bm25 + scikit-learn.
- D-15: Code blocks treated as atomic chunks — never split mid-code-block. Preserved whole and boosted when query has code intent.
- D-16: Trafilatura for clean text extraction before chunking. Replaces current BS4-based extraction for snippet use cases.

### Claude's Discretion
- Exact regex patterns for intent classification keywords
- Specific domains in each authority tier (initial set — can be tuned)
- BM25/TF-IDF weight blend ratio (50/50 is fine starting point)
- Chunk size threshold for splitting large heading-sections into paragraphs
- Test structure and fixture design

### Deferred Ideas (OUT OF SCOPE)
- Wiring modules into the live pipeline — Phase 2
- Neural cross-encoder re-ranking — Phase 3
- Intelligent retry with reformulation — Phase 3
- Multi-source dedup — Phase 2 (PIPE-04)
- Composite quality scoring — Phase 2 (PIPE-01)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| QUERY-01 | System classifies query intent (code, research, news, how-to, lookup, comparison) | Rules-based pattern matching at module level (compiled regex). Return intent + confidence 0.0–1.0. Fall back to "general" when confidence < 0.7 per D-03. |
| QUERY-02 | System expands queries with synonyms, alternate phrasings, and abbreviation expansion | Pure string manipulation — no ML. Abbreviation dict + term expansion dict. Return list of expanded query strings. D-04 mandates aggressive expansion (e.g., "react hooks" → "react useState useEffect"). |
| QUERY-03 | System decomposes complex multi-part questions into independent sub-queries | Split on conjunction tokens only: "and", "vs", "or", "compared to". Per D-05, keep it simple and predictable. |
| QUERY-04 | System detects entities in queries (library names, language names, version numbers) | Regex only per D-06. Patterns for: version strings (v1.2.3, 3.12, etc.), known language names, library name patterns. Return list of detected entities with type tags. |
| RANK-01 | System scores search results by source authority (domain-based tier map, query-type aware) | Five-tier map (1.0/0.8/0.5/0.2/0.0) per D-07. Different maps per query type per D-08. Domain extraction from URL → tier lookup. |
| RANK-02 | System applies freshness weighting for time-sensitive queries (date extraction + decay) | Apply only for news/current-event intent per D-09. python-dateutil already in requirements for date parsing. Decay function outputs 0.0–1.0 multiplier. |
| EXTRACT-01 | System extracts clean body text using trafilatura before snippet scoring | trafilatura 2.0.0 (latest). `extract(html, favor_precision=True, include_tables=True, include_formatting=False)`. Must handle None return (fall back gracefully). |
| EXTRACT-02 | System chunks content into logical sections (headings, paragraphs, code blocks) | Hybrid strategy per D-12: heading-based first, then paragraph-split large sections. Code blocks (``` fenced or indented) treated as atomic per D-15. |
| EXTRACT-03 | System scores each chunk against query and returns the most relevant snippet(s) | BM25 + TF-IDF blended score per D-14. Return top 2-3 chunks per D-13. rank-bm25 0.2.2 + scikit-learn 1.8.0 (already installed). |
| EXTRACT-04 | System uses sentence-level semantic matching to locate the exact answering passage | Within the top-scoring chunks, identify the most relevant sentence(s) using TF-IDF cosine (no neural here — neural is Phase 3). Narrows to sentence level within best chunk. |
</phase_requirements>

---

## Summary

Phase 1 builds three standalone Python modules — `query_analyzer.py`, `result_reranker.py`, and `snippet_extractor.py` — each with its own test file. None of these modules are wired into the pipeline; they are pure, importable library code with dataclass inputs/outputs that Phase 2 will connect.

The key technical decision already locked is rules-only for QueryAnalyzer (no spacy, no ML). This means all intent classification and entity extraction uses compiled regex patterns and keyword lists — the same pattern the codebase already uses for `BLOCKED_PATTERNS` in `worker.py`. The authority tier system in ResultReranker is a dict lookup with per-query-type maps, following the same pattern as `JS_HEAVY_DOMAINS` and `_try_source_adapter`. The SnippetExtractor is the most algorithmically complex piece: trafilatura cleans HTML, a hybrid chunker splits on HTML structure, then BM25 + TF-IDF blend scores each chunk.

All three new libraries required by this phase (trafilatura, rank-bm25) are NOT yet installed. scikit-learn 1.8.0 is already installed. python-dateutil is already in requirements for RANK-02. A Wave 0 task must add `trafilatura>=2.0.0` and `rank-bm25>=0.2.2` to `requirements.txt` and install them.

**Primary recommendation:** Model all three modules on the established codebase patterns — compiled regex at module level, dataclass containers, lazy imports for optional heavy deps, graceful fallback (never crash, always return something).

---

## Standard Stack

### Core (new additions for this phase)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `trafilatura` | `2.0.0` | Clean body text extraction from HTML before chunking | Outperforms newspaper3k and readability-lxml; actively maintained; locked in D-16 |
| `rank-bm25` | `0.2.2` | BM25Okapi lexical scoring of chunks against query | Zero dependencies, pure Python, always available; locked in D-14 |

### Already Installed
| Library | Version | Purpose | Phase Use |
|---------|---------|---------|-----------|
| `scikit-learn` | `1.8.0` | TF-IDF cosine similarity for chunk scoring | Blended with BM25 per D-14; EXTRACT-03/04 |
| `python-dateutil` | already in requirements | Date parsing for freshness scoring | RANK-02 freshness decay |

### Not Used in This Phase
| Library | Reason |
|---------|--------|
| `spacy` | Explicitly rejected in D-01 — rules-only for intent and entities |
| `sentence-transformers` | Phase 3 only — neural cross-encoder is deferred |
| `rapidfuzz` | Phase 2 dedup — out of scope for Phase 1 |

**Installation (Wave 0 task):**
```bash
pip install trafilatura>=2.0.0 rank-bm25>=0.2.2
# Add to requirements.txt:
# trafilatura>=2.0.0
# rank-bm25>=0.2.2
```

**Version verification (confirmed 2026-03-21):**
- `rank-bm25`: latest is `0.2.2` (only version with meaningful content: 0.2.2)
- `trafilatura`: latest is `2.0.0` (previously `1.12.2` — major version bump)
- `scikit-learn`: latest is `1.8.0` (installed: `1.8.0`)

---

## Architecture Patterns

### Recommended Project Structure

```
query_analyzer.py       # Standalone module: QueryAnalyzer + AnalyzedQuery dataclass
result_reranker.py      # Standalone module: ResultReranker + RankedResult dataclass
snippet_extractor.py    # Standalone module: SnippetExtractor + ExtractedSnippet dataclass
tests/
├── test_query_analyzer.py
├── test_result_reranker.py
└── test_snippet_extractor.py
```

All three files live at the project root alongside `web_search.py`, `smart_scraper.py`, etc. — matching the flat module structure convention.

### Pattern 1: Dataclass Containers (follow existing SearchResult/ScrapedContent pattern)

```python
# Source: existing web_search.py / smart_scraper.py patterns in codebase
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class AnalyzedQuery:
    original: str
    intent: str                        # "code" | "research" | "news" | "how-to" | "lookup" | "comparison" | "general"
    confidence: float                  # 0.0–1.0
    expanded_queries: List[str]        # original + expanded variants
    sub_queries: List[str]             # decomposed parts (empty if not decomposed)
    entities: List[dict]               # [{text, type}] — libraries, languages, versions

@dataclass
class RankedResult:
    url: str
    title: str
    snippet: str
    original_position: int             # 1-based, preserved from search engine
    authority_score: float             # 0.0–1.0 from tier map
    freshness_score: Optional[float]   # 0.0–1.0 only for news; None for others
    is_blocked: bool                   # True if domain is on blocklist

@dataclass
class ExtractedSnippet:
    text: str
    chunk_index: int
    score: float                       # blended BM25+TF-IDF score
    is_code: bool                      # True if chunk contains code block
    source_url: str
```

### Pattern 2: Compiled Regex at Module Level (follow BLOCKED_REGEX pattern)

```python
# Source: worker.py lines 70-71 — same pattern for intent keywords
import re

# Compile all patterns once at import time — not per-call
CODE_PATTERNS = re.compile(
    r'\b(function|class|def |import |pip install|npm install|'
    r'error:|exception:|traceback|api|sdk|library|package|module)\b',
    re.IGNORECASE
)

NEWS_PATTERNS = re.compile(
    r'\b(today|breaking|latest|now|this week|announced|released|'
    r'yesterday|just happened)\b',
    re.IGNORECASE
)

# Version number detection (entity extraction)
VERSION_PATTERN = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')
```

### Pattern 3: Lazy Import for Optional Heavy Deps (follow Playwright pattern)

```python
# Source: existing lazy import pattern in codebase
# rank-bm25 is lightweight (always available) — import at module top
# trafilatura is medium-weight — import at module top (no torch/CUDA)
# scikit-learn is already installed — import at module top

# For any future optional dep (e.g., sentence-transformers in Phase 3):
def _try_import_transformers():
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder
    except ImportError:
        return None
```

### Pattern 4: Per-Query-Type Authority Maps (follow JS_HEAVY_DOMAINS pattern)

```python
# Source: smart_scraper.py JS_HEAVY_DOMAINS dict pattern
# Domains are lowercased, www-stripped keys

AUTHORITY_TIERS = {
    "code": {
        # Authoritative (1.0)
        "docs.python.org": 1.0,
        "docs.rust-lang.org": 1.0,
        "developer.mozilla.org": 1.0,
        "docs.microsoft.com": 1.0,
        "stackoverflow.com": 1.0,
        "github.com": 1.0,
        # Trusted (0.8)
        "realpython.com": 0.8,
        "css-tricks.com": 0.8,
        # Low (0.2)
        "medium.com": 0.2,
        "dev.to": 0.2,
    },
    "research": {
        "stackoverflow.com": 0.5,  # Standard for research
        "arxiv.org": 1.0,
        "wikipedia.org": 1.0,
        "scholar.google.com": 0.8,
        "medium.com": 0.5,
    },
    "news": {
        "reuters.com": 1.0,
        "apnews.com": 1.0,
        "bbc.com": 1.0,
        "techcrunch.com": 0.8,
        "medium.com": 0.3,
    },
    # "lookup", "how-to", "comparison" — use "general" as fallback
    "general": {
        # Standard defaults when query type doesn't have a specific map
    }
}

BLOCKED_DOMAINS = {
    # SEO farms, scrapers, low-quality aggregators — always 0.0
    "answers.com",
    "ask.com",
    "ehow.com",
    "brighthub.com",
}
```

### Pattern 5: trafilatura Extraction

```python
# Source: trafilatura official docs (verified 2026-03-21)
import trafilatura

def extract_clean_text(html: str, url: str = "") -> Optional[str]:
    """Extract clean body text from raw HTML. Returns None if extraction fails."""
    result = trafilatura.extract(
        html,
        url=url,               # Helps date detection and link normalization
        favor_precision=True,  # Prefer accuracy over completeness
        include_tables=True,   # Tables contain useful structured data
        include_comments=False,
        include_formatting=False,  # Plain text, not markdown
    )
    return result  # May be None — callers must handle
```

### Pattern 6: BM25 + TF-IDF Blended Scoring

```python
# Source: rank-bm25 PyPI docs + scikit-learn official docs (verified 2026-03-21)
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

def score_chunks(query: str, chunks: List[str], bm25_weight: float = 0.5) -> List[float]:
    """
    Blend BM25 + TF-IDF cosine for chunk scoring.
    bm25_weight=0.5 means 50/50 blend (D-14 default).
    Returns normalized scores 0.0–1.0 for each chunk.
    """
    if not chunks:
        return []

    # BM25 scoring
    tokenized_corpus = [chunk.lower().split() for chunk in chunks]
    tokenized_query = query.lower().split()
    bm25 = BM25Okapi(tokenized_corpus)
    bm25_scores = bm25.get_scores(tokenized_query)

    # TF-IDF cosine scoring
    vectorizer = TfidfVectorizer(norm='l2', lowercase=True)
    all_texts = chunks + [query]
    tfidf_matrix = vectorizer.fit_transform(all_texts)
    chunk_vectors = tfidf_matrix[:-1]
    query_vector = tfidf_matrix[-1]
    tfidf_scores = cosine_similarity(query_vector, chunk_vectors)[0]

    # Normalize BM25 (not bounded 0-1 by default)
    bm25_max = max(bm25_scores) if max(bm25_scores) > 0 else 1.0
    bm25_norm = bm25_scores / bm25_max

    # Blend
    blended = bm25_weight * bm25_norm + (1 - bm25_weight) * tfidf_scores
    return blended.tolist()
```

### Anti-Patterns to Avoid

- **Length-biased scoring:** Do NOT add any length bonus to chunk scores. The existing `relevance_score` in `web_search.py` has `0.20 * length_score` — this is the exact anti-pattern described in Pitfall P2. Snippet scoring must measure relevance, not page size.
- **Stop-word removal on code queries:** Do NOT strip "is", "in", "for", "not" from queries. Python expressions like "is in", "for loop", "not null" break if stop words are removed (Pitfall P10). Since QueryAnalyzer detects code intent first, pass intent to SnippetExtractor so it can skip stop-word normalization.
- **Global single authority map:** Do NOT use one authority map for all query types. Stack Overflow is Authoritative for code but Standard for research — query-type-aware maps are required (D-08).
- **Freshness decay on all queries:** Do NOT apply date freshness to code/docs/research queries. Only apply to news/current-event intent (D-09). Python 3.12 docs from 2023 are still correct — penalizing them by date is wrong.
- **Splitting code blocks:** Do NOT split on paragraph boundaries inside fenced code blocks. Detect ``` markers and treat everything between them as an atomic unit (D-15).
- **Crashing on missing trafilatura output:** trafilatura.extract() returns None when it cannot extract meaningful content. Always check for None before proceeding to chunking.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| BM25 scoring algorithm | Custom BM25 from scratch | `rank-bm25` BM25Okapi | BM25 has subtle tuning params (k1, b); hand-rolled implementations miss edge cases and normalization |
| TF-IDF cosine similarity | Custom TF-IDF matrix + dot product | `sklearn.TfidfVectorizer` + `cosine_similarity` | Sklearn handles vocabulary building, IDF smoothing, L2 normalization, and sparse matrix efficiency |
| HTML body extraction | Custom BeautifulSoup rules | `trafilatura.extract()` | Nav/footer/sidebar removal requires heuristic ML; BS4 tag removal misses content zones; trafilatura benchmarks show significant accuracy advantage |
| Date string parsing | Custom regex date parser | `python-dateutil.parser.parse()` | Hundreds of date format variations — dateutil is already in requirements |

**Key insight:** The algorithmic complexity in BM25 and TF-IDF is in the scoring math, not the API. Both libraries are trivial to use correctly; re-implementing them introduces subtle bugs (division-by-zero, IDF smoothing, BM25 saturation) with no benefit.

---

## Common Pitfalls

### Pitfall 1: Length-Biased Chunk Scoring (P2 — Critical)
**What goes wrong:** Adding any content-length component to chunk scores causes long tangentially-relevant sections to outrank short precise answers. Long Wikipedia boilerplate beats a 3-line direct answer.
**Why it happens:** Intuitively "more content = more likely to be useful" — but this optimizes for page completeness, not answer precision.
**How to avoid:** Score is `0.5 * bm25_normalized + 0.5 * tfidf_cosine` — nothing else. No length component. No word-count bonus.
**Warning signs:** Short, precise code examples consistently score below long prose explanations in tests.

### Pitfall 2: Intent Misclassification Cascades (P5 — Moderate)
**What goes wrong:** A code query classified as "news" gets low authority scores for Stack Overflow and docs, boosting freshness instead of technical authority. Wrong routing corrupts all downstream scoring.
**Why it happens:** Pattern matching without sufficient signal — ambiguous queries (e.g., "Python release") could be code or news.
**How to avoid:** Conservative default — when confidence < 0.7, classify as "general" (D-03). Never apply specialized routing on uncertain classifications. Log all classifications for tuning.
**Warning signs:** In tests, "python release" should return confidence < 0.7 and classify as "general", not as either "code" or "news".

### Pitfall 3: BM25 Raw Scores Not Normalized
**What goes wrong:** BM25Okapi.get_scores() returns values in an unbounded range (e.g., 0 to 15.3). If blended directly with TF-IDF cosine (which is 0.0–1.0), the BM25 component dominates completely.
**Why it happens:** rank-bm25 does not normalize output — this is documented behavior.
**How to avoid:** Always normalize: `bm25_scores / max(bm25_scores)` before blending. Guard against `max == 0` (all-zero scores when no query terms appear in corpus).
**Warning signs:** TF-IDF weight effectively has no impact on final scores — blended scores closely mirror raw BM25.

### Pitfall 4: trafilatura Returning None
**What goes wrong:** Calling chunking/scoring logic directly on `trafilatura.extract()` result without None check causes AttributeError in downstream code.
**Why it happens:** trafilatura returns None when it cannot identify a meaningful main content area (login walls, error pages, very short pages).
**How to avoid:** `text = trafilatura.extract(html) or ""` — always coerce to string. If empty string, SnippetExtractor should return empty list, not crash.
**Warning signs:** Tests with minimal HTML fixtures (e.g., "Hello world") should return empty snippet list, not raise exceptions.

### Pitfall 5: Code Block Detection Fragility
**What goes wrong:** Code-block-aware chunking that only detects triple-backtick fences misses indented code blocks (4-space indent), `<code>` tags in HTML, and single-backtick inline code snippets.
**Why it happens:** Trafilatura output is plain text — HTML `<code>` tags are stripped. Relying on backtick detection alone misses indented blocks.
**How to avoid:** After trafilatura extraction, detect code blocks by: (1) triple-backtick fences, (2) 4-space or tab-indented blocks of 2+ consecutive lines. Mark these as `is_code=True` chunks.
**Warning signs:** Tests using indented-code-block pages return `is_code=False` for the code chunk.

### Pitfall 6: Authority Score for Unknown Domains
**What goes wrong:** A domain not in any authority tier map receives `KeyError` or is silently scored as 0.0 (Blocked tier), causing it to be filtered out even though it's a legitimate result.
**Why it happens:** Authority maps only cover known domains; the web has infinite domains.
**How to avoid:** Default fallback is Standard tier (0.5) for any domain not found in the map. Only explicitly listed `BLOCKED_DOMAINS` get 0.0. Never set unknown = blocked.
**Warning signs:** Long-tail domains (niche technical blogs, university sites) all score 0.0 in authority tests.

---

## Code Examples

### QueryAnalyzer — Intent Classification with Confidence

```python
# Source: adapted from worker.py BLOCKED_REGEX pattern (lines 70-71)
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict

# Compiled at module level — not per-call
_CODE_PATTERN = re.compile(
    r'\b(function|class|def |import |pip |npm |yarn |cargo |'
    r'error:|exception:|traceback|api|sdk|library|package|module|'
    r'install|configure|debug|syntax|loop|variable|method|returns?)\b',
    re.IGNORECASE
)
_NEWS_PATTERN = re.compile(
    r'\b(today|breaking|latest|just|now|this week|this year|'
    r'announced|released|yesterday|just happened|current|recent)\b',
    re.IGNORECASE
)
_HOW_TO_PATTERN = re.compile(
    r'\b(how to|how do|step by step|tutorial|guide|walkthrough|'
    r'setup|configure|enable|disable|install|create|build|make)\b',
    re.IGNORECASE
)
_RESEARCH_PATTERN = re.compile(
    r'\b(what is|explain|overview|history|background|theory|'
    r'research|paper|study|definition|concept|understand)\b',
    re.IGNORECASE
)
_COMPARISON_PATTERN = re.compile(
    r'\b(vs\.?|versus|compared? to|difference|better|worse|'
    r'pros and cons|tradeoffs?|which is)\b',
    re.IGNORECASE
)

def classify_intent(query: str) -> tuple[str, float]:
    """Return (intent, confidence). Falls back to 'general' when confidence < 0.7."""
    signals = {
        "code": len(_CODE_PATTERN.findall(query)),
        "news": len(_NEWS_PATTERN.findall(query)),
        "how-to": len(_HOW_TO_PATTERN.findall(query)),
        "research": len(_RESEARCH_PATTERN.findall(query)),
        "comparison": len(_COMPARISON_PATTERN.findall(query)),
    }
    total = sum(signals.values())
    if total == 0:
        return "lookup", 0.5  # Short factual queries — low confidence

    top_intent = max(signals, key=signals.get)
    confidence = min(signals[top_intent] / max(total, 1) + 0.3, 1.0)

    if confidence < 0.7:
        return "general", confidence
    return top_intent, confidence
```

### QueryAnalyzer — Query Decomposition on Conjunctions

```python
# Source: D-05 — split on conjunctions only
import re

_DECOMPOSE_PATTERN = re.compile(
    r'\s+(?:and|vs\.?|or|compared\s+to)\s+',
    re.IGNORECASE
)

def decompose_query(query: str) -> List[str]:
    """Split on conjunctions. Returns [query] if no split applies."""
    parts = _DECOMPOSE_PATTERN.split(query)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) <= 1:
        return [query]
    return parts
```

### ResultReranker — Authority Score Lookup

```python
# Source: D-07/D-08 pattern, modeled on smart_scraper.py domain detection
from urllib.parse import urlparse

def get_authority_score(url: str, query_type: str) -> float:
    """
    Returns 0.0–1.0. Unknown domains default to Standard (0.5).
    Explicitly blocked domains return 0.0.
    """
    domain = urlparse(url).netloc.lower().replace("www.", "")

    if domain in BLOCKED_DOMAINS:
        return 0.0

    tier_map = AUTHORITY_TIERS.get(query_type, AUTHORITY_TIERS["general"])
    # Walk domain suffixes for subdomain matching (e.g., docs.python.org)
    if domain in tier_map:
        return tier_map[domain]
    # Check base domain (strip subdomain)
    base_domain = ".".join(domain.split(".")[-2:])
    if base_domain in tier_map:
        return tier_map[base_domain]

    return 0.5  # Standard tier default — never 0.0 for unknown
```

### SnippetExtractor — Hybrid Chunking

```python
# Source: D-12/D-15 — heading-first, then paragraph-split, code blocks atomic
import re
from typing import List, Tuple

_HEADING_PATTERN = re.compile(r'^#{1,6}\s+.+$', re.MULTILINE)
_CODE_FENCE_PATTERN = re.compile(r'```[\s\S]*?```', re.MULTILINE)
_INDENTED_CODE_PATTERN = re.compile(r'(?:(?:^(?:    |\t).+\n?){2,})', re.MULTILINE)

CHUNK_SIZE_THRESHOLD = 800  # Characters — split heading-sections larger than this

def chunk_content(text: str) -> List[Tuple[str, bool]]:
    """
    Returns list of (chunk_text, is_code) tuples.
    Code blocks are atomic (never split). Heading sections split at CHUNK_SIZE_THRESHOLD.
    """
    if not text:
        return []

    chunks = []
    # Extract code blocks first (atomic — remove from text before other chunking)
    code_blocks = []
    def _save_code(m):
        placeholder = f"\x00CODE{len(code_blocks)}\x00"
        code_blocks.append(m.group(0))
        return placeholder

    text_no_code = _CODE_FENCE_PATTERN.sub(_save_code, text)

    # Split on headings
    sections = _HEADING_PATTERN.split(text_no_code)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) > CHUNK_SIZE_THRESHOLD:
            # Split large sections into paragraphs
            paragraphs = [p.strip() for p in section.split('\n\n') if p.strip()]
            for para in paragraphs:
                # Restore any code placeholders within this paragraph
                para = _restore_code_placeholders(para, code_blocks)
                chunks.append((para, False))
        else:
            section = _restore_code_placeholders(section, code_blocks)
            chunks.append((section, False))

    # Add standalone code blocks that weren't inside sections
    for i, code in enumerate(code_blocks):
        placeholder = f"\x00CODE{i}\x00"
        if placeholder in text_no_code and not any(placeholder in c[0] for c in chunks):
            chunks.append((code, True))

    return chunks

def _restore_code_placeholders(text: str, code_blocks: List[str]) -> str:
    for i, code in enumerate(code_blocks):
        text = text.replace(f"\x00CODE{i}\x00", code)
    return text
```

### SnippetExtractor — Code Boost for Code-Intent Queries

```python
# Source: D-15 — boost code blocks when query has code intent
def score_and_select_chunks(
    query: str,
    chunks: List[Tuple[str, bool]],  # (text, is_code)
    intent: str,
    top_n: int = 3,
    bm25_weight: float = 0.5,
) -> List[ExtractedSnippet]:
    """Return top N chunks, with code boost applied for code-intent queries."""
    if not chunks:
        return []

    texts = [c[0] for c in chunks]
    is_code_flags = [c[1] for c in chunks]

    scores = score_chunks(query, texts, bm25_weight)

    # Code boost: +0.2 for code chunks when query intent is "code"
    if intent == "code":
        scores = [
            min(s + 0.2, 1.0) if is_code else s
            for s, is_code in zip(scores, is_code_flags)
        ]

    # Sort descending, return top N
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    results = []
    for idx, score in indexed[:top_n]:
        if score > 0.0:  # Skip zero-score chunks
            results.append(ExtractedSnippet(
                text=texts[idx],
                chunk_index=idx,
                score=round(score, 4),
                is_code=is_code_flags[idx],
                source_url="",  # Set by caller
            ))
    return results
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| BS4 tag stripping for text extraction | trafilatura main-content detection | Trafilatura v1+ | Removes nav/footer/sidebar without explicit rules; handles JS-rendered metadata via URL param |
| Manual BM25 implementation | `rank-bm25` BM25Okapi | Library stable since 2019 | Correct k1/b parameters, proper IDF, no off-by-one errors |
| Single authority map for all query types | Per-query-type authority maps | Project decision (D-08) | Stack Overflow scores 1.0 for code, 0.5 for research — better routing |
| Freshness decay on all results | Freshness decay only for news intent | Project decision (D-09) | Docs don't age like news — no penalizing 2023 Python docs |
| trafilatura 1.x API | trafilatura 2.0.0 | March 2026 | `extract()` API is compatible; `favor_precision` and `include_tables` params unchanged |

**Deprecated/outdated:**
- `spacy` for query intent: rejected (D-01) — 12MB model download, ML dependency, overkill for keyword-based classification
- `newspaper3k`: unmaintained — use trafilatura (already in STACK.md)
- `readability-lxml`: less accurate than trafilatura on benchmarks

---

## Open Questions

1. **Chunk size threshold for paragraph splitting**
   - What we know: D-12 calls for splitting large heading-sections into paragraphs; Claude's discretion on threshold
   - What's unclear: Optimal character count — 500? 800? 1200?
   - Recommendation: Start with 800 characters. This is roughly 4-6 sentences — enough for a complete thought, not so large that BM25 scoring is diluted by unrelated content. Tune in Phase 2 with real queries.

2. **BM25/TF-IDF blend ratio**
   - What we know: D-14 says "50/50 is fine starting point"; Claude's discretion
   - What's unclear: Whether BM25 or TF-IDF performs better on the typical queries this system handles
   - Recommendation: Default to 50/50 (`bm25_weight=0.5`). Expose as a constructor parameter so Phase 3 can tune it empirically.

3. **Initial domain lists for authority tiers**
   - What we know: Claude's discretion on specific domains; five tiers are locked
   - What's unclear: Complete set of domains for each query type's map
   - Recommendation: Start with 15-20 high-impact domains per query type (the ones that appear most frequently in relevant searches). The maps are tunable — start defensible, iterate.

4. **trafilatura 2.0.0 breaking changes**
   - What we know: trafilatura went from 1.12.2 to 2.0.0 — a major version bump
   - What's unclear: Whether the `extract()` API has any breaking parameter changes
   - Recommendation: The core `extract(html, favor_precision, include_tables, include_comments)` API is verified unchanged. Test with real HTML in Wave 0 before relying on any undocumented behavior.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (no version pinned — existing project standard) |
| Config file | none (existing tests run without config file) |
| Quick run command | `python -m pytest tests/test_query_analyzer.py tests/test_result_reranker.py tests/test_snippet_extractor.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QUERY-01 | Intent classification returns correct category + confidence 0-1 | unit | `python -m pytest tests/test_query_analyzer.py::TestIntentClassification -x` | ❌ Wave 0 |
| QUERY-01 | confidence < 0.7 → returns "general" | unit | `python -m pytest tests/test_query_analyzer.py::TestIntentClassification::test_low_confidence_returns_general -x` | ❌ Wave 0 |
| QUERY-02 | Query expansion produces at least one expanded variant | unit | `python -m pytest tests/test_query_analyzer.py::TestQueryExpansion -x` | ❌ Wave 0 |
| QUERY-03 | Conjunction decomposition splits on "and", "vs", "or", "compared to" | unit | `python -m pytest tests/test_query_analyzer.py::TestQueryDecomposition -x` | ❌ Wave 0 |
| QUERY-04 | Entity extraction finds version numbers and language names | unit | `python -m pytest tests/test_query_analyzer.py::TestEntityExtraction -x` | ❌ Wave 0 |
| RANK-01 | Authority score for known domain returns correct tier value | unit | `python -m pytest tests/test_result_reranker.py::TestAuthorityScoring -x` | ❌ Wave 0 |
| RANK-01 | Unknown domain defaults to 0.5 (Standard), not 0.0 | unit | `python -m pytest tests/test_result_reranker.py::TestAuthorityScoring::test_unknown_domain_defaults_to_standard -x` | ❌ Wave 0 |
| RANK-01 | Blocked domain returns 0.0 | unit | `python -m pytest tests/test_result_reranker.py::TestAuthorityScoring::test_blocked_domain_returns_zero -x` | ❌ Wave 0 |
| RANK-02 | Freshness score computed for news intent | unit | `python -m pytest tests/test_result_reranker.py::TestFreshnessScoring -x` | ❌ Wave 0 |
| RANK-02 | Freshness score is None for code intent | unit | `python -m pytest tests/test_result_reranker.py::TestFreshnessScoring::test_no_freshness_for_code_intent -x` | ❌ Wave 0 |
| EXTRACT-01 | trafilatura extracts clean text, returns None for garbage HTML | unit | `python -m pytest tests/test_snippet_extractor.py::TestTextExtraction -x` | ❌ Wave 0 |
| EXTRACT-02 | Chunker splits on headings; code blocks are atomic | unit | `python -m pytest tests/test_snippet_extractor.py::TestChunking -x` | ❌ Wave 0 |
| EXTRACT-03 | Top N chunks returned; scores are 0.0–1.0 | unit | `python -m pytest tests/test_snippet_extractor.py::TestChunkScoring -x` | ❌ Wave 0 |
| EXTRACT-04 | Most relevant sentence identified within best chunk | unit | `python -m pytest tests/test_snippet_extractor.py::TestSentenceExtraction -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_query_analyzer.py tests/test_result_reranker.py tests/test_snippet_extractor.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_query_analyzer.py` — covers QUERY-01, QUERY-02, QUERY-03, QUERY-04
- [ ] `tests/test_result_reranker.py` — covers RANK-01, RANK-02
- [ ] `tests/test_snippet_extractor.py` — covers EXTRACT-01, EXTRACT-02, EXTRACT-03, EXTRACT-04
- [ ] Install new dependencies: `pip install trafilatura>=2.0.0 rank-bm25>=0.2.2` and add to `requirements.txt`

---

## Sources

### Primary (HIGH confidence)
- trafilatura official docs (readthedocs.io, fetched 2026-03-21) — `extract()` API, `favor_precision`, `include_tables` params
- rank-bm25 PyPI page (pypi.org, fetched 2026-03-21) — BM25Okapi API, normalization behavior, no preprocessing note
- scikit-learn official docs (scikit-learn.org, fetched 2026-03-21) — TfidfVectorizer L2 norm, `fit_transform`, `cosine_similarity`
- JustScrape codebase (direct inspection) — `web_search.py:relevance_score`, `worker.py:classify_content`, `smart_scraper.py:_try_source_adapter`

### Secondary (MEDIUM confidence)
- `pip index versions` output (2026-03-21) — confirmed trafilatura 2.0.0, rank-bm25 0.2.2, scikit-learn 1.8.0 are current latest
- `.planning/research/STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md` — project-level research from prior phase

### Tertiary (LOW confidence)
- None — all claims verified with primary or secondary sources

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions confirmed via pip index, APIs verified via official docs
- Architecture: HIGH — derived from direct codebase inspection + locked decisions in CONTEXT.md
- Pitfalls: HIGH — P2 and P10 directly identified in existing codebase; others verified from project PITFALLS.md

**Research date:** 2026-03-21
**Valid until:** 2026-04-20 (stable libraries; trafilatura 2.0.0 just released — watch for 2.0.x patches)
