# JustScrape

Free web search for AI that returns the exact answer, not 25 links.

## What It Does

You ask an AI model "what's the difference between `dict.get()` and `dict[]` in Python?" The AI calls JustScrape. Here's what happens:

**1. It understands your question first.** Before searching, it figures out this is a `code` question about `Python` and `dict`. This matters because it changes how results get ranked later — Stack Overflow and docs.python.org will be prioritized over random blogs.

**2. It searches 70+ engines at once.** A self-hosted [SearXNG](https://github.com/searxng/searxng) instance sends your query to Google, Bing, DuckDuckGo, Wikipedia, Stack Overflow, and dozens more — simultaneously. Results that appear in multiple engines rank higher. No API keys, no rate limits — you own the instance.

**3. It reranks by who actually knows the answer.** SearXNG returns 25 results ranked by "how many engines agreed." JustScrape reranks them by "who's actually authoritative for this type of question." For a Python code question, Stack Overflow (authority: 1.0) beats a Medium blog post (authority: 0.3), even if Google ranked the blog higher.

**4. It scrapes the pages and greps for the answer.** This is the core. It fetches the top pages, strips them to clean text, chunks the text into sections, then scores every chunk against your query using BM25 and TF-IDF. A 20,000 character Stack Overflow page becomes the 500 characters that specifically explain `dict.get()` vs `dict[]`.

**5. It scores, deduplicates, and returns.** Each result gets a composite score (relevance × authority × freshness × search position). Near-identical snippets from different sources get deduplicated. The AI gets back ~1,000 tokens of precisely targeted content instead of ~5,000+ tokens of raw page dumps.

**The result:** 3 scored results, each containing only the paragraph that answers the question, with metadata about where it came from and how confident the scoring is.

## Why

Perplexity, Tavily, and Exa charge for this. JustScrape does it free with open source parts. The only infrastructure is a Docker container running SearXNG on your machine.

AI models waste context window on irrelevant content. When you dump a full web page into a prompt, the model has to find the answer buried in navigation, ads, sidebars, and unrelated content. JustScrape does that extraction before the tokens are spent.

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/juxstin1/JustScrape.git
cd JustScrape
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Start SearXNG (one-time setup)
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

# 3. Verify it works
curl "http://localhost:8080/search?q=test&format=json" | python -m json.tool
```

Add to your AI client (Claude Desktop, or any MCP-compatible host):

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

After that, your AI can call `search_and_scrape` and get answers from the web.

## What Comes Back

```json
{
  "success": true,
  "query": "python dict.get() vs [] KeyError",
  "results": [
    {
      "title": "Python dict.get() raises KeyError - Stack Overflow",
      "url": "https://stackoverflow.com/questions/...",
      "content": "dict.get(key, default) returns the default value if key is missing. dict[key] raises KeyError. Use .get() when the key might not exist...",
      "best_sentence": "dict.get(key, default) returns the default value if key is missing instead of raising KeyError",
      "relevance_score": 0.45,
      "score_breakdown": {
        "relevance": 0.65,
        "authority": 1.0,
        "freshness": null,
        "position": 0.70
      },
      "source_type": "forum",
      "confidence": 0.85,
      "scraped_successfully": true
    }
  ],
  "total_results": 3
}
```

`content` is the extracted snippet — the part of the page that actually answers the query. `best_sentence` is the single most relevant sentence. `score_breakdown` shows why this result ranked where it did.

## The Pipeline

```
"python dict.get() vs [] KeyError"
         │
         ▼
┌─────────────────┐
│  QueryAnalyzer  │  intent: code, entities: [python, dict, KeyError]
│                 │  This changes how everything downstream scores.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    SearXNG      │  Sends query to Google + Bing + 70 engines.
│  (localhost)    │  Returns 25 results ranked by cross-engine agreement.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ResultReranker  │  Intent is "code" → Stack Overflow gets authority 1.0,
│                 │  Medium gets 0.3. Reorders by who actually knows.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Scrape + Extract│  Fetches top pages concurrently.
│                 │  Strips HTML → chunks text → scores every chunk
│                 │  against the query with BM25 + TF-IDF.
│                 │  20,000 char page → 500 chars that answer the question.
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  QualityScorer  │  Composite score: relevance (45%) × authority (20%)
│                 │  × freshness (0-25%) × position (15%)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     Dedup       │  "These two Stack Overflow answers say the same thing"
│                 │  → keeps the higher-scored one.
└────────┬────────┘
         │
         ▼
    3 results
   ~1,000 tokens
```

## Token Cost

| Results | Tokens | Compared to raw scraping |
|---------|--------|--------------------------|
| 1 | ~350 | was ~1,300 |
| 2 | ~850 | was ~3,500 |
| 3 | ~1,200 | was ~5,200 |

The difference is snippet extraction. Raw scraping dumps the full page. JustScrape returns only the chunks that matched the query.

## MCP Tools

| Tool | What It Does |
|------|-------------|
| `search_and_scrape` | Full pipeline — search, rerank, scrape, extract, score, dedup |
| `web_search` | Just the search results, no scraping |
| `scrape_url` | Scrape a single URL |
| `extract_urls` | Pull all links from a page |

## SearXNG

JustScrape's only search backend is a self-hosted SearXNG Docker container. SearXNG is a free meta-search engine that queries Google, Bing, and 70+ other engines from your machine.

**Why not use Google/Bing/DuckDuckGo directly?**
- Google blocks server-side requests with CAPTCHAs
- Bing does the same
- DuckDuckGo rate-limits aggressively and returns empty results
- SearXNG runs on your machine, makes requests that look like normal browser traffic, and has been doing this for years

**Managing it:**

```bash
sudo docker start searxng    # Start
sudo docker stop searxng     # Stop
sudo docker logs searxng     # Debug
```

If SearXNG isn't running, JustScrape returns a clear error with the docker command to start it.

## Security

- **SSRF Protection** — blocks private IPs, non-HTTP schemes, cloud metadata endpoints
- **XXE Defense** — `defusedxml` for XML parsing
- **Browser Isolation** — Playwright scrapes in isolated contexts
- **Size Caps** — 10MB response limit, 1000 char query limit, 100K content limit
- **Concurrency Limits** — semaphore prevents DDoS amplification
- **215 tests** passing

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for full version history and details on every fix.

## License

MIT
