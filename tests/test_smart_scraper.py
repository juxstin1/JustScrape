import sys
import types
from unittest.mock import patch

from justscrape.smart_scraper import SmartScraper
from justscrape.web_scraper import ContentType, ScrapedContent


# Mock URL validation so tests work without DNS resolution
_bypass_url_validation = patch(
    "justscrape.smart_scraper._validate_url", lambda url: (True, "ok")
)


def test_is_js_heavy_site_detects_known_domains():
    scraper = SmartScraper()
    assert scraper._is_js_heavy_site("https://www.reddit.com/r/python")
    assert not scraper._is_js_heavy_site("https://example.com/blog")


def test_needs_javascript_detects_signals():
    scraper = SmartScraper(min_content_length=200)

    assert scraper._needs_javascript(
        "<html><body>Please enable JavaScript to continue</body></html>",
        "short",
        "https://example.com",
    )

    long_content = "useful content " * 200
    assert not scraper._needs_javascript(
        "<html><body><article>Real article</article></body></html>",
        long_content,
        "https://example.com",
    )


@_bypass_url_validation
def test_scrape_falls_back_to_javascript_when_static_is_thin(monkeypatch):
    scraper = SmartScraper(min_content_length=200)

    # The scrape() method calls static_scraper.fetch() for raw HTML,
    # then checks _needs_javascript(). Provide thin HTML with a JS signal
    # so the fallback triggers.
    thin_html = "<html><body><noscript>Please enable JavaScript to continue</noscript></body></html>"
    monkeypatch.setattr(
        scraper.static_scraper,
        "fetch",
        lambda url: (thin_html, 200),
    )

    class FakeJavaScriptScraper:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return None

        def scrape(self, url, content_types):
            return ScrapedContent(
                url=url,
                title="JS Title",
                content="rendered content from javascript",
                status_code=200,
            )

    # Mock the entire js_scraper module in sys.modules (playwright isn't installed)
    fake_module = types.ModuleType("justscrape.js_scraper")
    fake_module.JavaScriptScraper = FakeJavaScriptScraper
    monkeypatch.setitem(sys.modules, "justscrape.js_scraper", fake_module)

    result = scraper.scrape("https://example.com", [ContentType.CLEAN_TEXT, ContentType.METADATA])

    assert result.title == "JS Title"
    assert result.content == "rendered content from javascript"


@_bypass_url_validation
def test_reddit_json_adapter_scrapes_without_browser(monkeypatch):
    scraper = SmartScraper()

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "kind": "Listing",
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "subreddit": "Python",
                                "title": "Useful Python discussion",
                                "selftext": "This is body text from reddit.",
                                "permalink": "/r/Python/comments/abc/useful_python_discussion/",
                                "url": "https://www.reddit.com/r/Python/comments/abc/useful_python_discussion/",
                                "score": 123,
                                "num_comments": 10,
                            },
                        }
                    ]
                },
            }

    monkeypatch.setattr("justscrape.smart_scraper._safe_get", lambda *args, **kwargs: FakeResponse())

    result = scraper.scrape(
        "https://www.reddit.com/r/Python/",
        [ContentType.CLEAN_TEXT, ContentType.METADATA, ContentType.LINKS],
    )

    assert result.scrape_method == "reddit_json"
    assert "Useful Python discussion" in (result.content or "")
    assert result.title == "r/Python - Reddit"
    assert result.metadata["source"] == "reddit_json"
    assert result.links and any("reddit.com" in link for link in result.links)


@_bypass_url_validation
def test_stackexchange_api_adapter_scrapes_without_browser(monkeypatch):
    scraper = SmartScraper()

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, headers=None, timeout=0):
        if "/answers" in url:
            return FakeResponse(
                200,
                {
                    "items": [
                        {
                            "body": "<p>Use <code>subprocess.run</code> with a list of args.</p>",
                            "score": 42,
                            "is_accepted": True,
                            "share_link": "https://stackoverflow.com/a/123456",
                        }
                    ]
                },
            )
        return FakeResponse(
            200,
            {
                "items": [
                    {
                        "title": "How to run ffmpeg from Python?",
                        "body": "<p>I need to call ffmpeg from Python.</p>",
                        "score": 15,
                        "answer_count": 2,
                        "is_answered": True,
                        "tags": ["python", "ffmpeg"],
                        "link": "https://stackoverflow.com/questions/1186880/how-to-run-ffmpeg-from-python",
                    }
                ]
            },
        )

    monkeypatch.setattr("justscrape.smart_scraper._safe_get", fake_get)

    result = scraper.scrape(
        "https://stackoverflow.com/questions/1186880/how-to-run-ffmpeg-from-python",
        [ContentType.CLEAN_TEXT, ContentType.METADATA, ContentType.LINKS],
    )

    assert result.scrape_method == "stackexchange_api"
    assert result.title == "How to run ffmpeg from Python?"
    assert "Question: How to run ffmpeg from Python?" in (result.content or "")
    assert "Top answers:" in (result.content or "")
    assert result.metadata["source"] == "stackexchange_api"
    assert result.metadata["site"] == "stackoverflow"
    assert result.links and any("stackoverflow.com" in link for link in result.links)


@_bypass_url_validation
def test_stackexchange_stackprinter_fallback_when_api_fails(monkeypatch):
    scraper = SmartScraper()

    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    def fake_get(url, headers=None, timeout=0):
        if "api.stackexchange.com" in url:
            return None  # _safe_get returns None for failures
        if "/stackprinter" in url:
            html = """
            <html>
              <head><title>How do I exit Vim? - Stack Overflow</title></head>
              <body>
                <h1>Question</h1>
                <p>I am stuck in vim and need to quit.</p>
                <h2>Answer</h2>
                <p>Press Esc then type :q! and Enter.</p>
                <a href="https://stackoverflow.com/questions/11828270/how-do-i-exit-the-vim-editor">Link</a>
              </body>
            </html>
            """
            return FakeResponse(200, text=html)
        return None  # _safe_get returns None for 404

    monkeypatch.setattr("justscrape.smart_scraper._safe_get", fake_get)

    result = scraper.scrape(
        "https://stackoverflow.com/questions/11828270/how-do-i-exit-the-vim-editor",
        [ContentType.CLEAN_TEXT, ContentType.METADATA, ContentType.LINKS],
    )

    assert result.scrape_method == "stackexchange_stackprinter"
    assert "exit vim" in (result.title or "").lower()
    assert "Press Esc then type :q!" in (result.content or "")
    assert result.metadata["source"] == "stackexchange_stackprinter"
    assert result.links and any("stackoverflow.com/questions/11828270" in link for link in result.links)


@_bypass_url_validation
def test_devto_api_adapter_scrapes_without_browser(monkeypatch):
    scraper = SmartScraper()

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "title": "FFmpeg tips for Python developers",
                "description": "Quick FFmpeg integration ideas.",
                "body_markdown": "Use `ffmpeg` via subprocess.\n\nSee https://ffmpeg.org/documentation.html",
                "tags": ["python", "ffmpeg"],
                "published_at": "2026-02-15T00:00:00Z",
                "reading_time_minutes": 3,
                "canonical_url": "https://example.com/ffmpeg-tips",
                "url": "https://dev.to/alice/ffmpeg-tips-1234",
                "user": {"name": "Alice", "username": "alice"},
            }

    monkeypatch.setattr("justscrape.smart_scraper._safe_get", lambda *args, **kwargs: FakeResponse())

    result = scraper.scrape(
        "https://dev.to/alice/ffmpeg-tips-1234",
        [ContentType.CLEAN_TEXT, ContentType.METADATA, ContentType.LINKS],
    )

    assert result.scrape_method == "devto_api"
    assert result.title == "FFmpeg tips for Python developers"
    assert "Use `ffmpeg` via subprocess." in (result.content or "")
    assert result.metadata["source"] == "devto_api"
    assert result.metadata["author"] == "Alice"
    assert result.links and any("ffmpeg.org/documentation.html" in link for link in result.links)


@_bypass_url_validation
def test_github_discussions_html_adapter_scrapes_without_browser(monkeypatch):
    scraper = SmartScraper()

    class FakeResponse:
        status_code = 200
        text = """
        <html>
          <head><title>How should we structure plugin APIs? · Discussion #42 · org/repo</title></head>
          <body>
            <h1>How should we structure plugin APIs?</h1>
            <div class="js-comment-body markdown-body">
              <p>We are planning a plugin API and need input on versioning.</p>
            </div>
            <div class="js-comment-body markdown-body">
              <p>Consider semantic versioning and capability negotiation.</p>
            </div>
            <a href="/org/repo/discussions/42">Discussion link</a>
          </body>
        </html>
        """

    monkeypatch.setattr("justscrape.smart_scraper._safe_get", lambda *args, **kwargs: FakeResponse())

    result = scraper.scrape(
        "https://github.com/org/repo/discussions/42",
        [ContentType.CLEAN_TEXT, ContentType.METADATA, ContentType.LINKS],
    )

    assert result.scrape_method == "github_discussions_html"
    assert result.title == "How should we structure plugin APIs?"
    assert "Topic:" in (result.content or "")
    assert "Reply 1:" in (result.content or "")
    assert result.metadata["source"] == "github_discussions_html"
    assert result.metadata["owner"] == "org"
    assert result.links and any("/org/repo/discussions/42" in link for link in result.links)
