"""
Advanced Web Scraper - Cuts through bloated sites to extract clean, useful content
Supports both static and JavaScript-heavy sites with intelligent content extraction
"""

import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, List, Union
import json
import time
from urllib.parse import urljoin, urlparse
import re
from dataclasses import dataclass, asdict
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
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class WebScraper:
    """
    Main scraper class with intelligent content extraction
    """
    
    def __init__(
        self,
        user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        timeout: int = 30,
        rate_limit: float = 1.0
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
        self.last_request_time = 0
    
    def _rate_limit_wait(self):
        """Enforce rate limiting between requests"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self.last_request_time = time.time()
    
    def fetch(self, url: str) -> tuple[Optional[str], int]:
        """
        Fetch raw HTML from URL
        Returns (html_content, status_code)
        """
        self._rate_limit_wait()
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            return response.text, response.status_code
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
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
        
        # Remove common ad/tracking classes
        ad_patterns = [
            'ad', 'advertisement', 'banner', 'promo', 'sponsor',
            'popup', 'modal', 'cookie', 'newsletter', 'sidebar',
            'social', 'share', 'comment', 'related', 'recommended'
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
            except:
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
