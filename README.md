# JustScrape

Layered intelligence web scraper that automatically handles static vs. dynamic content while delivering clean, LLM-ready output without manual tweaks.

## Features

- **Smart Routing** - Domain-based JS detection (Twitter/X, Instagram, Reddit, etc.) plus content-length fallback prevents failures on SPAs
- **Auto-Fallback** - If static scraping returns minimal content, automatically switches to browser rendering
- **Clean Extraction** - Strips ads, trackers, navigation, and bloat to extract actual content
- **LLM-Ready Output** - Markdown and plain text formats optimized for AI consumption
- **Interactive CLI** - Menu-driven interface with batch scraping, data extraction, and clipboard support

## Architecture

```
scrape_premium.py  →  smart_scraper.py  →  web_scraper.py / js_scraper.py
   (CLI interface)      (intelligence)       (scraping engines)
```

| Layer | Purpose |
|-------|---------|
| `scrape_premium.py` | Interactive CLI with menus, batch processing, settings |
| `smart_scraper.py` | Auto-detection logic, fallback handling, output formatting |
| `web_scraper.py` | Fast static scraping via requests + BeautifulSoup |
| `js_scraper.py` | Browser-based scraping via Playwright for JS-heavy sites |

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
| click | Interactive CLI |
| pyperclip | Clipboard support (optional) |

## Future Roadmap

- **MCP Server Integration** - Expose `scrape_url` as a tool via JSON-RPC for Claude/LLM workflows
- **Docker Support** - Containerized deployment with Playwright for JS rendering
- **Proxy Rotation** - BrightData integration for scale
- **Vector DB Pipeline** - Chain to AnythingLLM or Qdrant for RAG workflows

## License

MIT
