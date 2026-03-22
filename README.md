# JustScrape

God-status web search for AI. Free. No API keys. Returns the exact snippet, not a wall of text.

JustScrape is an MCP server that gives AI models web search and scraping capabilities. It searches via a self-hosted SearXNG instance (aggregating Google, Bing, and 70+ engines), scrapes the results, extracts only the relevant chunks using BM25/TF-IDF scoring, and returns precisely what the AI needs — scored, ranked, and deduplicated.

**~1,000 tokens per search** instead of ~5,000+. No paid APIs. No rate limits.

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/juxstin1/JustScrape.git
cd JustScrape
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Start SearXNG (one-time)
mkdir -p ~/searxng
cat > ~/searxng/settings.yml << 'EOF'
use_default_settings: true
search:
  formats:
    - html
    - json
server:
  limiter: false
  secret_key: "justscrape-local-dev"
EOF
sudo docker run -d --name searxng -p 8080:8080 \
  -v ~/searxng/settings.yml:/etc/searxng/settings.yml \
  searxng/searxng

# 3. Add to Claude Desktop config
# ~/.config/claude/claude_desktop_config.json (Linux/Mac)
# %APPDATA%\Claude\claude_desktop_config.json (Windows)
```

```json
{
  "mcpServers": {
    "justscrape": {
      "command": "python",
      "args": ["/path/to/JustScrape/justscrape_mcp.py"]
    }
  }
}
```

## How It Works

```
Query: "what is happening in Tel Aviv"
                    │
                    ▼
            ┌───────────────┐
            │ QueryAnalyzer │  Intent: news, confidence: 0.85
            └───────┬───────┘  Entities: [Tel Aviv], expanded queries
                    │
                    ▼
            ┌───────────────┐
            │   SearXNG     │  Google + Bing + 70 engines
            │  (localhost)  │  No rate limits, no API keys
            └───────┬───────┘
                    │
                    ▼
           ┌────────────────┐
           │ ResultReranker │  Authority scoring (per query type)
           └───────┬────────┘  Freshness weighting (news only)
                   │
                   ▼
          ┌─────────────────┐
          │ Parallel Scrape │  Concurrent fetching with semaphore
          │        +        │
          │SnippetExtractor │  BM25 + TF-IDF chunk scoring
          └────────┬────────┘  Returns top 3 relevant chunks only
                   │
                   ▼
           ┌───────────────┐
           │ QualityScorer │  Composite: relevance + authority +
           └───────┬───────┘  freshness + position
                   │
                   ▼
           ┌───────────────┐
           │   Dedup       │  rapidfuzz near-duplicate removal
           └───────┬───────┘
                   │
                   ▼
            Scored results
            ~1,000 tokens
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_and_scrape` | Full quality pipeline — search, rerank, scrape, extract, score, dedup |
| `web_search` | Raw search results without scraping |
| `scrape_url` | Scrape a single URL with clean extraction |
| `extract_urls` | Extract all links from a webpage |

### search_and_scrape Response

```json
{
  "success": true,
  "query": "python exception handling",
  "results": [
    {
      "title": "8. Errors and Exceptions — Python 3.14 docs",
      "url": "https://docs.python.org/3/tutorial/errors.html",
      "content": "...",
      "best_sentence": "The try statement works as follows...",
      "relevance_score": 0.54,
      "score_breakdown": {
        "relevance": 0.65,
        "authority": 1.0,
        "freshness": null,
        "position": 0.85
      },
      "source_type": "documentation",
      "confidence": 0.85,
      "scraped_successfully": true
    }
  ],
  "total_results": 3
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    justscrape_mcp.py                        │
│                     (MCP Server)                            │
│                                                             │
│  ┌──────────────┐ ┌───────────────┐ ┌───────────────────┐  │
│  │QueryAnalyzer │ │ResultReranker │ │ SnippetExtractor  │  │
│  │ intent, NER  │ │ authority,    │ │ trafilatura,      │  │
│  │ expansion    │ │ freshness     │ │ BM25 + TF-IDF     │  │
│  └──────────────┘ └───────────────┘ └───────────────────┘  │
│                                                             │
│  ┌──────────────┐ ┌───────────────┐                        │
│  │QualityScorer │ │   Dedup       │                        │
│  │ composite    │ │ rapidfuzz     │                        │
│  └──────────────┘ └───────────────┘                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ web_search  │ │smart_scraper│ │async_scraper│
│  SearXNG    │ │ static + JS │ │ httpx/HTTP2 │
└──────┬──────┘ └─────────────┘ └─────────────┘
       │
       ▼
┌─────────────┐
│  SearXNG    │  Self-hosted Docker container
│ (localhost) │  Google + Bing + 70 engines
└─────────────┘
```

### Quality Pipeline Modules

| Module | Purpose |
|--------|---------|
| `query_analyzer.py` | Intent classification, query expansion, entity extraction, decomposition |
| `result_reranker.py` | Per-query-type authority scoring, freshness weighting, blocked domain filtering |
| `snippet_extractor.py` | trafilatura text extraction, hybrid chunking, BM25+TF-IDF relevance scoring |
| `quality_scorer.py` | Composite scoring (relevance + authority + freshness + position), dedup |

### Infrastructure Modules

| Module | Purpose |
|--------|---------|
| `justscrape_mcp.py` | MCP server — orchestrates the full pipeline |
| `web_search.py` | Search orchestration with 2-layer cache (memory + SQLite) |
| `smart_scraper.py` | Auto-routing between static and JS scraping |
| `web_scraper.py` | Static scraping with HEAD pre-check, robots.txt, rate limiting |
| `async_scraper.py` | httpx + HTTP/2 async scraper with connection pooling |
| `js_scraper.py` | Playwright browser scraping for JS-heavy sites |
| `backends/` | Search backend implementations |

## Search Backend: SearXNG

JustScrape uses a self-hosted [SearXNG](https://github.com/searxng/searxng) instance as its only search backend. SearXNG is a free, open-source meta-search engine that aggregates results from Google, Bing, DuckDuckGo, and 70+ other engines.

**Why SearXNG?**
- **No rate limits** — you own the instance
- **No API keys** — completely free
- **Better results** — aggregates multiple engines, not just one
- **No CAPTCHA** — Google/Bing see SearXNG's server, not yours

**Managing SearXNG:**

```bash
# Start
sudo docker start searxng

# Stop
sudo docker stop searxng

# View logs
sudo docker logs searxng

# Restart
sudo docker restart searxng

# Remove and recreate
sudo docker rm -f searxng
sudo docker run -d --name searxng -p 8080:8080 \
  -v ~/searxng/settings.yml:/etc/searxng/settings.yml \
  searxng/searxng
```

## Security

- **SSRF Protection** — URL validation blocks private IPs, non-HTTP schemes, cloud metadata endpoints
- **XXE Defense** — `defusedxml` for sitemap parsing
- **Browser Isolation** — Playwright scrapes in isolated contexts
- **Response Size Caps** — 10MB streaming limit
- **Input Validation** — Query (1000 chars), URL (2048 chars), content (100K chars) server-side caps
- **Concurrency Limits** — Global semaphore prevents DDoS amplification
- **215 Tests** — Covering URL validation, XXE, SSRF, pipeline integration, and quality scoring

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp` | MCP server framework |
| `requests` | HTTP for static scraping |
| `httpx[http2]` | Async HTTP/2 scraping |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `trafilatura` | Content extraction for snippet scoring |
| `rank-bm25` | BM25 relevance scoring |
| `scikit-learn` | TF-IDF vectorization |
| `rapidfuzz` | Near-duplicate detection |
| `defusedxml` | XML security |
| `playwright` | JS-heavy site rendering (optional) |

## License

MIT
