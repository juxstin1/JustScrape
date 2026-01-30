"""
JustScrape MCP Worker v1 - Refined Contract

Based on empirical testing that proved:
- "success" != usable content (Medium, Reddit)
- Failures come in distinct classes (blocked, thin, encoding-failure)
- Signals are reliable (char count + keyword fingerprints)

This worker NEVER returns boolean success.
Usability is explicitly classified.
Bot walls are first-class outcomes.

Usage:
    python worker.py

Tools:
    search_sources - DuckDuckGo search
    retrieve_source - Scrape with classification
    research_with_sources - Search + scrape with failure separation
    extract_urls - Link extraction
"""

import json
import re
import sys
import traceback

from web_search import search_full
from web_scraper import WebScraper, ContentType

# Lazy import SmartScraper to avoid Playwright requirement at startup
_smart_scraper = None


def get_smart_scraper():
    global _smart_scraper
    if _smart_scraper is None:
        try:
            from smart_scraper import SmartScraper
            _smart_scraper = SmartScraper()
        except ImportError:
            _smart_scraper = "static_only"
    return _smart_scraper


# =============================================================================
# CLASSIFICATION ENGINE - Empirically validated heuristics
# =============================================================================

# Patterns that indicate bot walls (validated against Medium, Reddit, Cloudflare)
BLOCKED_PATTERNS = [
    r'verify you are human',
    r'captcha',
    r'cloudflare',
    r'blocked by network security',
    r'please enable javascript',
    r'just a moment\.\.\.',
    r'checking your browser',
    r'ray id:',
    r'access denied',
    r'bot detection',
]

# Compile for efficiency
BLOCKED_REGEX = re.compile('|'.join(BLOCKED_PATTERNS), re.IGNORECASE)


def classify_content(content: str, title: str, had_html: bool, encoding_error: bool, method: str) -> dict:
    """
    Classify retrieval outcome based on empirically validated signals.

    Returns:
        {
            "status": "usable | thin | blocked | encoding-failure | empty",
            "confidence": "high | medium | low",
            "detected_patterns": [...]
        }
    """
    content = content or ""
    title = title or ""
    content_length = len(content)
    detected_patterns = []

    # RULE 1: Encoding failure is a hard failure
    if encoding_error:
        return {
            "status": "encoding-failure",
            "confidence": "high",
            "detected_patterns": ["encoding_error"]
        }

    # RULE 2: Empty content
    if content_length == 0:
        return {
            "status": "empty",
            "confidence": "high",
            "detected_patterns": ["no_content"]
        }

    # RULE 3: Check for bot wall signatures
    # This catches Cloudflare, Reddit blocks, etc.
    # CRITICAL: Only flag as blocked if content is SHORT
    # Long content with these words is probably an article ABOUT the topic
    combined_text = f"{title} {content}".lower()
    matches = BLOCKED_REGEX.findall(combined_text)

    # Bot walls are always short (< 1000 chars typically)
    # Articles about captcha/scraping will be long
    if matches and content_length < 1500:
        detected_patterns.extend(list(set(matches)))
        confidence = "high" if content_length < 500 else "medium"
        return {
            "status": "blocked",
            "confidence": confidence,
            "detected_patterns": detected_patterns
        }

    # RULE 4: Title-only signals (e.g., "Just a moment...")
    if title.lower() in ["just a moment...", "attention required", "access denied"]:
        return {
            "status": "blocked",
            "confidence": "high",
            "detected_patterns": [f"title:{title}"]
        }

    # RULE 5: Thin content (< 500 chars)
    # Validated: example.com = 129 chars, blocked pages ~300 chars
    if content_length < 500:
        return {
            "status": "thin",
            "confidence": "high" if content_length < 200 else "medium",
            "detected_patterns": [f"content_length:{content_length}"]
        }

    # RULE 6: Usable content
    # Validated: Wikipedia 28K, ScrapingBee 53K, IPWay 12K
    # Check for paragraph-like structure (multiple line breaks)
    has_paragraphs = content.count('\n\n') >= 2 or content.count('\n') >= 5

    if content_length >= 5000 and has_paragraphs:
        confidence = "high"
    elif content_length >= 2000:
        confidence = "high" if has_paragraphs else "medium"
    elif content_length >= 500:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "status": "usable",
        "confidence": confidence,
        "detected_patterns": []
    }


# =============================================================================
# TOOL: search_sources (unchanged - did its job)
# =============================================================================

def search_sources(query: str, num_results: int = 10) -> dict:
    """Search via DuckDuckGo. Returns ranked results without content."""
    return search_full(query, num_results)


# =============================================================================
# TOOL: retrieve_source (REFINED - the key fix)
# =============================================================================

def retrieve_source(url: str, allow_javascript: bool = True) -> dict:
    """
    Retrieve and classify a single URL.

    NEVER returns boolean success.
    Always returns signals and classification.

    Returns:
        {
            "url": str,
            "title": str | None,
            "content": str | None,
            "signals": {
                "content_length": int,
                "method": "static" | "javascript",
                "had_html": bool,
                "encoding_error": bool
            },
            "classification": {
                "status": "usable" | "thin" | "blocked" | "encoding-failure" | "empty",
                "confidence": "high" | "medium" | "low",
                "detected_patterns": [...]
            }
        }
    """
    encoding_error = False
    method = "static"
    had_html = False
    content = None
    title = None

    try:
        scraper = get_smart_scraper()

        if scraper == "static_only" or not allow_javascript:
            ws = WebScraper()
            result = ws.scrape(url, [ContentType.CLEAN_TEXT, ContentType.METADATA])
            content = result.content
            title = result.title
            had_html = result.status_code == 200
            method = "static"
        else:
            result = scraper.scrape_to_dict(url)
            content = result.get('content')
            title = result.get('title')
            method = result.get('scrape_method', result.get('method', 'unknown'))
            if 'javascript' in method.lower():
                method = 'javascript'
            else:
                method = 'static'
            had_html = True

    except UnicodeEncodeError:
        encoding_error = True
    except UnicodeDecodeError:
        encoding_error = True
    except Exception as e:
        error_str = str(e).lower()
        if 'encode' in error_str or 'decode' in error_str or 'charmap' in error_str:
            encoding_error = True
        else:
            # Re-raise non-encoding errors
            raise

    # Build signals
    signals = {
        "content_length": len(content) if content else 0,
        "method": method,
        "had_html": had_html,
        "encoding_error": encoding_error
    }

    # Classify the result
    classification = classify_content(
        content=content,
        title=title,
        had_html=had_html,
        encoding_error=encoding_error,
        method=method
    )

    return {
        "url": url,
        "title": title,
        "content": content,
        "signals": signals,
        "classification": classification
    }


# =============================================================================
# TOOL: research_with_sources (REFINED - separates successes from failures)
# =============================================================================

def research_with_sources(query: str, limit: int = 5, allow_javascript: bool = True, max_content_length: int = 5000) -> dict:
    """
    Search + retrieve with explicit failure separation.

    Returns:
        {
            "query": str,
            "sources": [...],  # Only usable sources
            "failures": [...], # Blocked, thin, encoding failures
            "metrics": {
                "total": int,
                "usable_count": int,
                "usable_rate": float,
                "blocked_count": int,
                "thin_count": int
            }
        }
    """
    # Search
    search_result = search_full(query, limit)

    if not search_result.get("success", False):
        return {
            "query": query,
            "sources": [],
            "failures": [],
            "metrics": {"total": 0, "usable_count": 0, "usable_rate": 0.0},
            "search_error": search_result.get("error", "Search failed")
        }

    sources = []
    failures = []

    for r in search_result.get("results", []):
        url = r.get("url", "")
        if not url:
            continue

        try:
            retrieved = retrieve_source(url, allow_javascript=allow_javascript)
            status = retrieved["classification"]["status"]

            # Truncate content if needed
            content = retrieved.get("content") or ""
            if len(content) > max_content_length:
                content = content[:max_content_length] + f"\n\n[Truncated - {len(retrieved.get('content', ''))} total chars]"

            entry = {
                "url": url,
                "title": retrieved.get("title") or r.get("title"),
                "snippet": r.get("snippet"),
                "status": status,
                "method": retrieved["signals"]["method"],
                "content_length": retrieved["signals"]["content_length"]
            }

            if status == "usable":
                entry["content"] = content
                sources.append(entry)
            else:
                entry["reason"] = retrieved["classification"]["detected_patterns"]
                failures.append(entry)

        except Exception as e:
            failures.append({
                "url": url,
                "title": r.get("title"),
                "status": "error",
                "reason": str(e)
            })

    # Compute metrics
    total = len(sources) + len(failures)
    usable_count = len(sources)
    blocked_count = len([f for f in failures if f.get("status") == "blocked"])
    thin_count = len([f for f in failures if f.get("status") == "thin"])

    return {
        "query": query,
        "sources": sources,
        "failures": failures,
        "metrics": {
            "total": total,
            "usable_count": usable_count,
            "usable_rate": round(usable_count / total, 2) if total > 0 else 0.0,
            "blocked_count": blocked_count,
            "thin_count": thin_count
        }
    }


# =============================================================================
# TOOL: extract_urls (unchanged)
# =============================================================================

def extract_urls(url: str, filter_external: bool = False) -> dict:
    """Extract all links from a page."""
    from urllib.parse import urlparse

    scraper = WebScraper()
    result = scraper.scrape(url, [ContentType.LINKS])
    links = result.links or []

    if filter_external:
        source_domain = urlparse(url).netloc.lower().replace('www.', '')
        links = [
            link for link in links
            if urlparse(link).netloc.lower().replace('www.', '') != source_domain
        ]

    return {
        "source_url": url,
        "urls": links,
        "count": len(links)
    }


# =============================================================================
# LEGACY ALIASES (for backwards compatibility)
# =============================================================================

def web_search(query: str, num_results: int = 10) -> dict:
    """Alias for search_sources"""
    return search_sources(query, num_results)

def scrape_url(url: str, include_links: bool = False) -> dict:
    """Alias for retrieve_source (legacy)"""
    return retrieve_source(url, allow_javascript=True)

def search_and_scrape(query: str, limit: int = 3, max_content_length: int = 5000) -> dict:
    """Alias for research_with_sources (legacy)"""
    return research_with_sources(query, limit, True, max_content_length)


# =============================================================================
# TOOL REGISTRY
# =============================================================================

TOOLS = {
    # v1 refined API
    "search_sources": search_sources,
    "retrieve_source": retrieve_source,
    "research_with_sources": research_with_sources,
    "extract_urls": extract_urls,

    # Legacy aliases
    "web_search": web_search,
    "scrape_url": scrape_url,
    "search_and_scrape": search_and_scrape,
}


# =============================================================================
# WORKER MAIN LOOP
# =============================================================================

def send(obj):
    """Send JSON response to stdout"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def error(msg):
    """Send error response"""
    send({"ok": False, "error": msg})


def main():
    """Main worker loop"""
    send({
        "ok": True,
        "status": "ready",
        "version": "1.0.0",
        "tools": list(TOOLS.keys())
    })

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            job = json.loads(line)
            tool = job.get("tool")
            args = job.get("args", {})

            if tool not in TOOLS:
                error(f"Unknown tool: {tool}. Available: {list(TOOLS.keys())}")
                continue

            result = TOOLS[tool](**args)
            send({"ok": True, "result": result})

        except json.JSONDecodeError as e:
            error(f"Invalid JSON: {e}")
        except TypeError as e:
            error(f"Invalid arguments: {e}")
        except Exception:
            error(traceback.format_exc())


if __name__ == "__main__":
    main()
