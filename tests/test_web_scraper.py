import justscrape.web_scraper as web_scraper
from justscrape.web_scraper import WebScraper, head_pre_check


def test_head_pre_check_blocks_non_html_content():
    class FakeResponse:
        status_code = 200
        url = "https://example.com/file.pdf"
        headers = {
            "content-type": "application/pdf",
            "content-length": "1024",
        }

    class FakeSession:
        def head(self, *args, **kwargs):
            return FakeResponse()

    should_fetch, info = head_pre_check("https://example.com/file.pdf", session=FakeSession())

    assert should_fetch is False
    assert info["reason"].startswith("content_type:")


def test_fetch_respects_robots_disallow(monkeypatch):
    scraper = WebScraper(use_head_check=False, respect_robots=True)
    monkeypatch.setattr(web_scraper.RobotsCache, "can_fetch", lambda url: False)
    monkeypatch.setattr("justscrape.url_validator.validate_url", lambda url: (True, None))

    html, status = scraper.fetch("https://example.com/private")

    assert html is None
    assert status == 403


def test_fetch_does_not_get_when_head_check_fails(monkeypatch):
    scraper = WebScraper(use_head_check=True, respect_robots=False)
    monkeypatch.setattr(
        web_scraper,
        "head_pre_check",
        lambda url, session, timeout: (False, {"status_code": 429}),
    )
    monkeypatch.setattr(scraper, "_rate_limit_wait", lambda url=None: None)
    monkeypatch.setattr("justscrape.url_validator.validate_url", lambda url: (True, None))

    called = {"get": 0}

    def fake_get(*args, **kwargs):
        called["get"] += 1
        raise AssertionError("GET should not be called when HEAD pre-check fails")

    monkeypatch.setattr(scraper.session, "get", fake_get)

    html, status = scraper.fetch("https://example.com")

    assert html is None
    assert status == 429
    assert called["get"] == 0


def test_extract_clean_text_removes_bloat_and_dedupes_lines():
    scraper = WebScraper()
    html = """
    <html>
      <head><title>Demo</title><script>console.log("x")</script></head>
      <body>
        <nav>Top Nav</nav>
        <main>
          <h1>Important Title</h1>
          <p>Same line</p>
          <p>Same line</p>
          <div class="promo">Buy now</div>
          <p>Important body text.</p>
        </main>
      </body>
    </html>
    """

    text = scraper.extract_clean_text(html)

    assert "Top Nav" not in text
    assert "Buy now" not in text
    assert text.count("Same line") == 1
    assert "Important body text." in text
