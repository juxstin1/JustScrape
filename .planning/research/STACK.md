# Stack Research: AI-Powered Search Quality

## Recommended Stack

### Core Libraries (Free/Open-Source Only)

| Library | Version | Role | Confidence |
|---------|---------|------|------------|
| `rank-bm25` | `>=0.2.2` | Lexical re-ranking (BM25Okapi) — zero-dependency, pure Python | HIGH |
| `sentence-transformers` | `>=2.7.0` | Semantic cross-encoder re-ranking via `cross-encoder/ms-marco-MiniLM-L-6-v2` — 80MB model | HIGH |
| `scikit-learn` | `>=1.4.0` | TF-IDF cosine fallback when torch unavailable | HIGH |
| `spacy` + `en_core_web_sm` | `>=3.7.0` | Query intent/entity detection (12MB model) — identifies code vs research vs news | HIGH |
| `trafilatura` | `>=1.8.0` | Clean body text extraction — outperforms readability-lxml and newspaper3k | HIGH |
| `rapidfuzz` | `>=3.6.0` | Near-duplicate snippet deduplication for multi-source synthesis | HIGH |

### What NOT to Use

| Library | Why Not |
|---------|---------|
| BART / T5 / any generation model | JustScrape retrieves, the calling LLM synthesizes — no generation needed |
| `newspaper3k` | Unmaintained, worse extraction quality than trafilatura |
| `readability-lxml` | Less accurate than trafilatura on benchmarks |
| Paid embedding APIs (OpenAI, Cohere) | Violates free-only constraint |
| `fuzzywuzzy` | Unmaintained — use `rapidfuzz` instead |
| Full `transformers` pipeline | Overkill — `sentence-transformers` provides focused re-ranking |

### Graceful Degradation Strategy

Three-tier fallback matching existing Playwright optional pattern:

1. **Best**: Cross-encoder re-ranking (sentence-transformers + torch) — most accurate
2. **Good**: TF-IDF cosine similarity (scikit-learn) — lightweight, decent quality
3. **Basic**: BM25 lexical ranking (rank-bm25) — zero dependencies, always available

### Size/Cost Considerations

- `sentence-transformers` pulls in `torch` (~500MB–2GB) — largest dependency by far
- `spacy` + `en_core_web_sm` — 12MB model download
- All other libraries are lightweight (<5MB each)
- Consider making torch/sentence-transformers optional (like Playwright currently is)

### Integration Points

- **trafilatura** replaces/supplements existing BeautifulSoup extraction in `web_scraper.py`
- **rank-bm25** + **sentence-transformers** add a re-ranking layer between search results and return
- **spacy** adds query understanding before search execution
- **rapidfuzz** enables deduplication in multi-source synthesis

---
*Researched: 2026-03-21*
