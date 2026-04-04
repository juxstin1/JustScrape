"""
Smart Web Scraper - Unified interface that auto-detects best scraping method
Combines static and JavaScript scrapers with intelligent fallback
Integrates with sitemap registry for efficient URL discovery

Features:
- Multi-signal JS fallback detection (not just content length)
- Per-domain scraping intelligence
- Integrates with sitemap registry for URL discovery
"""

from typing import Optional, List, Dict, Union
from dataclasses import dataclass
from .web_scraper import WebScraper, ContentType, ScrapedContent, quick_scrape
from .sitemap_registry import SitemapRegistry
from urllib.parse import urlparse
from .url_validator import validate_url as _validate_url
from .adapters import get_adapter
# Re-export _safe_get so existing callers / test patches keep working.
from .adapters.base import _safe_get, MAX_ADAPTER_RESPONSE_SIZE  # noqa: F401
import re

# NOTE: js_scraper is imported lazily inside methods that need it


class SmartScraper:
    """
    Intelligent scraper that chooses the best method automatically.
    Uses multi-signal detection to decide between static and JS scraping.
    """

    # Domains known to be JS-heavy (always use browser)
    JS_HEAVY_DOMAINS = {
        'twitter.com', 'x.com', 'reddit.com', 'youtube.com',
        'instagram.com', 'facebook.com', 'linkedin.com',
        'medium.com', 'substack.com', 'discord.com'
    }

    # Patterns that indicate JS is needed
    JS_NEEDED_PATTERNS = re.compile(
        r'enable javascript|requires javascript|please turn on javascript|'
        r'javascript is required|javascript must be enabled|'
        r'this page requires javascript|browser does not support javascript',
        re.IGNORECASE
    )

    def __init__(
        self,
        min_content_length: int = 200,
        force_js: bool = False
    ):
        self.min_content_length = min_content_length
        self.force_js = force_js
        self.static_scraper = WebScraper()

    def _is_js_heavy_site(self, url: str) -> bool:
        """Check if URL is likely to need JavaScript rendering"""
        domain = urlparse(url).netloc.lower().replace('www.', '')
        return any(js_domain in domain for js_domain in self.JS_HEAVY_DOMAINS)

    def _try_source_adapter(
        self,
        url: str,
        content_types: List[ContentType],
    ) -> Optional[ScrapedContent]:
        """
        Try source-specific non-browser adapters before static/JS scraping.
        Returns ScrapedContent on adapter success, else None to continue fallback.
        """
        # SSRF protection: validate URL before any adapter makes outbound requests
        url_ok, _ = _validate_url(url)
        if not url_ok:
            return None

        adapter = get_adapter(url)
        if adapter is not None:
            return adapter.scrape(url, content_types)
        return None

    def _needs_javascript(self, html: str, content: str, url: str) -> bool:
        """
        Multi-signal decision for whether to fall back to JS rendering.
        Smarter than the old simple content-length check.
        """
        content_length = len(content) if content else 0

        # Known JS-heavy domains
        if self._is_js_heavy_site(url):
            return True

        # Short content + explicit JS requirement message in HTML
        if content_length < 500 and html and self.JS_NEEDED_PATTERNS.search(html):
            return True

        # Very short content + page has noscript tag or high script density
        if content_length < self.min_content_length and html:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                has_noscript = bool(soup.find('noscript'))
                script_count = len(soup.find_all('script'))

                if has_noscript or script_count > 5:
                    return True
            except Exception:
                pass

        # Fallback: just too short
        if content_length < self.min_content_length:
            return True

        return False

    def scrape(
        self,
        url: str,
        content_types: List[ContentType] = None,
        force_method: Optional[str] = None
    ) -> ScrapedContent:
        """
        Intelligently scrape URL using best method.

        Uses multi-signal detection to decide between static and JS scraping.
        """
        if content_types is None:
            content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]

        # SSRF protection: reject unsafe URLs before any network request
        url_ok, url_reason = _validate_url(url)
        if not url_ok:
            return ScrapedContent(url=url, status_code=0)

        # Try non-browser adapters first for known hard targets.
        adapter_result = self._try_source_adapter(url, content_types)
        if adapter_result is not None:
            return adapter_result

        # Determine scraping method
        use_js = (
            self.force_js or
            force_method == 'js' or
            (force_method != 'static' and self._is_js_heavy_site(url))
        )

        if not use_js:
            # Fetch raw HTML once (used for both content extraction and JS detection)
            raw_html = None
            try:
                raw_html, _ = self.static_scraper.fetch(url)
            except Exception:
                pass

            # Extract content from the fetched HTML
            if raw_html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(raw_html, 'html.parser')
                result = ScrapedContent(url=url, status_code=200, scrape_method='static')
                for ct in content_types:
                    if ct == ContentType.CLEAN_TEXT:
                        result.content = self.static_scraper.extract_clean_text(raw_html, soup)
                    elif ct == ContentType.METADATA:
                        result.metadata = self.static_scraper.extract_metadata(soup)
                        result.title = result.metadata.get('title')
                    elif ct == ContentType.LINKS:
                        result.links = self.static_scraper.extract_links(soup, url)
                    elif ct == ContentType.IMAGES:
                        result.images = self.static_scraper.extract_images(soup, url)
            else:
                result = ScrapedContent(url=url, status_code=0)

            # Multi-signal check: do we need JS?
            if not self._needs_javascript(raw_html, result.content, url):
                return result

            use_js = True

        if use_js:
            try:
                from .js_scraper import JavaScriptScraper
                with JavaScriptScraper() as js_scraper:
                    return js_scraper.scrape(url, content_types)
            except (ImportError, Exception):
                # Playwright not installed or JS scrape failed —
                # fall through to return static result if available
                pass

        # Return static result if we have one, otherwise empty
        try:
            return result
        except NameError:
            return ScrapedContent(url=url)

    def scrape_to_markdown(self, url: str) -> str:
        """
        Scrape and return clean markdown-formatted text
        Perfect for feeding to LLMs or saving as docs
        """
        result = self.scrape(url, [ContentType.CLEAN_TEXT, ContentType.METADATA])

        output = []

        # Add title
        if result.title:
            output.append(f"# {result.title}\n")

        # Add metadata
        if result.metadata:
            if result.metadata.get('description'):
                output.append(f"> {result.metadata['description']}\n")
            if result.metadata.get('author'):
                output.append(f"**Author:** {result.metadata['author']}")
            if result.metadata.get('published_date'):
                output.append(f"**Published:** {result.metadata['published_date']}")
            if result.metadata.get('author') or result.metadata.get('published_date'):
                output.append("")

        # Add main content
        if result.content:
            output.append(result.content)

        return '\n'.join(output)

    def scrape_to_dict(
        self,
        url: str,
        include_links: bool = False,
        force_method: Optional[str] = None,
    ) -> Dict:
        """Scrape and return as simple dictionary"""
        content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]
        if include_links:
            content_types.append(ContentType.LINKS)

        result = self.scrape(url, content_types, force_method=force_method)

        return {
            'url': result.url,
            'title': result.title,
            'content': result.content,
            'metadata': result.metadata,
            'links': result.links if include_links else None,
            'scrape_method': result.scrape_method,
            'status_code': result.status_code,
        }


# Utility functions
def scrape_article(url: str) -> str:
    """
    Scrape an article and return clean, readable text
    Automatically handles both static and JS sites
    """
    scraper = SmartScraper()
    return scraper.scrape_to_markdown(url)


def scrape_multiple_articles(urls: List[str]) -> List[Dict]:
    """
    Scrape multiple URLs and return as list of dictionaries
    """
    scraper = SmartScraper()
    results = []

    for url in urls:
        print(f"Scraping: {url}")
        result_dict = scraper.scrape_to_dict(url)
        results.append(result_dict)

    return results


def extract_article_for_llm(url: str) -> str:
    """
    Extract article optimized for LLM consumption
    Returns clean markdown with minimal metadata
    """
    scraper = SmartScraper()
    result = scraper.scrape(url, [ContentType.CLEAN_TEXT, ContentType.METADATA])

    # Simple format for LLM
    parts = []
    if result.title:
        parts.append(f"Title: {result.title}")
    if result.content:
        parts.append(f"\nContent:\n{result.content}")

    return '\n'.join(parts)


def scrape_and_summarize(url: str, max_length: int = 5000) -> str:
    """
    Scrape article and return truncated version if too long
    Useful for quick previews
    """
    content = scrape_article(url)

    if len(content) > max_length:
        return content[:max_length] + f"\n\n[Content truncated - {len(content)} total chars]"

    return content


def batch_scrape_to_files(urls: List[str], output_dir: str = "./scraped"):
    """
    Scrape multiple URLs and save each to a separate markdown file
    """
    import os
    from pathlib import Path
    from urllib.parse import urlparse

    Path(output_dir).mkdir(exist_ok=True)
    scraper = SmartScraper()

    for i, url in enumerate(urls):
        print(f"Scraping [{i+1}/{len(urls)}]: {url}")

        try:
            content = scraper.scrape_to_markdown(url)

            # Generate filename from URL
            parsed = urlparse(url)
            filename = parsed.netloc.replace('www.', '') + '_' + str(i) + '.md'
            filename = re.sub(r'[^\w\s-]', '', filename)

            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"  ✓ Saved to {filepath}")

        except Exception as e:
            print(f"  ✗ Error: {e}")


# Advanced utilities
def scrape_with_extraction(url: str, extract_pattern: str = None) -> List[str]:
    """
    Scrape and extract specific patterns (emails, phone numbers, etc.)

    Args:
        url: URL to scrape
        extract_pattern: Regex pattern to extract, or use preset:
                        'emails', 'phones', 'urls'
    """
    scraper = SmartScraper()
    result = scraper.scrape(url, [ContentType.CLEAN_TEXT])

    if not result.content:
        return []

    # Preset patterns
    patterns = {
        'emails': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phones': r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        'urls': r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
    }

    pattern = patterns.get(extract_pattern, extract_pattern)
    if not pattern:
        return []

    matches = re.findall(pattern, result.content, re.MULTILINE)
    return list(set(matches))  # Remove duplicates


def compare_scraping_methods(url: str) -> Dict:
    """
    Compare static vs JS scraping for a URL
    Useful for debugging which method works better
    """
    results = {
        'url': url,
        'static': None,
        'javascript': None,
        'recommendation': None
    }

    # Try static
    static_scraper = WebScraper()
    static_result = static_scraper.scrape(url, [ContentType.CLEAN_TEXT])
    results['static'] = {
        'success': bool(static_result.content),
        'length': len(static_result.content) if static_result.content else 0,
        'preview': static_result.content[:200] if static_result.content else None
    }

    # Try JS
    try:
        from .js_scraper import JavaScriptScraper
        with JavaScriptScraper() as js_scraper:
            js_result = js_scraper.scrape(url, [ContentType.CLEAN_TEXT])
            results['javascript'] = {
                'success': bool(js_result.content),
                'length': len(js_result.content) if js_result.content else 0,
                'preview': js_result.content[:200] if js_result.content else None
            }
    except Exception as e:
        results['javascript'] = {
            'success': False,
            'error': str(e)
        }

    # Recommendation
    if results['static']['success'] and results['static']['length'] > 200:
        results['recommendation'] = 'static'
    else:
        results['recommendation'] = 'javascript'

    return results


def scrape_from_sitemap(
    domain: str,
    limit: int = 10,
    unscraped_only: bool = True,
    auto_add: bool = True
) -> List[Dict]:
    """
    Scrape multiple URLs from a domain's sitemap

    Args:
        domain: Domain to scrape from (e.g., "example.com")
        limit: Maximum number of URLs to scrape
        unscraped_only: Only scrape URLs not previously scraped
        auto_add: Automatically add domain to registry if not found

    Returns:
        List of dictionaries with scraped content
    """
    registry = SitemapRegistry()

    # Check if domain has sitemap
    if not registry.has_sitemap(domain):
        if auto_add:
            print(f"Domain {domain} not in registry, fetching sitemap...")
            success = registry.add_domain(domain)
            if not success:
                print(f"Failed to fetch sitemap for {domain}")
                return []
        else:
            print(f"Domain {domain} not in registry")
            return []

    # Check if sitemap is stale
    if registry.is_stale(domain):
        print(f"Sitemap for {domain} is stale, refreshing...")
        registry.refresh_domain(domain)

    # Get URLs to scrape
    urls = registry.get_urls(domain, limit=limit, unscraped_only=unscraped_only)

    if not urls:
        print(f"No URLs found for {domain}")
        return []

    print(f"Scraping {len(urls)} URLs from {domain}...")

    # Scrape each URL
    scraper = SmartScraper()
    results = []

    for i, url in enumerate(urls):
        print(f"  [{i+1}/{len(urls)}] {url}")

        try:
            result = scraper.scrape_to_dict(url)
            results.append(result)

            # Mark as scraped in registry
            registry.mark_scraped(url)

        except Exception as e:
            print(f"    ✗ Error: {e}")

    print(f"\n✓ Scraped {len(results)}/{len(urls)} URLs")
    return results


def get_sitemap_urls(domain: str, limit: int = 100) -> List[str]:
    """
    Get URLs from a domain's sitemap without scraping

    Args:
        domain: Domain to get URLs from
        limit: Maximum URLs to return

    Returns:
        List of URLs
    """
    registry = SitemapRegistry()

    if not registry.has_sitemap(domain):
        print(f"Fetching sitemap for {domain}...")
        registry.add_domain(domain)

    return registry.get_urls(domain, limit=limit)


if __name__ == '__main__':
    # Example usage
    url = "https://example.com"

    print("=== Smart Scraper Examples ===\n")

    # Simple article scraping
    print("1. Scraping article...")
    content = scrape_article(url)
    print(f"Content length: {len(content)} chars\n")

    # Extract specific data
    print("2. Extracting emails...")
    emails = scrape_with_extraction(url, 'emails')
    print(f"Found {len(emails)} emails\n")

    # Compare methods
    print("3. Comparing scraping methods...")
    comparison = compare_scraping_methods(url)
    print(f"Recommendation: {comparison['recommendation']}\n")

    # Sitemap-based scraping
    print("4. Scraping from sitemap...")
    results = scrape_from_sitemap("example.com", limit=5)
    print(f"Scraped {len(results)} articles from sitemap\n")
