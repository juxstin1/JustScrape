"""
Advanced Web Scraper - Cuts through bloated sites to extract clean, useful content
Supports both static and JavaScript-heavy sites with intelligent content extraction

Features:
- HEAD pre-check to skip non-HTML, blocked, or oversized responses
- Per-domain rate limiting (scraping different domains doesn't throttle each other)
- Robots.txt awareness (caches per domain, respects crawl-delay)
"""

import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, List, Union, Tuple
import json
import time
import threading
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import re
from dataclasses import dataclass, asdict, field
from enum import Enum


class ContentType(Enum):
    """Types of content extraction"""
    CLEAN_TEXT = "clean_text"  # Main article/content only
    FULL_HTML = "full_html"    # Complete HTML
    STRUCTURED = "structured"   # Structured data extraction
    LINKS = "links"            # Extract all links
    IMAGES = "images"          # Extract all images
    METADATA = "metadata"      # Meta tags and SEO data


@dataclass
class ScrapedContent:
    """Container for scraped content"""
    url: str
    title: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict] = None
    links: Optional[List[str]] = None
    images: Optional[List[str]] = None
    structured_data: Optional[Dict] = None
    status_code: Optional[int] = None
    scrape_method: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# =============================================================================
# ROBOTS.TXT CACHE
# =============================================================================

class RobotsCache:
    """Cache robots.txt per domain to avoid wasting time on disallowed paths."""
    _cache: Dict[str, RobotFileParser] = {}
    _lock = threading.Lock()
    _user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    _MAX_SIZE = 500

    @classmethod
    def can_fetch(cls, url: str) -> bool:
        """Check if URL is allowed by robots.txt. Returns True on failure (permissive)."""
        try:
            domain = urlparse(url).netloc.lower()

            # Check cache first (lock only for read)
            with cls._lock:
                if domain in cls._cache:
                    entry = cls._cache[domain]
                    rp = entry[0] if entry else None
                    ts = entry[1] if entry else 0
                    # TTL: re-fetch after 24 hours
                    if time.time() - ts < 86400:
                        if rp is None:
                            return True
                        return rp.can_fetch(cls._user_agent, url)

            # Fetch robots.txt OUTSIDE the lock (with short timeout)
            rp = RobotFileParser()
            robots_url = f"https://{domain}/robots.txt"
            rp.set_url(robots_url)
            try:
                import urllib.request
                with urllib.request.urlopen(robots_url, timeout=3) as resp:
                    raw = resp.read(100_000).decode("utf-8", errors="replace")
                    rp.parse(raw.splitlines())
            except Exception:
                rp = None

            # Store result (lock only for write)
            with cls._lock:
                if len(cls._cache) >= cls._MAX_SIZE:
                    oldest = next(iter(cls._cache))
                    del cls._cache[oldest]
                cls._cache[domain] = (rp, time.time())

            if rp is None:
                return True
            return rp.can_fetch(cls._user_agent, url)
        except Exception:
            return True

    @classmethod
    def get_crawl_delay(cls, url: str) -> Optional[float]:
        """Get crawl-delay from robots.txt if specified."""
        try:
            domain = urlparse(url).netloc.lower()
            with cls._lock:
                rp = cls._cache.get(domain)
                if rp:
                    delay = rp.crawl_delay(cls._user_agent)
                    return delay
        except Exception:
            pass
        return None


# =============================================================================
# HEAD PRE-CHECK
# =============================================================================

def head_pre_check(url: str, session: requests.Session = None, timeout: int = 5) -> Tuple[bool, Dict]:
    """
    Lightweight HEAD request to check if URL is worth a full GET.

    Returns:
        (should_fetch, info_dict)
    """
    try:
        s = session or requests.Session()
        resp = s.head(url, allow_redirects=True, timeout=timeout,
                      headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})

        info = {
            "status_code": resp.status_code,
            "final_url": resp.url,
            "content_type": resp.headers.get('content-type', ''),
            "content_length": resp.headers.get('content-length', ''),
        }

        # SSRF: re-validate the final URL after redirects
        if resp.url != url:
            from .url_validator import validate_url as _validate_url
            url_ok, reason = _validate_url(resp.url)
            if not url_ok:
                return False, {**info, "reason": f"redirect_ssrf:{reason}"}

        # Block on auth/forbidden/rate-limited
        if resp.status_code in (401, 403, 429, 451):
            return False, {**info, "reason": f"status:{resp.status_code}"}

        # Block on non-HTML content types
        ct = info["content_type"].lower()
        html_types = ('text/html', 'text/plain', 'application/xhtml')
        if ct and not any(t in ct for t in html_types):
            return False, {**info, "reason": f"content_type:{ct}"}

        # Block on very large responses (>5MB probably not articles)
        if info["content_length"]:
            try:
                size = int(info["content_length"])
                if size > 5 * 1024 * 1024:
                    return False, {**info, "reason": f"too_large:{size}"}
            except ValueError:
                pass

        # Check if redirect went to a login page
        final_path = urlparse(resp.url).path.lower()
        if any(p in final_path for p in ['/login', '/signin', '/signup', '/auth']):
            return False, {**info, "reason": f"redirect_to_login:{resp.url}"}

        return True, info

    except requests.RequestException:
        # If HEAD fails, let the GET try anyway
        return True, {"reason": "head_failed"}


# =============================================================================
# PER-DOMAIN RATE LIMITING FOR SCRAPER
# =============================================================================

class _ScraperDomainLimiter:
    """Per-domain rate limiting for the web scraper."""
    _MAX_DOMAINS = 1000

    def __init__(self, default_delay: float = 1.0):
        self.default_delay = default_delay
        self._domains: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str):
        domain = urlparse(url).netloc.lower()
        with self._lock:
            # Evict oldest if at capacity
            if domain not in self._domains and len(self._domains) >= self._MAX_DOMAINS:
                oldest = min(self._domains, key=self._domains.get)
                del self._domains[oldest]
            now = time.time()
            next_allowed = self._domains.get(domain, 0.0)
            wait_time = max(0, next_allowed - now)
            self._domains[domain] = now + wait_time + self.default_delay
        if wait_time > 0:
            time.sleep(wait_time)

_scraper_limiter = _ScraperDomainLimiter(default_delay=1.0)


class WebScraper:
    """
    Main scraper class with intelligent content extraction.
    Features per-domain rate limiting, HEAD pre-checks, and robots.txt awareness.
    """

    def __init__(
        self,
        user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        timeout: int = 30,
        rate_limit: float = 1.0,
        use_head_check: bool = True,
        respect_robots: bool = True,
    ):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.use_head_check = use_head_check
        self.respect_robots = respect_robots
        self.last_request_time = 0

    def _rate_limit_wait(self, url: str = None):
        """Enforce per-domain rate limiting between requests"""
        if url:
            _scraper_limiter.wait(url)
        else:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
            self.last_request_time = time.time()

    def fetch(self, url: str) -> tuple[Optional[str], int]:
        """
        Fetch raw HTML from URL with optional HEAD pre-check and robots.txt respect.
        Returns (html_content, status_code)
        """
        # SSRF protection: validate URL before any outbound request
        from .url_validator import validate_url
        url_ok, url_reason = validate_url(url)
        if not url_ok:
            return None, 0

        # Check robots.txt
        if self.respect_robots and not RobotsCache.can_fetch(url):
            return None, 403

        # HEAD pre-check
        if self.use_head_check:
            should_fetch, info = head_pre_check(url, self.session, timeout=min(self.timeout, 5))
            if not should_fetch:
                return None, info.get("status_code", 0)

        self._rate_limit_wait(url)

        try:
            _MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10MB
            response = self.session.get(url, timeout=self.timeout, stream=True)
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536, decode_unicode=True):
                if chunk:
                    total += len(chunk)
                    if total > _MAX_RESPONSE_SIZE:
                        break
                    chunks.append(chunk)
            return "".join(chunks), response.status_code
        except requests.RequestException as e:
            return None, 0
    
    def extract_clean_text(self, html: str, soup: BeautifulSoup = None) -> str:
        """
        Extract clean, readable text from HTML by removing bloat
        """
        if soup is None:
            soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 
                           'aside', 'form', 'iframe', 'noscript']):
            element.decompose()
        
        # Remove common ad/tracking classes (use word boundaries to avoid false positives)
        # e.g., 'ad' should not match 'header', 'download', 'reading'
        ad_patterns = [
            r'\bad[s]?\b', r'\badvertisement\b', r'\bbanner\b', r'\bpromo\b', r'\bsponsor\b',
            r'\bpopup\b', r'\bmodal\b', r'\bcookie\b', r'\bnewsletter\b', r'\bsidebar\b',
            r'\bsocial\b', r'\bshare\b', r'\bcomments?\b', r'\brelated\b', r'\brecommended\b'
        ]

        for pattern in ad_patterns:
            for element in soup.find_all(class_=re.compile(pattern, re.I)):
                element.decompose()
            for element in soup.find_all(id=re.compile(pattern, re.I)):
                element.decompose()
        
        # Try to find main content area
        main_content = (
            soup.find('article') or 
            soup.find('main') or 
            soup.find(class_=re.compile('content|article|post|entry', re.I)) or
            soup.find(id=re.compile('content|article|post|entry', re.I)) or
            soup.find('body')
        )
        
        if main_content:
            # Get text and clean up whitespace
            text = main_content.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            # Remove duplicate consecutive lines
            cleaned_lines = []
            prev = None
            for line in lines:
                if line != prev:
                    cleaned_lines.append(line)
                    prev = line
            return '\n\n'.join(cleaned_lines)
        
        return soup.get_text(separator='\n', strip=True)
    
    def extract_metadata(self, soup: BeautifulSoup) -> Dict:
        """Extract metadata from HTML"""
        metadata = {
            'title': None,
            'description': None,
            'keywords': None,
            'author': None,
            'published_date': None,
            'og_data': {},
            'twitter_data': {}
        }
        
        # Title
        title_tag = soup.find('title')
        metadata['title'] = title_tag.string if title_tag else None
        
        # Meta tags
        for meta in soup.find_all('meta'):
            name = meta.get('name', '').lower()
            property_name = meta.get('property', '').lower()
            content = meta.get('content', '')
            
            if name == 'description':
                metadata['description'] = content
            elif name == 'keywords':
                metadata['keywords'] = content
            elif name == 'author':
                metadata['author'] = content
            elif 'date' in name or 'published' in name:
                metadata['published_date'] = content
            
            # OpenGraph
            if property_name.startswith('og:'):
                metadata['og_data'][property_name] = content
            
            # Twitter Cards
            if name.startswith('twitter:'):
                metadata['twitter_data'][name] = content
        
        return metadata
    
    def extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract all links from page"""
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Convert relative URLs to absolute
            absolute_url = urljoin(base_url, href)
            links.append(absolute_url)
        return list(set(links))  # Remove duplicates
    
    def extract_images(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract all images from page"""
        images = []
        for img in soup.find_all('img', src=True):
            src = img['src']
            absolute_url = urljoin(base_url, src)
            images.append(absolute_url)
        return list(set(images))
    
    def extract_structured_data(self, soup: BeautifulSoup) -> Dict:
        """Extract JSON-LD and other structured data"""
        structured = {
            'json_ld': [],
            'microdata': []
        }
        
        # JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                structured['json_ld'].append(data)
            except Exception:
                pass
        
        return structured
    
    def scrape(
        self,
        url: str,
        content_types: List[ContentType] = None
    ) -> ScrapedContent:
        """
        Main scraping method - extracts content based on specified types
        
        Args:
            url: URL to scrape
            content_types: List of ContentType enums to extract
                          If None, extracts CLEAN_TEXT and METADATA
        
        Returns:
            ScrapedContent object with requested data
        """
        if content_types is None:
            content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]
        
        # Fetch HTML
        html, status_code = self.fetch(url)
        
        if not html:
            return ScrapedContent(url=url, status_code=status_code)
        
        soup = BeautifulSoup(html, 'html.parser')
        result = ScrapedContent(url=url, status_code=status_code)
        
        # Extract based on requested types
        for content_type in content_types:
            if content_type == ContentType.CLEAN_TEXT:
                result.content = self.extract_clean_text(html, soup)
            
            elif content_type == ContentType.FULL_HTML:
                result.content = html
            
            elif content_type == ContentType.METADATA:
                result.metadata = self.extract_metadata(soup)
                result.title = result.metadata.get('title')
            
            elif content_type == ContentType.LINKS:
                result.links = self.extract_links(soup, url)
            
            elif content_type == ContentType.IMAGES:
                result.images = self.extract_images(soup, url)
            
            elif content_type == ContentType.STRUCTURED:
                result.structured_data = self.extract_structured_data(soup)
        
        return result
    
    def scrape_multiple(
        self,
        urls: List[str],
        content_types: List[ContentType] = None
    ) -> List[ScrapedContent]:
        """Scrape multiple URLs"""
        results = []
        for url in urls:
            result = self.scrape(url, content_types)
            results.append(result)
        return results


# Convenience functions
def quick_scrape(url: str, clean_only: bool = True) -> str:
    """
    Quick scrape - just get the clean text content
    
    Args:
        url: URL to scrape
        clean_only: If True, returns only clean text. If False, returns ScrapedContent object
    
    Returns:
        Clean text content or ScrapedContent object
    """
    scraper = WebScraper()
    result = scraper.scrape(url, [ContentType.CLEAN_TEXT, ContentType.METADATA])
    
    if clean_only:
        return result.content
    return result


def scrape_with_links(url: str) -> Dict:
    """Scrape content and extract all links"""
    scraper = WebScraper()
    result = scraper.scrape(
        url, 
        [ContentType.CLEAN_TEXT, ContentType.METADATA, ContentType.LINKS]
    )
    return {
        'title': result.title,
        'content': result.content,
        'links': result.links
    }


def scrape_for_llm(url: str) -> str:
    """
    Scrape and format for LLM consumption
    Returns clean markdown-like text with title and content
    """
    scraper = WebScraper()
    result = scraper.scrape(url, [ContentType.CLEAN_TEXT, ContentType.METADATA])
    
    output = []
    if result.title:
        output.append(f"# {result.title}\n")
    if result.metadata and result.metadata.get('description'):
        output.append(f"*{result.metadata['description']}*\n")
    if result.content:
        output.append(result.content)
    
    return '\n'.join(output)


if __name__ == '__main__':
    # Example usage
    scraper = WebScraper(rate_limit=2.0)
    
    # Quick scrape example
    print("=== Quick Scrape ===")
    text = quick_scrape("https://example.com")
    print(text[:500] if text else "Failed to scrape")
    
    # Full scrape example
    print("\n=== Full Scrape ===")
    result = scraper.scrape(
        "https://example.com",
        content_types=[
            ContentType.CLEAN_TEXT,
            ContentType.METADATA,
            ContentType.LINKS,
            ContentType.IMAGES
        ]
    )
    print(f"Title: {result.title}")
    print(f"Content length: {len(result.content) if result.content else 0}")
    print(f"Links found: {len(result.links) if result.links else 0}")
    print(f"Images found: {len(result.images) if result.images else 0}")
