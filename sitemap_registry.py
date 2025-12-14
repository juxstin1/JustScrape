"""
Sitemap Registry - Database-backed sitemap storage and URL discovery system
Provides efficient URL discovery without web search APIs by leveraging sitemaps

Architecture:
- SQLite database for persistent storage of sitemaps and URLs
- XML parser for sitemap.xml and sitemap index files
- Deduplication to avoid re-scraping
- Staleness detection to refresh outdated sitemaps
- Integration hooks for smart_scraper.py
"""

import sqlite3
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, urljoin
import requests
import hashlib
import gzip
from io import BytesIO


# Database location - store in user home directory alongside scraper config
DB_PATH = Path.home() / ".scraper_sitemap_registry.db"


@dataclass
class SitemapInfo:
    """Container for sitemap metadata"""
    domain: str                      # Base domain (e.g., "example.com")
    sitemap_url: str                 # Full URL to sitemap.xml
    content_hash: str                # SHA-256 hash of sitemap content for change detection
    last_fetched: datetime           # When we last fetched this sitemap
    url_count: int                   # Number of URLs in this sitemap
    status: str                      # "success", "failed", "pending"
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['last_fetched'] = self.last_fetched.isoformat() if self.last_fetched else None
        return data


@dataclass
class SitemapURL:
    """Container for individual URLs from sitemaps"""
    url: str                         # Full URL
    domain: str                      # Parent domain
    last_modified: Optional[str]     # Last modified date from sitemap (if available)
    priority: Optional[float]        # Priority from sitemap (0.0-1.0)
    change_frequency: Optional[str]  # Change frequency hint ("daily", "weekly", etc.)
    scraped: bool = False            # Whether we've scraped this URL yet
    scraped_at: Optional[datetime] = None


class SitemapRegistry:
    """
    Main registry class - handles sitemap storage, parsing, and URL retrieval

    Usage:
        registry = SitemapRegistry()

        # Add a domain and fetch its sitemap
        registry.add_domain("example.com")

        # Get all URLs from a domain
        urls = registry.get_urls("example.com")

        # Check if sitemap exists and is fresh
        has_sitemap = registry.has_sitemap("example.com")
    """

    def __init__(self, db_path: Path = DB_PATH, staleness_days: int = 7):
        """
        Initialize the registry

        Args:
            db_path: Path to SQLite database file
            staleness_days: Number of days before a sitemap is considered stale
        """
        self.db_path = db_path
        self.staleness_days = staleness_days
        self._init_database()

    def _init_database(self):
        """Create database tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Sitemaps table - stores sitemap metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sitemaps (
                domain TEXT PRIMARY KEY,
                sitemap_url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                last_fetched TIMESTAMP NOT NULL,
                url_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                error_message TEXT
            )
        """)

        # URLs table - stores individual URLs from sitemaps
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sitemap_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                domain TEXT NOT NULL,
                last_modified TEXT,
                priority REAL,
                change_frequency TEXT,
                scraped BOOLEAN DEFAULT 0,
                scraped_at TIMESTAMP,
                UNIQUE(url),
                FOREIGN KEY (domain) REFERENCES sitemaps(domain) ON DELETE CASCADE
            )
        """)

        # Create indexes for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_domain
            ON sitemap_urls(domain)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scraped
            ON sitemap_urls(scraped, domain)
        """)

        conn.commit()
        conn.close()

    def _extract_domain(self, url: str) -> str:
        """
        Extract clean domain from URL

        Args:
            url: Full URL or domain

        Returns:
            Clean domain without www prefix
        """
        if not url.startswith('http'):
            url = 'https://' + url

        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Remove www prefix for consistency
        return domain.replace('www.', '')

    def _generate_sitemap_urls(self, domain: str) -> List[str]:
        """
        Generate common sitemap URL patterns for a domain

        Args:
            domain: Domain to generate sitemap URLs for

        Returns:
            List of possible sitemap URLs to try
        """
        base_url = f"https://{domain}"

        return [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap-index.xml",
            f"{base_url}/sitemap1.xml",
            f"{base_url}/post-sitemap.xml",
            f"{base_url}/page-sitemap.xml",
            f"https://www.{domain}/sitemap.xml",  # Try with www
        ]

    def _fetch_sitemap(self, sitemap_url: str, verbose: bool = False) -> Optional[bytes]:
        """
        Fetch sitemap content from URL

        Args:
            sitemap_url: URL to sitemap.xml
            verbose: Print detailed error messages

        Returns:
            Raw sitemap content as bytes, or None if failed
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; SitemapBot/1.0)',
                'Accept-Encoding': 'gzip, deflate'
            }

            response = requests.get(sitemap_url, headers=headers, timeout=30)
            response.raise_for_status()

            # Handle gzipped sitemaps
            if sitemap_url.endswith('.gz'):
                with gzip.GzipFile(fileobj=BytesIO(response.content)) as f:
                    return f.read()

            return response.content

        except requests.RequestException as e:
            if verbose:
                print(f"Error fetching sitemap {sitemap_url}: {e}")
            return None

    def _parse_sitemap(self, content: bytes, base_url: str, debug: bool = False) -> Tuple[List[SitemapURL], List[str]]:
        """
        Parse sitemap XML and extract URLs

        Handles both regular sitemaps and sitemap index files

        Args:
            content: Raw XML content as bytes
            base_url: Base URL for resolving relative URLs
            debug: Print debug information

        Returns:
            Tuple of (list of SitemapURL objects, list of child sitemap URLs)
        """
        try:
            root = ET.fromstring(content)

            # Handle XML namespaces (sitemaps use xmlns)
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            urls = []
            child_sitemaps = []

            if debug:
                print(f"  [DEBUG] Root tag: {root.tag}")

            # Check if this is a sitemap index (contains <sitemap> tags)
            sitemap_tags = root.findall('.//sm:sitemap', ns) or root.findall('.//sitemap')

            if debug:
                print(f"  [DEBUG] Found {len(sitemap_tags)} sitemap tags")

            if sitemap_tags:
                # This is a sitemap index - extract child sitemap URLs
                for i, sitemap in enumerate(sitemap_tags):
                    # Use findtext() to avoid Element truthiness issues with 'or'
                    # (Elements with no children evaluate to False)
                    loc_text = sitemap.findtext('sm:loc', default='', namespaces=ns).strip()
                    if not loc_text:
                        loc_text = sitemap.findtext('loc', default='').strip()

                    if loc_text:
                        child_sitemaps.append(loc_text)

                if debug:
                    print(f"  [DEBUG] Extracted {len(child_sitemaps)} child sitemap URLs")

                return urls, child_sitemaps

            # This is a regular sitemap - extract URLs
            url_tags = root.findall('.//sm:url', ns) or root.findall('.//url')

            for url_tag in url_tags:
                # Extract location (required) - use findtext() to avoid Element truthiness issues
                url_text = url_tag.findtext('sm:loc', default='', namespaces=ns).strip()
                if not url_text:
                    url_text = url_tag.findtext('loc', default='').strip()

                if not url_text:
                    continue

                # Extract optional fields using findtext()
                lastmod_text = url_tag.findtext('sm:lastmod', default='', namespaces=ns).strip()
                if not lastmod_text:
                    lastmod_text = url_tag.findtext('lastmod', default='').strip()

                priority_text = url_tag.findtext('sm:priority', default='', namespaces=ns).strip()
                if not priority_text:
                    priority_text = url_tag.findtext('priority', default='').strip()

                changefreq_text = url_tag.findtext('sm:changefreq', default='', namespaces=ns).strip()
                if not changefreq_text:
                    changefreq_text = url_tag.findtext('changefreq', default='').strip()

                sitemap_url = SitemapURL(
                    url=url_text,
                    domain=self._extract_domain(base_url),
                    last_modified=lastmod_text if lastmod_text else None,
                    priority=float(priority_text) if priority_text else None,
                    change_frequency=changefreq_text if changefreq_text else None
                )

                urls.append(sitemap_url)

            return urls, child_sitemaps

        except ET.ParseError as e:
            print(f"Error parsing sitemap XML: {e}")
            return [], []

    def _hash_content(self, content: bytes) -> str:
        """
        Generate SHA-256 hash of content for change detection

        Args:
            content: Raw content bytes

        Returns:
            Hex string of hash
        """
        return hashlib.sha256(content).hexdigest()

    def add_domain(self, domain: str, sitemap_url: Optional[str] = None) -> bool:
        """
        Add a domain to the registry and fetch its sitemap

        Args:
            domain: Domain to add (e.g., "example.com")
            sitemap_url: Specific sitemap URL, or None to auto-discover

        Returns:
            True if successful, False otherwise
        """
        domain = self._extract_domain(domain)

        # Try provided sitemap URL or auto-discover
        urls_to_try = [sitemap_url] if sitemap_url else self._generate_sitemap_urls(domain)

        for url in urls_to_try:
            if url is None:
                continue

            print(f"Trying {url}...")
            content = self._fetch_sitemap(url)

            if content:
                return self._process_sitemap(domain, url, content)

        # Failed to find any sitemap
        self._mark_failed(domain, "No valid sitemap found")
        return False

    def _process_sitemap(self, domain: str, sitemap_url: str, content: bytes) -> bool:
        """
        Process fetched sitemap content and store in database

        Args:
            domain: Domain this sitemap belongs to
            sitemap_url: URL of the sitemap
            content: Raw sitemap content

        Returns:
            True if successful
        """
        content_hash = self._hash_content(content)

        # Parse the sitemap
        urls, child_sitemaps = self._parse_sitemap(content, sitemap_url)

        # If this is a sitemap index, fetch all child sitemaps
        if child_sitemaps:
            print(f"Found sitemap index with {len(child_sitemaps)} child sitemaps")
            all_urls = []

            for child_url in child_sitemaps:
                print(f"  Fetching child sitemap: {child_url}")
                child_content = self._fetch_sitemap(child_url)

                if child_content:
                    child_urls, _ = self._parse_sitemap(child_content, child_url)
                    all_urls.extend(child_urls)

            urls = all_urls

        if not urls:
            self._mark_failed(domain, "No URLs found in sitemap")
            return False

        # Store in database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Insert or update sitemap metadata
            cursor.execute("""
                INSERT OR REPLACE INTO sitemaps
                (domain, sitemap_url, content_hash, last_fetched, url_count, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                domain,
                sitemap_url,
                content_hash,
                datetime.now(),
                len(urls),
                'success'
            ))

            # Insert URLs (ignore duplicates)
            for url_obj in urls:
                cursor.execute("""
                    INSERT OR IGNORE INTO sitemap_urls
                    (url, domain, last_modified, priority, change_frequency)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    url_obj.url,
                    url_obj.domain,
                    url_obj.last_modified,
                    url_obj.priority,
                    url_obj.change_frequency
                ))

            conn.commit()
            print(f"✓ Stored {len(urls)} URLs from {domain}")
            return True

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def _mark_failed(self, domain: str, error: str):
        """Mark a domain as failed to fetch"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO sitemaps
            (domain, sitemap_url, content_hash, last_fetched, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (domain, '', '', datetime.now(), 'failed', error))

        conn.commit()
        conn.close()

    def has_sitemap(self, domain: str) -> bool:
        """
        Check if domain has a sitemap in registry

        Args:
            domain: Domain to check

        Returns:
            True if sitemap exists and is successful
        """
        domain = self._extract_domain(domain)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT status FROM sitemaps WHERE domain = ?
        """, (domain,))

        result = cursor.fetchone()
        conn.close()

        return result is not None and result[0] == 'success'

    def is_stale(self, domain: str) -> bool:
        """
        Check if sitemap is stale and needs refreshing

        Args:
            domain: Domain to check

        Returns:
            True if sitemap is older than staleness_days
        """
        domain = self._extract_domain(domain)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT last_fetched FROM sitemaps WHERE domain = ?
        """, (domain,))

        result = cursor.fetchone()
        conn.close()

        if not result:
            return True

        last_fetched = datetime.fromisoformat(result[0])
        age = datetime.now() - last_fetched

        return age > timedelta(days=self.staleness_days)

    def get_urls(
        self,
        domain: str,
        limit: Optional[int] = None,
        offset: int = 0,
        unscraped_only: bool = False
    ) -> List[str]:
        """
        Get URLs from a domain's sitemap

        Args:
            domain: Domain to get URLs for
            limit: Maximum number of URLs to return (None = all)
            offset: Number of URLs to skip (for pagination)
            unscraped_only: Only return URLs that haven't been scraped

        Returns:
            List of URL strings
        """
        domain = self._extract_domain(domain)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT url FROM sitemap_urls WHERE domain = ?"
        params = [domain]

        if unscraped_only:
            query += " AND scraped = 0"

        # Order by priority (high to low), then by URL
        query += " ORDER BY priority DESC, url ASC"

        if limit:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()

        return [row[0] for row in results]

    def mark_scraped(self, url: str):
        """
        Mark a URL as scraped

        Args:
            url: URL that was scraped
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE sitemap_urls
            SET scraped = 1, scraped_at = ?
            WHERE url = ?
        """, (datetime.now(), url))

        conn.commit()
        conn.close()

    def get_sitemap_info(self, domain: str) -> Optional[SitemapInfo]:
        """
        Get metadata about a sitemap

        Args:
            domain: Domain to get info for

        Returns:
            SitemapInfo object or None if not found
        """
        domain = self._extract_domain(domain)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT domain, sitemap_url, content_hash, last_fetched,
                   url_count, status, error_message
            FROM sitemaps WHERE domain = ?
        """, (domain,))

        result = cursor.fetchone()
        conn.close()

        if not result:
            return None

        return SitemapInfo(
            domain=result[0],
            sitemap_url=result[1],
            content_hash=result[2],
            last_fetched=datetime.fromisoformat(result[3]) if result[3] else None,
            url_count=result[4],
            status=result[5],
            error_message=result[6]
        )

    def list_domains(self) -> List[str]:
        """
        List all domains in the registry

        Returns:
            List of domain strings
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT domain FROM sitemaps ORDER BY domain")
        results = cursor.fetchall()
        conn.close()

        return [row[0] for row in results]

    def get_stats(self) -> Dict:
        """
        Get registry statistics

        Returns:
            Dictionary with stats about the registry
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Count sitemaps
        cursor.execute("SELECT COUNT(*) FROM sitemaps WHERE status = 'success'")
        sitemap_count = cursor.fetchone()[0]

        # Count total URLs
        cursor.execute("SELECT COUNT(*) FROM sitemap_urls")
        url_count = cursor.fetchone()[0]

        # Count scraped URLs
        cursor.execute("SELECT COUNT(*) FROM sitemap_urls WHERE scraped = 1")
        scraped_count = cursor.fetchone()[0]

        conn.close()

        return {
            'total_sitemaps': sitemap_count,
            'total_urls': url_count,
            'scraped_urls': scraped_count,
            'unscraped_urls': url_count - scraped_count,
            'database_path': str(self.db_path)
        }

    def refresh_domain(self, domain: str) -> bool:
        """
        Force refresh a domain's sitemap

        Args:
            domain: Domain to refresh

        Returns:
            True if successful
        """
        domain = self._extract_domain(domain)

        # Get existing sitemap URL
        info = self.get_sitemap_info(domain)
        sitemap_url = info.sitemap_url if info else None

        # Re-fetch
        return self.add_domain(domain, sitemap_url)


# Convenience functions for quick access
def quick_add_domain(domain: str) -> bool:
    """
    Quick function to add a domain to registry

    Args:
        domain: Domain to add

    Returns:
        True if successful
    """
    registry = SitemapRegistry()
    return registry.add_domain(domain)


def quick_get_urls(domain: str, limit: int = 100) -> List[str]:
    """
    Quick function to get URLs from a domain

    Args:
        domain: Domain to get URLs from
        limit: Max URLs to return

    Returns:
        List of URLs
    """
    registry = SitemapRegistry()
    return registry.get_urls(domain, limit=limit)


if __name__ == '__main__':
    # Example usage and testing
    print("=== Sitemap Registry Test ===\n")

    registry = SitemapRegistry()

    # Test with a real site that has a sitemap (TechCrunch)
    test_domain = "techcrunch.com"

    # Add a domain
    print(f"Adding {test_domain}...")
    success = registry.add_domain(test_domain)

    if success:
        print("\n[SUCCESS]")

        # Get info
        info = registry.get_sitemap_info(test_domain)
        print(f"\nSitemap Info:")
        print(f"  URL: {info.sitemap_url}")
        print(f"  URLs: {info.url_count}")
        print(f"  Last fetched: {info.last_fetched}")

        # Get some URLs
        urls = registry.get_urls(test_domain, limit=5)
        print(f"\nFirst 5 URLs:")
        for url in urls:
            print(f"  - {url}")

        # Stats
        stats = registry.get_stats()
        print(f"\nRegistry Stats:")
        print(f"  Total sitemaps: {stats['total_sitemaps']}")
        print(f"  Total URLs: {stats['total_urls']}")

        # Test staleness check
        print(f"\nIs stale? {registry.is_stale(test_domain)}")

    else:
        print("\n[FAILED] Failed to add domain")
