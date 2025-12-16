# JustScrape

Layered intelligence web scraper + **MCP Server** that provides free web search and scraping capabilities to AI models.

## Features

- **MCP Server** - Expose web search and scraping as tools for Claude, LM Studio, or any MCP-compatible client
- **Free Web Search** - DuckDuckGo-based SERP search, no API keys required
- **Smart Routing** - Domain-based JS detection (Twitter/X, Instagram, Reddit, etc.) plus content-length fallback
- **Auto-Fallback** - If static scraping returns minimal content, automatically switches to browser rendering
- **Clean Extraction** - Strips ads, trackers, navigation, and bloat to extract actual content
- **LLM-Ready Output** - Markdown and plain text formats optimized for AI consumption
- **Interactive CLI** - Menu-driven interface with batch scraping, data extraction, and clipboard support

## MCP Server (For AI Models)

JustScrape can run as an MCP (Model Context Protocol) server, exposing tools that AI models can use directly.

### Available Tools

| Tool | Description |
|------|-------------|
| `web_search` | Free SERP-style search via DuckDuckGo |
| `scrape_url` | Clean content extraction from any URL |
| `search_and_scrape` | Search + fetch top results in one call |
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
    "num_results": 5
  }
}
```

Returns:
```json
{
  "query": "python web scraping tutorial",
  "results": [
    {
      "position": 1,
      "title": "Web Scraping with Python - Real Python",
      "url": "https://realpython.com/...",
      "snippet": "Learn how to scrape websites..."
    }
  ],
  "total_results": 5,
  "success": true
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
| `justscrape_mcp.py` | MCP server exposing tools for AI models |
| `scrape_premium.py` | Interactive CLI with menus, batch processing, settings |
| `smart_scraper.py` | Auto-detection logic, fallback handling, output formatting |
| `web_scraper.py` | Fast static scraping via requests + BeautifulSoup |
| `js_scraper.py` | Browser-based scraping via Playwright for JS-heavy sites |
| `web_search.py` | Free web search via DuckDuckGo |

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
| beautifulsoup4 | HTML parsing |
| lxml | Fast HTML parser |
| playwright | Headless browser for JS sites |
| mcp | MCP server framework |
| duckduckgo-search | Free web search |
| click | Interactive CLI |
| pyperclip | Clipboard support (optional) |

## Future Roadmap

- **Docker Support** - Containerized deployment with Playwright for JS rendering
- **Proxy Rotation** - BrightData integration for scale
- **Vector DB Pipeline** - Chain to AnythingLLM or Qdrant for RAG workflows
- **SearXNG Integration** - Self-hosted meta-search as alternative to DuckDuckGo

## License

MIT
