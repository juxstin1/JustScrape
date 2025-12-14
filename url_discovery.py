"""
URL Discovery System
Simple one-level link discovery from source URLs with basic filtering.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from web_scraper import WebScraper
from bs4 import BeautifulSoup


# Junk URL patterns to filter out (ads, trackers, social widgets)
JUNK_PATTERNS = [
    'doubleclick.net',
    'googlesyndication.com',
    'googleadservices.com',
    'facebook.com/plugins',
    'facebook.com/sharer',
    'twitter.com/widgets',
    'twitter.com/intent',
    'linkedin.com/share',
    'pinterest.com/pin',
    '/ads/',
    '/ad/',
    '/banner/',
    '/tracker/',
    '/track/',
    'analytics',
    'pixel',
    '/feed/',
    '/rss/',
    'mailto:',
    'javascript:',
    'tel:',
]


class URLDiscovery:
    """Manages source URLs and discovers links from them"""

    def __init__(self):
        """Initialize URL discovery with JSON storage"""
        # Storage directory
        self.storage_dir = Path.home() / '.scraper'
        self.storage_dir.mkdir(exist_ok=True)

        # Storage files
        self.sources_file = self.storage_dir / 'sources.json'
        self.discovered_file = self.storage_dir / 'discovered.json'

        # Initialize files if they don't exist
        if not self.sources_file.exists():
            self._save_sources([])

        if not self.discovered_file.exists():
            self._save_discovered({})

    def _load_sources(self) -> List[str]:
        """Load source URLs from JSON file"""
        try:
            with open(self.sources_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading sources: {e}")
            return []

    def _save_sources(self, sources: List[str]):
        """Save source URLs to JSON file"""
        try:
            with open(self.sources_file, 'w', encoding='utf-8') as f:
                json.dump(sources, f, indent=2)
        except Exception as e:
            print(f"Error saving sources: {e}")

    def _load_discovered(self) -> Dict[str, dict]:
        """Load discovered URLs from JSON file"""
        try:
            with open(self.discovered_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading discovered URLs: {e}")
            return {}

    def _save_discovered(self, discovered: Dict[str, dict]):
        """Save discovered URLs to JSON file"""
        try:
            with open(self.discovered_file, 'w', encoding='utf-8') as f:
                json.dump(discovered, f, indent=2)
        except Exception as e:
            print(f"Error saving discovered URLs: {e}")

    def _filter_junk(self, urls: List[str]) -> tuple[List[str], int]:
        """
        Filter out junk URLs (ads, trackers, social widgets)
        Returns: (filtered_urls, junk_count)
        """
        filtered = []
        junk_count = 0

        for url in urls:
            is_junk = False
            url_lower = url.lower()

            # Check against junk patterns
            for pattern in JUNK_PATTERNS:
                if pattern in url_lower:
                    is_junk = True
                    junk_count += 1
                    break

            if not is_junk:
                filtered.append(url)

        return filtered, junk_count

    def add_source(self, url: str) -> bool:
        """
        Add a source URL to discover from
        Returns: True if added, False if already exists
        """
        # Normalize URL
        url = url.strip()
        if not url.startswith('http'):
            url = 'https://' + url

        sources = self._load_sources()

        # Check if already exists
        if url in sources:
            return False

        # Add and save
        sources.append(url)
        self._save_sources(sources)
        return True

    def remove_source(self, url: str) -> bool:
        """
        Remove a source URL
        Returns: True if removed, False if not found
        """
        sources = self._load_sources()

        if url in sources:
            sources.remove(url)
            self._save_sources(sources)
            return True

        return False

    def get_sources(self) -> List[str]:
        """Get list of all source URLs"""
        return self._load_sources()

    def discover(self, source_url: Optional[str] = None, verbose: bool = True) -> tuple[int, int]:
        """
        Discover URLs from a source (or all sources if None)
        Returns: (discovered_count, junk_filtered_count)
        """
        sources = self._load_sources()

        if not sources:
            if verbose:
                print("No sources configured. Add a source URL first.")
            return 0, 0

        # Determine which sources to process
        if source_url:
            if source_url not in sources:
                if verbose:
                    print(f"Source not found: {source_url}")
                return 0, 0
            sources_to_process = [source_url]
        else:
            sources_to_process = sources

        # Load existing discovered URLs
        discovered = self._load_discovered()

        # Initialize web scraper
        scraper = WebScraper()

        total_discovered = 0
        total_junk = 0

        for source in sources_to_process:
            if verbose:
                print(f"\nDiscovering from: {source}")

            try:
                # Fetch the source page
                html, status_code = scraper.fetch(source)
                if not html or status_code != 200:
                    if verbose:
                        print(f"  Could not fetch page (status: {status_code})")
                    continue

                # Parse HTML
                soup = BeautifulSoup(html, 'html.parser')
                if not soup:
                    if verbose:
                        print(f"  Could not parse HTML")
                    continue

                # Extract links
                links = scraper.extract_links(soup, source)
                if verbose:
                    print(f"  Found {len(links)} links")

                # Filter junk URLs
                filtered_links, junk_count = self._filter_junk(links)
                total_junk += junk_count

                if verbose and junk_count > 0:
                    print(f"  Filtered {junk_count} junk URLs")

                # Try to get page title
                title = "Unknown"
                try:
                    title_tag = soup.find('title')
                    if title_tag and title_tag.string:
                        title = title_tag.string.strip()
                except:
                    pass

                # Store discovered URLs with metadata
                timestamp = datetime.now().isoformat()
                new_urls = 0

                for url in filtered_links:
                    if url not in discovered:
                        discovered[url] = {
                            'discovered_from': source,
                            'timestamp': timestamp,
                            'source_title': title
                        }
                        new_urls += 1

                total_discovered += new_urls

                if verbose:
                    print(f"  Added {new_urls} new URLs")

            except Exception as e:
                if verbose:
                    print(f"  Error: {e}")
                continue

        # Save updated discovered URLs
        self._save_discovered(discovered)

        return total_discovered, total_junk

    def search(self, query: str) -> List[str]:
        """
        Search discovered URLs by string matching
        Returns: List of matching URLs
        """
        discovered = self._load_discovered()
        query_lower = query.lower()

        matches = []
        for url in discovered.keys():
            if query_lower in url.lower():
                matches.append(url)

        return matches

    def get_stats(self) -> dict:
        """
        Get discovery statistics
        Returns: Dict with stats
        """
        sources = self._load_sources()
        discovered = self._load_discovered()

        # Find most recent discovery timestamp
        last_discovery = None
        if discovered:
            timestamps = [info['timestamp'] for info in discovered.values()]
            if timestamps:
                last_discovery = max(timestamps)

        return {
            'total_sources': len(sources),
            'total_discovered': len(discovered),
            'last_discovery': last_discovery
        }

    def clear_discovered(self) -> int:
        """
        Clear all discovered URLs
        Returns: Number of URLs cleared
        """
        discovered = self._load_discovered()
        count = len(discovered)
        self._save_discovered({})
        return count

    def get_url_info(self, url: str) -> Optional[dict]:
        """
        Get metadata for a specific discovered URL
        Returns: Metadata dict or None if not found
        """
        discovered = self._load_discovered()
        return discovered.get(url)
