import worker
from web_search import (
    SearchResponse,
    SearchResult,
    build_query,
    merge_search_results,
    relevance_score,
    should_scrape,
)


def test_build_query_and_should_scrape_filters():
    query = build_query(
        "python scraping",
        site="docs.python.org",
        filetype="pdf",
        exclude_sites=["reddit.com", "medium.com"],
    )
    assert "site:docs.python.org" in query
    assert "filetype:pdf" in query
    assert "-site:reddit.com" in query

    ok, reason = should_scrape("https://medium.com/some-post")
    assert ok is False
    assert reason.startswith("blocked_domain:")

    ok, reason = should_scrape("https://example.com/login")
    assert ok is False
    assert reason.startswith("skip_path:")

    ok, reason = should_scrape("https://example.com/article")
    assert ok is True
    assert reason == "ok"

    ok, reason = should_scrape("https://www.reddit.com/r/Python/")
    assert ok is True
    assert reason == "adapter:reddit_json"

    ok, reason = should_scrape("https://dev.to/alice/ffmpeg-tips-1234")
    assert ok is True
    assert reason == "adapter:devto_api"

    ok, reason = should_scrape("https://github.com/org/repo/discussions/42")
    assert ok is True
    assert reason == "adapter:github_discussions_html"

    ok, reason = should_scrape("https://stackoverflow.com/questions/1186880/how-to-run-ffmpeg-from-python")
    assert ok is True
    assert reason == "adapter:stackexchange_api"


def test_merge_search_results_dedupes_and_keeps_longest_snippet():
    resp1 = SearchResponse(
        query="python scraping",
        results=[
            SearchResult(
                position=1,
                title="A",
                url="https://example.com/page/?utm_source=x",
                snippet="short snippet",
                source="duckduckgo",
            )
        ],
        total_results=1,
        search_time_ms=5,
        source="duckduckgo",
        success=True,
    )
    resp2 = SearchResponse(
        query="python scraping",
        results=[
            SearchResult(
                position=1,
                title="A alt",
                url="https://example.com/page",
                snippet="a much longer and better snippet",
                source="searxng",
            )
        ],
        total_results=1,
        search_time_ms=6,
        source="searxng",
        success=True,
    )

    merged = merge_search_results([resp1, resp2])

    assert merged.success is True
    assert len(merged.results) == 1
    assert merged.results[0].snippet == "a much longer and better snippet"
    assert merged.results[0].position == 1


def test_relevance_score_rewards_term_and_title_matches():
    high = relevance_score(
        "python scraping",
        ("python scraping tutorial " * 200),
        title="Python Scraping Guide",
    )
    low = relevance_score(
        "python scraping",
        ("unrelated text " * 200),
        title="Completely Different",
    )
    assert high > low


def test_classify_content_handles_blocked_and_encoding_cases():
    blocked = worker.classify_content(
        content="Please enable javascript and complete captcha.",
        title="Just a moment...",
        had_html=True,
        encoding_error=False,
        method="static",
    )
    assert blocked["status"] == "blocked"

    about_captcha = worker.classify_content(
        content=("This long article discusses captcha systems in detail.\n\n" * 400),
        title="Captcha Research Article",
        had_html=True,
        encoding_error=False,
        method="static",
    )
    assert about_captcha["status"] == "usable"

    encoding_fail = worker.classify_content(
        content="whatever",
        title="irrelevant",
        had_html=False,
        encoding_error=True,
        method="static",
    )
    assert encoding_fail["status"] == "encoding-failure"


def test_research_with_sources_filters_and_classifies(monkeypatch):
    def fake_search_full(query, num_results):
        return {
            "success": True,
            "search_time_ms": 7,
            "results": [
                {"position": 1, "title": "Blocked", "url": "https://medium.com/post", "snippet": "x"},
                {"position": 2, "title": "High quality", "url": "https://example.com/a", "snippet": "a"},
                {"position": 3, "title": "Thin page", "url": "https://example.org/b", "snippet": "b"},
                {"position": 4, "title": "Login page", "url": "https://sample.com/login", "snippet": "c"},
            ],
        }

    def fake_retrieve_source(url, allow_javascript=True):
        if "example.com/a" in url:
            content = "python scraping " * 500
            return {
                "url": url,
                "title": "High quality",
                "content": content,
                "signals": {"content_length": len(content), "method": "static", "had_html": True, "encoding_error": False},
                "classification": {"status": "usable", "confidence": "high", "detected_patterns": []},
            }
        return {
            "url": url,
            "title": "Thin page",
            "content": "tiny",
            "signals": {"content_length": 4, "method": "static", "had_html": True, "encoding_error": False},
            "classification": {"status": "thin", "confidence": "high", "detected_patterns": ["content_length:4"]},
        }

    monkeypatch.setattr(worker, "search_full", fake_search_full)
    monkeypatch.setattr(worker, "retrieve_source", fake_retrieve_source)
    monkeypatch.setattr(
        worker,
        "relevance_score",
        lambda query, content, title="": 0.95 if "High" in title else 0.10,
    )

    result = worker.research_with_sources("python scraping", limit=2, max_content_length=200)

    assert len(result["skipped"]) == 2
    assert len(result["sources"]) == 1
    assert len(result["failures"]) == 1
    assert result["sources"][0]["title"] == "High quality"
    assert result["metrics"]["usable_count"] == 1
    assert result["metrics"]["thin_count"] == 1
    assert result["metrics"]["skipped_count"] == 2
    assert "[Truncated -" in result["sources"][0]["content"]


def test_retrieve_source_preserves_stackexchange_adapter_method(monkeypatch):
    class FakeScraper:
        @staticmethod
        def scrape_to_dict(url, force_method=None):
            return {
                "url": url,
                "title": "Stack question",
                "content": "Useful content " * 100,
                "scrape_method": "stackexchange_api",
                "status_code": 200,
            }

    monkeypatch.setattr(worker, "get_smart_scraper", lambda: FakeScraper())

    result = worker.retrieve_source(
        "https://stackoverflow.com/questions/1186880/how-to-run-ffmpeg-from-python",
        allow_javascript=False,
    )

    assert result["signals"]["method"] == "stackexchange_api"
    assert result["classification"]["status"] == "usable"


def test_retrieve_source_preserves_stackprinter_adapter_method(monkeypatch):
    class FakeScraper:
        @staticmethod
        def scrape_to_dict(url, force_method=None):
            return {
                "url": url,
                "title": "StackPrinter fallback question",
                "content": "Fallback content " * 80,
                "scrape_method": "stackexchange_stackprinter",
                "status_code": 200,
            }

    monkeypatch.setattr(worker, "get_smart_scraper", lambda: FakeScraper())

    result = worker.retrieve_source(
        "https://stackoverflow.com/questions/11828270/how-do-i-exit-the-vim-editor",
        allow_javascript=False,
    )

    assert result["signals"]["method"] == "stackexchange_stackprinter"
    assert result["classification"]["status"] == "usable"


def test_retrieve_source_preserves_devto_adapter_method(monkeypatch):
    class FakeScraper:
        @staticmethod
        def scrape_to_dict(url, force_method=None):
            return {
                "url": url,
                "title": "dev.to article",
                "content": "Useful dev.to content " * 80,
                "scrape_method": "devto_api",
                "status_code": 200,
            }

    monkeypatch.setattr(worker, "get_smart_scraper", lambda: FakeScraper())

    result = worker.retrieve_source("https://dev.to/alice/ffmpeg-tips-1234", allow_javascript=False)

    assert result["signals"]["method"] == "devto_api"
    assert result["classification"]["status"] == "usable"


def test_retrieve_source_preserves_github_discussions_adapter_method(monkeypatch):
    class FakeScraper:
        @staticmethod
        def scrape_to_dict(url, force_method=None):
            return {
                "url": url,
                "title": "GitHub discussion",
                "content": "Discussion content " * 80,
                "scrape_method": "github_discussions_html",
                "status_code": 200,
            }

    monkeypatch.setattr(worker, "get_smart_scraper", lambda: FakeScraper())

    result = worker.retrieve_source("https://github.com/org/repo/discussions/42", allow_javascript=False)

    assert result["signals"]["method"] == "github_discussions_html"
    assert result["classification"]["status"] == "usable"
