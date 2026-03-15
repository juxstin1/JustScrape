# JustScrape

Layered intelligence web scraper + **MCP Server** that provides free web search and scraping capabilities to AI models.

## Features

- **MCP Server** - Expose web search and scraping as tools for Claude, LM Studio, or any MCP-compatible client
- **Free Web Search** - DuckDuckGo-based SERP search, no API keys required
- **Multi-Backend Search** - Pluggable backend system: DuckDuckGo (default), SearXNG (self-hosted), Brave Search (free tier)
- **Query Operators** - `site:`, `filetype:`, date range, domain exclusion built into the search API
- **Parallel Scraping** - Search results scraped concurrently via `asyncio.gather` (3-5x faster)
- **2-Layer Cache** - In-memory (5 min) + SQLite persistent (24 hr) — survives server restarts
- **Per-Domain Rate Limiting** - Scraping different domains doesn't throttle each other
- **Snippet Pre-Filtering** - Skips known-blocked domains and non-content URLs before scraping
- **HEAD Pre-Check** - Verifies pages are reachable HTML before committing to a full download
- **Relevance Scoring** - Scraped results ranked by query relevance (TF + title match + length)
- **Robots.txt Awareness** - Respects robots.txt to avoid wasting time on disallowed paths
- **Smart JS Fallback** - Multi-signal detection (noscript tags, script density, JS-required messages) not just content length
- **httpx + HTTP/2** - Async scraper with HTTP/2 multiplexing and connection pooling
- **Clean Extraction** - Strips ads, trackers, navigation, and bloat to extract actual content
- **LLM-Ready Output** - Markdown and plain text formats optimized for AI consumption
- **Interactive CLI** - Menu-driven interface with batch scraping, data extraction, and clipboard support

## Security

JustScrape includes hardened security for safe operation as an MCP server:

- **SSRF Protection** - All URLs validated before outbound requests; blocks private IPs (10.x, 172.16.x, 192.168.x, 127.x, 169.254.x), non-HTTP schemes (`file://`, `data://`, `javascript://`), and cloud metadata endpoints
- **XXE Defense** - Sitemap parsing uses `defusedxml` to block XML entity expansion attacks (Billion Laughs) and external entity injection
- **Browser Isolation** - Each Playwright scrape runs in an isolated browser context (separate cookies, storage, cache) to prevent cross-site data leakage
- **Response Size Caps** - Streaming HTTP reads with 10MB limit prevent memory exhaustion from oversized responses
- **Input Validation** - Query length (1000 chars), URL length (2048 chars), and content size (100K chars) are server-side capped
- **Concurrency Limits** - Global semaphore caps parallel outbound scrapes to prevent DDoS amplification
- **Sanitized Errors** - Exception details logged to stderr; only generic error messages returned to MCP clients
- **112 Security Tests** - Covering URL validation, XXE protection, SSRF blocking, adapter isolation, and classification

## MCP Server (For AI Models)

JustScrape can run as an MCP (Model Context Protocol) server, exposing tools that AI models can use directly.

### Available Tools

| Tool | Description |
|------|-------------|
| `web_search` | Free SERP search with operators (site:, filetype:, date range, exclude) |
| `scrape_url` | Clean content extraction with HEAD pre-check and robots.txt awareness |
| `search_and_scrape` | Search + parallel scrape with pre-filtering and relevance scoring |
| `extract_urls` | Extract all links from a webpage |

### Setup with Claude Desktop

Add to your Claude Desktop config (`~/.config/claude/claude_desktop_config.json` on Linux/Mac or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

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

### Setup with Other MCP Clients

Run the server directly:

```bash
python justscrape_mcp.py
```

The server communicates via stdio using the MCP protocol.

### Example: Web Search Tool

```json
{
  "name": "web_search",
  "arguments": {
    "query": "python web scraping tutorial",
    "num_results": 5,
    "site": "realpython.com",
    "date_range": "year"
  }
}
```

Returns:
```json
{
  "query": "python web scraping tutorial site:realpython.com",
  "results": [
    {
      "position": 1,
      "title": "Web Scraping with Python - Real Python",
      "url": "https://realpython.com/...",
      "snippet": "Learn how to scrape websites..."
    }
  ],
  "total_results": 5,
  "success": true,
  "cached": false
}
```

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│  justscrape_mcp.py  │     │  scrape_premium.py   │
│   (MCP Server)      │     │    (CLI interface)   │
└─────────┬───────────┘     └──────────┬───────────┘
          │                            │
          └────────────┬───────────────┘
                       ▼
              ┌────────────────────┐
              │  smart_scraper.py  │
              │  (intelligence)    │
              └────────┬───────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│web_scraper  │ │ js_scraper  │ │ web_search  │
│  (static)   │ │ (browser)   │ │   (SERP)    │
└─────────────┘ └─────────────┘ └─────────────┘
```

| Layer | Purpose |
|-------|---------|
| `justscrape_mcp.py` | MCP server — parallel scraping, pre-filtering, relevance scoring |
| `scrape_premium.py` | Interactive CLI with menus, batch processing, settings |
| `smart_scraper.py` | Multi-signal JS fallback detection, auto-routing |
| `web_scraper.py` | Static scraping with HEAD pre-check, robots.txt, per-domain rate limiting |
| `async_scraper.py` | httpx + HTTP/2 async scraper with connection pooling |
| `js_scraper.py` | Browser-based scraping via Playwright for JS-heavy sites |
| `web_search.py` | Multi-backend search with 2-layer cache and query operators |
| `backends/` | Pluggable search backends: DuckDuckGo, SearXNG, Brave Search |

## Installation

```bash
# Clone the repo
git clone https://github.com/juxstin1/JustScrape.git
cd JustScrape

# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (required for JS scraping)
playwright install chromium
```

## Usage

### Interactive Mode (Recommended)

**Windows:**
```bash
scrape.bat
```

**Linux/Mac:**
```bash
python scrape_premium.py
```

### Programmatic Usage

```python
from smart_scraper import scrape_article, extract_article_for_llm, scrape_with_extraction

# Basic article scraping
content = scrape_article("https://example.com/article")

# LLM-optimized extraction
llm_content = extract_article_for_llm("https://example.com/article")

# Extract specific data
emails = scrape_with_extraction("https://example.com", "emails")
phones = scrape_with_extraction("https://example.com", "phones")
urls = scrape_with_extraction("https://example.com", "urls")
```

```python
from web_scraper import WebScraper, ContentType, quick_scrape

# Quick scrape
text = quick_scrape("https://example.com")

# Full control
scraper = WebScraper(rate_limit=2.0)
result = scraper.scrape(
    "https://example.com",
    content_types=[
        ContentType.CLEAN_TEXT,
        ContentType.METADATA,
        ContentType.LINKS,
        ContentType.IMAGES
    ]
)
```

```python
from js_scraper import JavaScriptScraper, scrape_js_site

# Quick JS scrape
content = scrape_js_site("https://twitter.com/user")

# With custom wait
with JavaScriptScraper() as scraper:
    result = scraper.scrape("https://spa-site.com", custom_wait=".main-content")

    # Infinite scroll support
    result = scraper.scrape_with_scroll("https://infinite-scroll-site.com", scrolls=5)
```

## How It Works

### Smart Detection

Known JS-heavy domains trigger browser rendering automatically:
- twitter.com / x.com
- reddit.com
- instagram.com
- facebook.com
- linkedin.com
- medium.com
- substack.com
- youtube.com

### Content Extraction

1. Removes `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>`, `<aside>`
2. Strips elements matching ad/tracking patterns
3. Locates main content via `<article>`, `<main>`, or content-related classes
4. Deduplicates and cleans whitespace

### Ad/Tracker Blocking

Browser mode blocks:
- Google Analytics / Tag Manager
- DoubleClick
- Facebook Pixel
- Twitter tracking
- Generic ad patterns

## Dependencies

| Package | Purpose |
|---------|---------|
| requests | HTTP requests for static scraping |
| httpx[http2] | Async HTTP/2 scraping with connection pooling |
| beautifulsoup4 | HTML parsing |
| lxml | Fast HTML parser |
| defusedxml | XML security (XXE/entity expansion protection) |
| playwright | Headless browser for JS sites |
| mcp | MCP server framework |
| duckduckgo-search | Free web search (default backend) |
| click | Interactive CLI |
| pyperclip | Clipboard support (optional) |

## Multi-Backend Search

JustScrape supports pluggable search backends. DuckDuckGo is the default (no config needed).

### SearXNG (Self-Hosted Meta-Search)

Unlimited queries via 70+ search engines:

```bash
# Deploy SearXNG
docker run -d --name searxng -p 8080:8080 searxng/searxng

# Use in Python
from backends import SearXNGBackend, MultiSearch, DuckDuckGoBackend

multi = MultiSearch([
    SearXNGBackend(base_url="http://localhost:8080"),
    DuckDuckGoBackend(),  # fallback
])
result = multi.search("python web scraping", num_results=10)
```

### Brave Search (Free Tier)

2,000 queries/month with independent index:

```bash
export BRAVE_SEARCH_API_KEY="your-key-here"
```

```python
from backends import BraveSearchBackend
brave = BraveSearchBackend()
result = brave.search("python tutorial", num_results=5)
```

## Source Adapters

JustScrape includes non-browser adapters for sites that are hard to scrape statically:

| Adapter | Method | Sites |
|---------|--------|-------|
| Reddit JSON | API | reddit.com (subreddits, threads, comments) |
| Dev.to API | API | dev.to (articles, markdown content) |
| GitHub Discussions | HTML | github.com/*/discussions/* |
| StackExchange API | API | stackoverflow.com, superuser.com, serverfault.com, *.stackexchange.com |
| StackPrinter | HTML fallback | Stack Exchange (when API fails) |

## Future Roadmap

- **Docker Support** - Containerized deployment with Playwright for JS rendering
- **Proxy Rotation** - BrightData integration for scale
- **Vector DB Pipeline** - Chain to AnythingLLM or Qdrant for RAG workflows

## License

MIT
