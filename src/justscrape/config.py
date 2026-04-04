"""
Centralized configuration for JustScrape.

All tunable thresholds, timeouts, domain lists, size limits, and cache
settings live here so they can be found and adjusted in one place.
"""

# === Concurrency ===
MAX_CONCURRENT_SCRAPES = 5
ASYNC_GLOBAL_SEMAPHORE_LIMIT = 10
ASYNC_MAX_PER_DOMAIN = 2
ASYNC_MAX_DOMAIN_SEMAPHORES = 500

# === Size Limits ===
MAX_RESPONSE_SIZE = 10 * 1024 * 1024           # 10 MB — static scraper streaming cap
MAX_ADAPTER_RESPONSE_SIZE = 10 * 1024 * 1024   # 10 MB — smart_scraper adapter cap
MAX_HEAD_CHECK_SIZE = 5 * 1024 * 1024           # 5 MB — HEAD pre-check rejection threshold
MAX_SITEMAP_SIZE = 50 * 1024 * 1024             # 50 MB — sitemap XML cap
MAX_CHILD_SITEMAPS = 100                        # sitemap index child limit
MAX_DISCOVERED_URLS = 100000                    # url_discovery storage cap

# === Cache ===
SEARCH_CACHE_TTL = 300          # L1 in-memory cache TTL (seconds)
SEARCH_CACHE_MAX_SIZE = 100     # L1 in-memory cache max entries
PERSISTENT_CACHE_TTL = 86400    # L2 SQLite cache TTL (seconds) — 24 hours
ROBOTS_CACHE_MAX_SIZE = 500     # robots.txt parser cache max entries
ROBOTS_CACHE_TTL = 86400        # robots.txt cache TTL (seconds) — 24 hours

# === Rate Limiting ===
SCRAPER_DOMAIN_LIMITER_MAX_DOMAINS = 1000
RATE_LIMITER_MAX_DOMAINS = 1000

# === Scraper Defaults ===
MIN_CONTENT_LENGTH = 200        # SmartScraper JS-fallback threshold (chars)

# === Snippet Extraction ===
CHUNK_SIZE_THRESHOLD = 800      # chars before splitting heading sections into paragraphs

# === Quality Pipeline ===
DEDUP_SIMILARITY_THRESHOLD = 0.85   # rapidfuzz token_sort_ratio threshold for dedup

# === Domain Lists ===
YOUTUBE_DOMAINS = {"youtube.com", "youtu.be"}

JS_HEAVY_DOMAINS = {
    'twitter.com', 'x.com', 'reddit.com', 'youtube.com',
    'instagram.com', 'facebook.com', 'linkedin.com',
    'medium.com', 'substack.com', 'discord.com',
}

# Domains known to block scrapers — skip in automated research flows
KNOWN_BLOCKED_DOMAINS = {
    'medium.com',
    'twitter.com', 'x.com', 'linkedin.com', 'www.linkedin.com',
    'facebook.com', 'www.facebook.com', 'instagram.com', 'www.instagram.com',
}

# Domains that are searchable but poor retrieval targets without a transcript adapter
UNSUPPORTED_RESEARCH_DOMAINS = {
    'youtube.com',
    'youtu.be',
}

# Domains that are always blocked (SEO farms, paywalls, login-gated) — reranker
RERANKER_BLOCKED_DOMAINS: set[str] = {
    "answers.com",
    "ask.com",
    "ehow.com",
    "brighthub.com",
    "quora.com",
    "pinterest.com",
    "scribd.com",
}

# URL path patterns that are rarely useful content
SKIP_PATH_PATTERNS = [
    '/login', '/signup', '/register', '/terms', '/privacy',
    '/cookie', '/tos', '/legal', '/auth', '/account/',
]

# === SSRF Protection ===
ALLOWED_SCHEMES = {'http', 'https'}

BLOCKED_HOSTNAMES = {
    'metadata.google.internal',
    'metadata.goog',
}

# === URL Discovery ===
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
