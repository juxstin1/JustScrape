"""
Browser pool and pooled scraper for JustScrape.

LazyBrowserPool: Thread-safe singleton for Playwright browser lifecycle.
PooledSmartScraper: SmartScraper subclass using the pooled browser for JS rendering.
"""

import atexit
import threading
import time

from .smart_scraper import SmartScraper
from .url_validator import validate_url


class LazyBrowserPool:
    """
    Lazy browser pool for Playwright - only initializes when first needed.
    Keeps browser warm for subsequent requests.
    Thread-safe singleton pattern.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._playwright = None
        self._browser = None
        self._init_lock = threading.Lock()
        self._last_used = 0
        self._initialized = True

        # Register cleanup on exit
        atexit.register(self.shutdown)

    def _ensure_browser(self):
        """Lazily initialize browser on first use"""
        if self._browser is not None:
            self._last_used = time.time()
            return

        with self._init_lock:
            if self._browser is not None:
                return

            try:
                from playwright.sync_api import sync_playwright

                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
                self._last_used = time.time()
            except Exception as e:
                self._browser = None
                raise RuntimeError(f"Failed to initialize browser: {e}")

    def get_browser(self):
        """Get the browser instance, initializing if needed"""
        self._ensure_browser()
        return self._browser

    def is_initialized(self) -> bool:
        """Check if browser is initialized"""
        return self._browser is not None

    def get_stats(self) -> dict:
        """Get pool statistics"""
        return {
            "initialized": self.is_initialized(),
            "last_used": self._last_used,
            "idle_seconds": int(time.time() - self._last_used)
            if self._last_used
            else None,
        }

    def shutdown(self):
        """Shutdown browser and playwright"""
        with self._init_lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None

            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None


# Global browser pool (lazy singleton)
_browser_pool = LazyBrowserPool()


class PooledSmartScraper(SmartScraper):
    """
    SmartScraper that uses the lazy browser pool for JS rendering.
    Avoids cold starts on every JS scrape.
    """

    def scrape(self, url, content_types=None, force_method=None):
        """Override to use pooled browser for JS scraping"""
        from .web_scraper import ContentType, ScrapedContent

        if content_types is None:
            content_types = [ContentType.CLEAN_TEXT, ContentType.METADATA]

        # SSRF protection: reject unsafe URLs before any network request
        url_ok, _ = validate_url(url)
        if not url_ok:
            return ScrapedContent(url=url, status_code=0)

        # Try non-browser adapters first (e.g., reddit JSON).
        adapter_result = self._try_source_adapter(url, content_types)
        if adapter_result is not None:
            return adapter_result

        # Determine if we need JS
        use_js = (
            self.force_js
            or force_method == "js"
            or (force_method != "static" and self._is_js_heavy_site(url))
        )

        if not use_js:
            # Try static first
            result = self.static_scraper.scrape(url, content_types)
            content_ok = (
                result.content and len(result.content) >= self.min_content_length
            )

            if content_ok:
                return result

            use_js = True

        # Use pooled browser for JS — fall back to static if Playwright unavailable
        if use_js:
            try:
                return self._scrape_with_pooled_browser(url, content_types)
            except Exception:
                # Playwright not installed or browser failed — try static as last resort
                result = self.static_scraper.scrape(url, content_types)
                if result.content:
                    return result
                return ScrapedContent(url=url)

        # Unreachable, but safe fallback
        return ScrapedContent(url=url)

    def _scrape_with_pooled_browser(self, url, content_types):
        """Scrape using pooled browser"""
        from .web_scraper import ScrapedContent, ContentType
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse

        # Block non-HTTP schemes before Playwright navigation (prevents file:// access)
        scheme = urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(
                f"URL scheme '{scheme}' is not allowed for browser scraping"
            )

        browser = _browser_pool.get_browser()
        # Use isolated browser context per scrape to prevent cookie/storage leakage
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            java_script_enabled=True,
        )
        page = context.new_page()

        try:
            # Block tracking/ads
            def route_handler(route):
                blocked_patterns = [
                    "google-analytics",
                    "googletagmanager",
                    "doubleclick",
                    "facebook.com/tr",
                    "facebook.net",
                    "twitter.com/i/adsct",
                ]
                if any(p in route.request.url for p in blocked_patterns):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", route_handler)

            # Navigate
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)  # Let JS settle

            html = page.content()
            soup = BeautifulSoup(html, "lxml")

            # Extract content
            title = soup.title.string if soup.title else None

            # Remove junk
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()

            # Find main content
            main = soup.find("article") or soup.find("main") or soup.find("body")
            content = main.get_text(separator="\n", strip=True) if main else ""

            # Clean up
            lines = [line.strip() for line in content.split("\n") if line.strip()]
            content = "\n".join(lines)

            # Extract metadata
            metadata = {}
            if ContentType.METADATA in content_types:
                meta_desc = soup.find("meta", attrs={"name": "description"})
                if meta_desc:
                    metadata["description"] = meta_desc.get("content", "")

            # Extract links
            links = None
            if ContentType.LINKS in content_types:
                links = [a.get("href") for a in soup.find_all("a", href=True)]
                links = [l for l in links if l.startswith("http")]

            return ScrapedContent(
                url=url,
                title=title,
                content=content,
                metadata=metadata,
                links=links,
                images=None,
                structured_data=None,
                scrape_method="javascript_pooled",
            )

        finally:
            page.close()
            context.close()
