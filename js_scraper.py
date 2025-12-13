"""
Advanced Web Scraper with JavaScript Support
Handles modern SPAs and JavaScript-heavy sites using Playwright
"""

from playwright.sync_api import sync_playwright, Page, Browser
from typing import Optional, Dict, List
import time
from dataclasses import dataclass
from web_scraper import ScrapedContent, ContentType
from bs4 import BeautifulSoup


@dataclass
class ScraperConfig:
    """Configuration for advanced scraping"""
    headless: bool = True
    timeout: int = 30000  # milliseconds
    wait_for_selector: Optional[str] = None
    wait_for_timeout: int = 2000  # Wait for JS to execute
    block_resources: List[str] = None  # Block ads, trackers, etc.
    
    def __post_init__(self):
        if self.block_resources is None:
            # Default blocked resources to speed up scraping
            self.block_resources = [
                '*google-analytics.com*',
                '*googletagmanager.com*',
                '*doubleclick.net*',
                '*facebook.com/tr*',
                '*facebook.net*',
                '*twitter.com/i/adsct*',
                '*.ads.*',
                '*advertising*',
                '*ad-*.js',
                '*analytics*.js'
            ]


class JavaScriptScraper:
    """
    Scraper that handles JavaScript-heavy sites
    Uses Playwright to render pages fully before extraction
    """
    
    def __init__(self, config: ScraperConfig = None):
        self.config = config or ScraperConfig()
        self.playwright = None
        self.browser = None
    
    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.config.headless)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
    
    def _setup_page(self, page: Page):
        """Setup page with resource blocking and other optimizations"""
        # Block unwanted resources
        def route_handler(route):
            if any(pattern in route.request.url for pattern in self.config.block_resources):
                route.abort()
            else:
                route.continue_()
        
        page.route("**/*", route_handler)
        
        # Set viewport for consistent rendering
        page.set_viewport_size({"width": 1920, "height": 1080})
    
    def scrape(
        self,
        url: str,
        content_types: List[ContentType] = None,
        custom_wait: Optional[str] = None
    ) -> ScrapedContent:
        """
        Scrape a JavaScript-heavy site
        
        Args:
            url: URL to scrape
            content_types: Types of content to extract
            custom_wait: Custom CSS selector to wait for before scraping
        
        Returns:
            ScrapedContent object
        """
        if content_types is None:
            content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]
        
        if not self.browser:
            raise RuntimeError("Use this scraper in a context manager (with statement)")
        
        page = self.browser.new_page()
        self._setup_page(page)
        
        try:
            # Navigate to page
            page.goto(url, wait_until='networkidle', timeout=self.config.timeout)
            
            # Wait for specific selector if provided
            wait_selector = custom_wait or self.config.wait_for_selector
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=self.config.timeout)
            else:
                # Default wait for JavaScript execution
                time.sleep(self.config.wait_for_timeout / 1000)
            
            # Get rendered HTML
            html = page.content()
            
            # Extract content similar to regular scraper
            soup = BeautifulSoup(html, 'html.parser')
            result = ScrapedContent(url=url, status_code=200)
            
            for content_type in content_types:
                if content_type == ContentType.CLEAN_TEXT:
                    result.content = self._extract_clean_text(soup)
                
                elif content_type == ContentType.METADATA:
                    result.metadata = self._extract_metadata(soup, page)
                    result.title = result.metadata.get('title')
                
                elif content_type == ContentType.LINKS:
                    result.links = self._extract_links(soup, url)
                
                elif content_type == ContentType.IMAGES:
                    result.images = self._extract_images(soup, url)
                
                elif content_type == ContentType.FULL_HTML:
                    result.content = html
            
            return result
            
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return ScrapedContent(url=url, status_code=0)
        
        finally:
            page.close()
    
    def _extract_clean_text(self, soup: BeautifulSoup) -> str:
        """Extract clean text from rendered page"""
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 
                           'aside', 'form', 'iframe', 'noscript']):
            element.decompose()
        
        # Find main content
        main_content = (
            soup.find('article') or 
            soup.find('main') or 
            soup.find(class_=['content', 'article', 'post', 'entry']) or
            soup.find('body')
        )
        
        if main_content:
            text = main_content.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            return '\n\n'.join(lines)
        
        return soup.get_text(separator='\n', strip=True)
    
    def _extract_metadata(self, soup: BeautifulSoup, page: Page) -> Dict:
        """Extract metadata including page title"""
        metadata = {}
        
        # Get title from page object (more reliable for SPAs)
        metadata['title'] = page.title()
        
        # Extract meta tags
        for meta in soup.find_all('meta'):
            name = meta.get('name', '').lower()
            property_name = meta.get('property', '').lower()
            content = meta.get('content', '')
            
            if name == 'description':
                metadata['description'] = content
            elif property_name == 'og:title':
                metadata['og_title'] = content
            elif property_name == 'og:description':
                metadata['og_description'] = content
        
        return metadata
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract links"""
        from urllib.parse import urljoin
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            absolute_url = urljoin(base_url, href)
            links.append(absolute_url)
        return list(set(links))
    
    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract images"""
        from urllib.parse import urljoin
        images = []
        for img in soup.find_all('img', src=True):
            src = img['src']
            absolute_url = urljoin(base_url, src)
            images.append(absolute_url)
        return list(set(images))
    
    def scrape_with_scroll(self, url: str, scrolls: int = 3) -> ScrapedContent:
        """
        Scrape infinite scroll pages by scrolling multiple times
        
        Args:
            url: URL to scrape
            scrolls: Number of times to scroll to bottom
        """
        if not self.browser:
            raise RuntimeError("Use this scraper in a context manager")
        
        page = self.browser.new_page()
        self._setup_page(page)
        
        try:
            page.goto(url, wait_until='networkidle', timeout=self.config.timeout)
            
            # Scroll to load more content
            for _ in range(scrolls):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)  # Wait for content to load
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            result = ScrapedContent(url=url, status_code=200)
            result.content = self._extract_clean_text(soup)
            result.metadata = self._extract_metadata(soup, page)
            result.title = result.metadata.get('title')
            
            return result
            
        finally:
            page.close()
    
    def screenshot(self, url: str, output_path: str, full_page: bool = True):
        """Take a screenshot of the page"""
        if not self.browser:
            raise RuntimeError("Use this scraper in a context manager")
        
        page = self.browser.new_page()
        self._setup_page(page)
        
        try:
            page.goto(url, wait_until='networkidle', timeout=self.config.timeout)
            page.screenshot(path=output_path, full_page=full_page)
            print(f"Screenshot saved to {output_path}")
        finally:
            page.close()


# Convenience functions
def scrape_js_site(url: str, wait_for: Optional[str] = None) -> str:
    """
    Quick scrape for JavaScript-heavy sites
    
    Args:
        url: URL to scrape
        wait_for: CSS selector to wait for before scraping
    
    Returns:
        Clean text content
    """
    with JavaScriptScraper() as scraper:
        result = scraper.scrape(url, [ContentType.CLEAN_TEXT], wait_for)
        return result.content


def scrape_spa(url: str, wait_timeout: int = 3000) -> ScrapedContent:
    """
    Scrape Single Page Application with custom wait time
    
    Args:
        url: URL to scrape
        wait_timeout: Milliseconds to wait for JS execution
    """
    config = ScraperConfig(wait_for_timeout=wait_timeout)
    with JavaScriptScraper(config) as scraper:
        return scraper.scrape(url, [ContentType.CLEAN_TEXT, ContentType.METADATA])


if __name__ == '__main__':
    # Example usage
    print("=== JavaScript Scraper Example ===")
    
    # Scrape a JavaScript-heavy site
    with JavaScriptScraper() as scraper:
        result = scraper.scrape(
            "https://example.com",
            content_types=[ContentType.CLEAN_TEXT, ContentType.METADATA]
        )
        print(f"Title: {result.title}")
        print(f"Content: {result.content[:200] if result.content else 'No content'}...")
