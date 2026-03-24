# JustScrape

[![PyPI](https://img.shields.io/pypi/v/justscrape)](https://pypi.org/project/justscrape/)
[![CI](https://github.com/juxstin1/JustScrape/actions/workflows/ci.yml/badge.svg)](https://github.com/juxstin1/JustScrape/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://pypi.org/project/justscrape/)

An MCP server that gives AI models web search and scraping. Returns the exact relevant snippet, not a wall of text.

Perplexity, Tavily, and Exa charge for this. JustScrape does it free with no API keys.

## Install

```bash
uvx justscrape
```

Or with pip:

```bash
pip install justscrape
```

Add to your AI client:

```json
{
  "mcpServers": {
    "justscrape": {
      "command": "uvx",
      "args": ["justscrape"]
    }
  }
}
```

Or configure **all your AI tools at once** with [add-mcp](https://github.com/neondatabase/add-mcp):

```bash
npx add-mcp "uvx justscrape" -g -y --all
```

That's it. Your AI can now call `search_and_scrape` and get answers from the web.

## Works Everywhere

<details>
<summary>Claude Desktop / Cursor / VS Code / LM Studio</summary>

Add to your MCP config file:
```json
{
  "mcpServers": {
    "justscrape": {
      "command": "uvx",
      "args": ["justscrape"]
    }
  }
}
```

Config file locations:
- **Claude Desktop:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows)
- **Cursor:** `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project)
- **VS Code:** `.vscode/mcp.json` (project)
- **LM Studio:** Edit `mcp.json` in Settings > MCP

</details>

<details>
<summary>Claude Code</summary>

Project-level (`.mcp.json`):
```json
{
  "mcpServers": {
    "justscrape": {
      "command": "uvx",
      "args": ["justscrape"]
    }
  }
}
```

Or global (`~/.claude.json`).

</details>

<details>
<summary>OpenAI Codex</summary>

Add to `~/.codex/config.toml` (or `.codex/config.toml` for project scope):
```toml
[mcp_servers.justscrape]
command = "uvx"
args = ["justscrape"]
```

</details>

<details>
<summary>OpenCode</summary>

Add to `opencode.json`:
```json
{
  "mcp": {
    "justscrape": {
      "type": "local",
      "command": ["uvx", "justscrape"]
    }
  }
}
```

</details>

<details>
<summary>Zed</summary>

Add to `~/.config/zed/settings.json`:
```json
{
  "context_servers": {
    "justscrape": {
      "command": {
        "path": "uvx",
        "args": ["justscrape"]
      }
    }
  }
}
```

</details>

<details>
<summary>Gemini CLI</summary>

Add to `~/.gemini/settings.json`:
```json
{
  "mcpServers": {
    "justscrape": {
      "command": "uvx",
      "args": ["justscrape"]
    }
  }
}
```

</details>

## How It Works

Your AI asks "what's the difference between `dict.get()` and `dict[]` in Python?" and calls JustScrape:

1. **Query analysis** — classifies as a `code` question about `Python` and `dict`, so Stack Overflow and docs.python.org get priority over blogs
2. **Multi-engine search** — SearXNG (if set up) queries Google, Bing, and 70+ engines simultaneously. Without SearXNG, falls back to DuckDuckGo. No API keys.
3. **Authority reranking** — Stack Overflow (authority: 1.0) beats Medium (0.3) for code questions, regardless of Google's ranking
4. **Snippet extraction** — fetches top pages concurrently, strips to clean text, scores every chunk with BM25 + TF-IDF. A 20,000 char page becomes the 500 chars that answer the question.
5. **Score and dedup** — composite score (relevance x authority x freshness x position), near-duplicate removal

**Result:** 3 scored results, ~1,000 tokens of precisely targeted content instead of ~5,000+ tokens of raw page dumps.

```json
{
  "query": "python dict.get() vs [] KeyError",
  "results": [
    {
      "title": "Python dict.get() vs bracket notation - Stack Overflow",
      "url": "https://stackoverflow.com/questions/...",
      "content": "dict.get(key, default) returns the default value if key is missing. dict[key] raises KeyError. Use .get() when the key might not exist...",
      "best_sentence": "dict.get(key, default) returns the default value if key is missing instead of raising KeyError",
      "relevance_score": 0.82,
      "score_breakdown": {
        "relevance": 0.88,
        "authority": 1.0,
        "freshness": null,
        "position": 0.90
      },
      "source_type": "forum",
      "confidence": 0.85
    }
  ],
  "total_results": 3
}
```

## MCP Tools

| Tool | What It Does |
|------|-------------|
| `search_and_scrape` | Full pipeline — search, rerank, scrape, extract, score, dedup |
| `web_search` | Search results only, no scraping |
| `scrape_url` | Scrape a single URL to clean text |
| `extract_urls` | Pull all links from a page |
| `get_stats` | Cache and browser pool status |

## Upgrade Search Quality (Optional)

JustScrape works out of the box with DuckDuckGo. For better results, set up SearXNG — a self-hosted meta-search engine that aggregates 70+ engines from your machine:

```bash
justscrape setup
```

Pulls the Docker image, starts the container, verifies it's working. JustScrape auto-detects it — no config changes needed.

<details>
<summary>Why SearXNG is better</summary>

- Aggregates Google + Bing + 70 engines (cross-engine agreement = better ranking)
- Runs on your machine — no rate limits, no CAPTCHAs
- JustScrape uses it automatically when available, falls back to DuckDuckGo when not

```bash
sudo docker start searxng    # Start
sudo docker stop searxng     # Stop
sudo docker logs searxng     # Debug
```

</details>

## Optional: Browser Rendering

For JS-heavy sites (SPAs, dynamic content):

```bash
pip install "justscrape[browser]"
playwright install chromium
```

Without this, JustScrape uses static scraping with automatic fallback — works for most sites.

## Health Check

```bash
justscrape doctor
```

## Security

- **SSRF protection** — blocks private IPs, non-HTTP schemes, cloud metadata endpoints
- **XXE defense** — `defusedxml` for all XML parsing
- **Browser isolation** — Playwright scrapes in isolated contexts
- **Size caps** — 10MB response limit, 1000 char query limit, 100K content limit
- **Concurrency limits** — per-domain semaphores prevent amplification

## License

MIT
