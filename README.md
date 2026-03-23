# JustScrape

Free web search for AI that returns the exact answer, not 25 links.

## Install

```bash
# One command — works immediately
uvx justscrape
```

Or with pip:

```bash
pip install justscrape
```

Then add to your AI client:

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

## What It Does

You ask an AI model "what's the difference between `dict.get()` and `dict[]` in Python?" The AI calls JustScrape. Here's what happens:

**1. It understands your question first.** Before searching, it figures out this is a `code` question about `Python` and `dict`. This matters because it changes how results get ranked later — Stack Overflow and docs.python.org will be prioritized over random blogs.

**2. It searches multiple engines.** SearXNG (if set up) sends your query to Google, Bing, DuckDuckGo, Wikipedia, Stack Overflow, and dozens more — simultaneously. Without SearXNG, it falls back to DuckDuckGo automatically. No API keys required.

**3. It reranks by who actually knows the answer.** Results get reranked by authority for the question type. For a Python code question, Stack Overflow (authority: 1.0) beats a Medium blog post (authority: 0.3), even if Google ranked the blog higher.

**4. It scrapes the pages and greps for the answer.** It fetches the top pages, strips them to clean text, chunks the text into sections, then scores every chunk against your query using BM25 and TF-IDF. A 20,000 character page becomes the 500 characters that actually answer the question.

**5. It scores, deduplicates, and returns.** Each result gets a composite score (relevance x authority x freshness x position). Near-identical snippets get deduplicated. The AI gets ~1,000 tokens of precisely targeted content instead of ~5,000+ tokens of raw page dumps.

## What Comes Back

```json
{
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
| `web_search` | Just the search results, no scraping |
| `scrape_url` | Scrape a single URL |
| `extract_urls` | Pull all links from a page |
| `get_stats` | Cache and browser pool status for debugging |

## Upgrade Search Quality (Optional)

JustScrape works out of the box with DuckDuckGo. For the best results, set up SearXNG — a self-hosted meta-search engine that queries Google, Bing, and 70+ engines from your machine:

```bash
justscrape setup
```

This pulls the SearXNG Docker image and starts it. JustScrape auto-detects it — no config changes needed.

**Why SearXNG is better:**
- Aggregates Google + Bing + 70 engines (cross-engine agreement = better ranking)
- Runs on your machine — no rate limits, no CAPTCHAs
- JustScrape automatically uses it when available, falls back to DuckDuckGo when not

**Managing SearXNG:**
```bash
sudo docker start searxng    # Start
sudo docker stop searxng     # Stop
sudo docker logs searxng     # Debug
```

## Health Check

```bash
justscrape doctor
```

Reports Python version, MCP SDK, SearXNG status, Playwright availability, and Docker.

## Optional Extras

```bash
# Browser rendering for JS-heavy sites
pip install "justscrape[browser]"
playwright install chromium

# Interactive CLI
pip install "justscrape[cli]"
```

## Token Cost

| Results | Tokens | Compared to raw scraping |
|---------|--------|--------------------------|
| 1 | ~350 | was ~1,300 |
| 2 | ~850 | was ~3,500 |
| 3 | ~1,200 | was ~5,200 |

The difference is snippet extraction. Raw scraping dumps the full page. JustScrape returns only the chunks that matched the query.

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
