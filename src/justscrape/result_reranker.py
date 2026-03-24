"""
Result Reranker — query-type-aware authority scoring and freshness weighting.

Implements RANK-01 (authority scoring with per-query-type tier maps) and
RANK-02 (freshness decay for news/current-event queries only).

Re-orders search results by source quality so the best sources are scraped
first, reducing wasted scraping on low-value pages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse
from datetime import datetime

from dateutil import parser as dateutil_parser


# ---------------------------------------------------------------------------
# Authority tier maps (per D-07 / D-08)
# Keys are bare domains (no www, no scheme).
# Values are authority scores 0.0–1.0.
# ---------------------------------------------------------------------------

AUTHORITY_TIERS: dict[str, dict[str, float]] = {
    "code": {
        "docs.python.org": 1.0,
        "docs.rust-lang.org": 1.0,
        "developer.mozilla.org": 1.0,
        "docs.microsoft.com": 1.0,
        "stackoverflow.com": 1.0,
        "github.com": 1.0,
        "cppreference.com": 1.0,
        "docs.oracle.com": 1.0,
        "go.dev": 1.0,
        "realpython.com": 0.8,
        "css-tricks.com": 0.8,
        "digitalocean.com": 0.8,
        "geeksforgeeks.org": 0.8,
        "tutorialspoint.com": 0.5,
        "w3schools.com": 0.5,
        "medium.com": 0.2,
        "dev.to": 0.2,
    },
    "research": {
        "arxiv.org": 1.0,
        "wikipedia.org": 1.0,
        "scholar.google.com": 0.8,
        "nature.com": 1.0,
        "sciencedirect.com": 0.8,
        "stackoverflow.com": 0.5,
        "medium.com": 0.5,
        "github.com": 0.5,
    },
    "news": {
        "reuters.com": 1.0,
        "apnews.com": 1.0,
        "bbc.com": 1.0,
        "bbc.co.uk": 1.0,
        "nytimes.com": 0.8,
        "theguardian.com": 0.8,
        "techcrunch.com": 0.8,
        "arstechnica.com": 0.8,
        "theverge.com": 0.8,
        "medium.com": 0.3,
        "dev.to": 0.3,
    },
    "general": {},  # Fallback — all unknown domains get 0.5
}

# Domains that are always blocked (SEO farms, paywalls, login-gated).
# Blocked domains score 0.0 and is_blocked=True per D-10.
BLOCKED_DOMAINS: set[str] = {
    "answers.com",
    "ask.com",
    "ehow.com",
    "brighthub.com",
    "quora.com",     # Often paywalled / login-gated
    "pinterest.com", # Image-only, no useful text
    "scribd.com",    # Paywall
}

# Query intents that receive freshness scoring (D-09).
_FRESHNESS_INTENTS = {"news", "current", "current-events"}


@dataclass
class RankedResult:
    """A search result enriched with authority and freshness scores."""

    url: str
    title: str
    snippet: str
    original_position: int      # 1-based, preserved from search engine (D-11)
    authority_score: float      # 0.0–1.0 from tier map (D-07)
    freshness_score: Optional[float]  # 0.0–1.0 for news; None otherwise (D-09)
    is_blocked: bool            # True if domain is on BLOCKED_DOMAINS (D-10)
    detected_date: Optional[str] = None  # ISO date string if parsed from snippet


class ResultReranker:
    """Re-ranks search results by source quality for a given query intent."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_authority_score(self, url: str, query_type: str) -> float:
        """Return authority score (0.0–1.0) for *url* given *query_type*.

        Rules:
        - Blocked domains always return 0.0 (D-10).
        - Known domains return their tier score from the matching map (D-07).
        - Unknown domains default to 0.5 — NEVER 0.0 (Pitfall 6).
        - Subdomain lookup: try full netloc first, then base domain
          (last two labels, e.g. docs.python.org → python.org fallback).
        """
        domain = self._extract_domain(url)
        if domain in BLOCKED_DOMAINS:
            return 0.0

        tier_map = AUTHORITY_TIERS.get(query_type, {})

        # Exact match
        if domain in tier_map:
            return tier_map[domain]

        # Base-domain fallback (strip leading subdomain labels until 2 remain)
        base = self._base_domain(domain)
        if base != domain and base in tier_map:
            return tier_map[base]

        # Unknown domain — default to Standard (0.5), never 0.0
        return 0.5

    def get_freshness_score(self, snippet: str, query_type: str) -> Optional[float]:
        """Return freshness score (0.0–1.0) or None.

        Per D-09: freshness scoring ONLY applies to news/current-event queries.
        Code and research intents always receive None.

        For news:
        - Parses a date from *snippet* using dateutil.
        - Applies linear decay: score = max(0.0, 1.0 - days_old / 30).
        - If no date found, returns 0.3 (penalised but not zero).
        """
        if query_type not in _FRESHNESS_INTENTS:
            return None

        parsed_date = self._parse_date_from_snippet(snippet)
        if parsed_date is None:
            return 0.3  # Penalty for undated news content

        now = datetime.now()
        days_old = max(0.0, (now - parsed_date).total_seconds() / 86400.0)
        score = max(0.0, 1.0 - days_old / 30.0)
        return round(score, 4)

    def rerank(self, results: List[dict], query_type: str) -> List[RankedResult]:
        """Re-rank *results* by authority (and freshness for news).

        Args:
            results: List of dicts with keys {url, title, snippet, position}.
            query_type: Intent string ("code", "research", "news", "general").

        Returns:
            List of RankedResult sorted by authority_score descending;
            blocked entries are pushed to the bottom. original_position is
            preserved from the input position value (D-11).
        """
        ranked: List[RankedResult] = []
        for item in results:
            url = item["url"]
            domain = self._extract_domain(url)
            is_blocked = domain in BLOCKED_DOMAINS
            authority = self.get_authority_score(url, query_type)
            snippet_text = item.get("snippet", "")
            freshness = self.get_freshness_score(snippet_text, query_type)

            # Extract date from snippet for metadata (independent of freshness scoring)
            parsed_dt = self._parse_date_from_snippet(snippet_text)
            date_iso = parsed_dt.date().isoformat() if parsed_dt else None

            ranked.append(RankedResult(
                url=url,
                title=item.get("title", ""),
                snippet=snippet_text,
                original_position=item["position"],
                authority_score=authority,
                freshness_score=freshness,
                is_blocked=is_blocked,
                detected_date=date_iso,
            ))

        # Sort: non-blocked first, then by authority descending; blocked at end
        ranked.sort(key=lambda r: (r.is_blocked, -r.authority_score))
        return ranked

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Return bare lowercase domain from URL, stripping leading 'www.'."""
        try:
            netloc = urlparse(url).netloc.lower()
        except Exception:
            return ""
        # Strip port if present
        netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc

    # Known two-label TLDs where base domain needs 3 labels
    _CC_SLDS = frozenset({
        "co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "org.au", "gov.au",
        "co.jp", "or.jp", "co.nz", "org.nz", "co.za", "co.in", "com.br",
        "org.br", "co.kr", "or.kr", "com.cn", "org.cn", "co.il", "org.il",
        "com.mx", "com.ar", "com.sg", "com.hk", "com.tw",
    })

    @classmethod
    def _base_domain(cls, domain: str) -> str:
        """Return the registrable domain, e.g. docs.bbc.co.uk → bbc.co.uk."""
        parts = domain.split(".")
        if len(parts) > 2:
            last_two = ".".join(parts[-2:])
            if last_two in cls._CC_SLDS and len(parts) > 3:
                return ".".join(parts[-3:])
            return last_two
        return domain

    # Explicit date patterns tried before fuzzy parsing
    _DATE_PATTERNS = [
        re.compile(r'\b(\d{4}-\d{1,2}-\d{1,2})\b'),                          # 2026-03-22
        re.compile(r'\b(\d{1,2}/\d{1,2}/\d{4})\b'),                          # 03/22/2026
        re.compile(r'\b(\w+\s+\d{1,2},?\s+\d{4})\b'),                        # March 22, 2026
        re.compile(r'\b(\d{1,2}\s+\w+\s+\d{4})\b'),                          # 22 March 2026
    ]

    @classmethod
    def _parse_date_from_snippet(cls, snippet: str) -> Optional[datetime]:
        """Extract a date from snippet text. Tries explicit patterns first, fuzzy as fallback."""
        now = datetime.now()

        # Try explicit patterns first (avoids "Python 3.12" → March 12)
        for pattern in cls._DATE_PATTERNS:
            match = pattern.search(snippet)
            if match:
                try:
                    dt = dateutil_parser.parse(match.group(1))
                    dt = dt.replace(tzinfo=None)
                    # Reject dates outside reasonable range
                    if dt.year < now.year - 5 or dt > now:
                        continue
                    return dt
                except (ValueError, OverflowError):
                    continue

        # Fuzzy fallback — but sanity-check the result
        try:
            dt = dateutil_parser.parse(snippet, fuzzy=True)
            dt = dt.replace(tzinfo=None)
            if dt.year < now.year - 5 or dt > now:
                return None
            return dt
        except (ValueError, OverflowError):
            return None
