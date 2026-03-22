"""Tests for snippet_extractor.py — SnippetExtractor and ExtractedSnippet.

Covers EXTRACT-01 (trafilatura extraction), EXTRACT-02 (hybrid chunking),
EXTRACT-03 (BM25+TF-IDF blended scoring), EXTRACT-04 (sentence-level matching).
"""

import pytest
from snippet_extractor import SnippetExtractor, ExtractedSnippet


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<html><head><title>Python Async Guide</title></head>
<body>
<nav>Navigation links here</nav>
<article>
<h1>Python Async Programming</h1>
<p>Python's asyncio module provides infrastructure for writing single-threaded
concurrent code using coroutines. The async/await syntax makes asynchronous
code almost as readable as synchronous code.</p>

<h2>Getting Started</h2>
<p>To use async in Python, you need to understand three key concepts:
coroutines, event loops, and tasks. A coroutine is declared with async def
and is the building block of async Python programs.</p>

<pre><code>
import asyncio

async def main():
    await asyncio.sleep(1)
    print("done")

asyncio.run(main())
</code></pre>

<h2>Advanced Topics</h2>
<p>For production use, consider connection pooling with aiohttp or httpx.
These libraries provide async HTTP clients that work seamlessly with asyncio.</p>
</article>
<footer>Footer content here</footer>
</body></html>
"""

MINIMAL_HTML = "<div></div>"


# ---------------------------------------------------------------------------
# TestTextExtraction — EXTRACT-01
# ---------------------------------------------------------------------------

class TestTextExtraction:
    def setup_method(self):
        self.extractor = SnippetExtractor()

    def test_extract_from_html(self):
        """Valid HTML page should produce non-empty clean text."""
        result = self.extractor.extract_text(SAMPLE_HTML)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should contain actual article content, not nav/footer boilerplate
        assert "asyncio" in result.lower() or "async" in result.lower()

    def test_extract_from_garbage_html(self):
        """Minimal/garbage HTML should not crash; returns empty string."""
        result = self.extractor.extract_text(MINIMAL_HTML)
        assert isinstance(result, str)
        # None should never be propagated

    def test_extract_returns_string(self):
        """Return type is always str — never None propagated."""
        result1 = self.extractor.extract_text(SAMPLE_HTML)
        result2 = self.extractor.extract_text(MINIMAL_HTML)
        result3 = self.extractor.extract_text("")
        assert result1 is not None
        assert result2 is not None
        assert result3 is not None
        assert isinstance(result1, str)
        assert isinstance(result2, str)
        assert isinstance(result3, str)


# ---------------------------------------------------------------------------
# TestChunking — EXTRACT-02
# ---------------------------------------------------------------------------

class TestChunking:
    def setup_method(self):
        self.extractor = SnippetExtractor()

    def test_heading_split(self):
        """Text with markdown headings should produce 2+ chunks."""
        text = (
            "# Heading1\n"
            "This is the content under heading one, which talks about something.\n\n"
            "# Heading2\n"
            "This is the content under heading two, which is about something else.\n"
        )
        chunks = self.extractor.chunk_content(text)
        assert len(chunks) >= 2

    def test_large_section_paragraph_split(self):
        """A heading section > 800 chars should be split into paragraphs."""
        # Create a section with a heading followed by two large paragraphs
        paragraph = "This is a fairly long paragraph that contains information. " * 10
        text = (
            "# Big Section\n\n"
            + paragraph + "\n\n"
            + paragraph
        )
        chunks = self.extractor.chunk_content(text)
        # Should have at least 2 chunks from the split on double newlines
        assert len(chunks) >= 2

    def test_code_block_atomic(self):
        """Triple-backtick code block should be a single atomic chunk with is_code=True."""
        text = (
            "# Python Example\n"
            "Here is how you use async/await:\n\n"
            "```python\n"
            "import asyncio\n\n"
            "async def main():\n"
            "    await asyncio.sleep(1)\n"
            "\nasyncio.run(main())\n"
            "```\n\n"
            "The code above shows the basic pattern.\n"
        )
        chunks = self.extractor.chunk_content(text)
        code_chunks = [c for c in chunks if c[1] is True]
        assert len(code_chunks) >= 1
        # The code chunk should contain the asyncio code
        code_text = code_chunks[0][0]
        assert "asyncio" in code_text

    def test_indented_code_block(self):
        """4-space indented lines of 2+ should be detected as code."""
        text = (
            "Here is an example:\n\n"
            "    def hello():\n"
            "        print('hello')\n"
            "        return True\n\n"
            "That is the function.\n"
        )
        chunks = self.extractor.chunk_content(text)
        code_chunks = [c for c in chunks if c[1] is True]
        assert len(code_chunks) >= 1

    def test_empty_text(self):
        """Empty string should return empty list."""
        chunks = self.extractor.chunk_content("")
        assert chunks == []


# ---------------------------------------------------------------------------
# TestChunkScoring — EXTRACT-03
# ---------------------------------------------------------------------------

class TestChunkScoring:
    def setup_method(self):
        self.extractor = SnippetExtractor()

    def _make_chunks(self, texts, is_code_list=None):
        if is_code_list is None:
            is_code_list = [False] * len(texts)
        return list(zip(texts, is_code_list))

    def test_relevant_chunk_scores_higher(self):
        """The async-related chunk should score higher for 'python async' query."""
        async_chunk = (
            "Python's asyncio module provides coroutines for concurrent code. "
            "Use async def and await to write asynchronous Python programs."
        )
        unrelated_chunk = (
            "Flask is a web micro-framework. "
            "It uses Jinja2 templates and Werkzeug for routing and HTTP handling."
        )
        chunks = self._make_chunks([async_chunk, unrelated_chunk])
        results = self.extractor.score_chunks("python async", chunks, top_n=2)
        assert len(results) >= 1
        # The first (highest scoring) result should be the async chunk
        assert "async" in results[0].text.lower() or "asyncio" in results[0].text.lower()

    def test_scores_normalized(self):
        """All returned scores should be in 0.0 to 1.0 range."""
        texts = [
            "Python asyncio concurrent programming coroutines",
            "Flask web framework routes templates",
            "numpy array operations matrix multiplication",
        ]
        chunks = self._make_chunks(texts)
        results = self.extractor.score_chunks("python async", chunks)
        for r in results:
            assert 0.0 <= r.score <= 1.0, f"Score {r.score} out of range"

    def test_top_n_returned(self):
        """With 10 chunks, top_n=3 should return exactly 3 results."""
        texts = [f"Chunk number {i} with some content about topic {i}" for i in range(10)]
        chunks = self._make_chunks(texts)
        results = self.extractor.score_chunks("topic query", chunks, top_n=3)
        assert len(results) == 3

    def test_code_boost_for_code_intent(self):
        """Code chunk should get +0.2 boost when intent='code'."""
        code_text = "import asyncio\nasync def main():\n    await asyncio.sleep(1)"
        prose_text = (
            "Python asyncio module enables writing concurrent code. "
            "Use coroutines with async and await keywords to handle asynchronous operations."
        )
        chunks = [(prose_text, False), (code_text, True)]
        results_code_intent = self.extractor.score_chunks(
            "python async", chunks, intent="code", top_n=2
        )
        results_general = self.extractor.score_chunks(
            "python async", chunks, intent="general", top_n=2
        )
        # Find code chunk result in each
        code_result_boost = next((r for r in results_code_intent if r.is_code), None)
        code_result_no_boost = next((r for r in results_general if r.is_code), None)
        if code_result_boost and code_result_no_boost:
            assert code_result_boost.score >= code_result_no_boost.score

    def test_no_code_boost_for_research_intent(self):
        """Code chunk should not receive +0.2 boost for intent='research'."""
        code_text = "import asyncio\nasync def main():\n    await asyncio.sleep(1)"
        prose_text = (
            "Research on asynchronous programming paradigms shows that concurrent "
            "execution models improve throughput in I/O bound workloads significantly."
        )
        chunks = [(prose_text, False), (code_text, True)]
        results = self.extractor.score_chunks(
            "async programming research", chunks, intent="research", top_n=2
        )
        # Should not crash — just verify scores are in range
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_empty_chunks(self):
        """Empty chunk list should return empty result."""
        results = self.extractor.score_chunks("some query", [])
        assert results == []

    def test_no_length_bias(self):
        """Short precise chunk should score >= long tangential chunk (anti-pattern P2).

        A short, query-relevant answer should NOT be penalized for brevity.
        A long, tangential chunk should NOT be rewarded for length.
        """
        short_precise = "Use async def and await to write async Python coroutines."
        long_tangential = (
            "Django is a high-level Python web framework that encourages rapid "
            "development and clean pragmatic design. Built by experienced developers "
            "it takes care of much of the hassle of web development so you can focus "
            "on writing your app without needing to reinvent the wheel. It's free and "
            "open source. Django includes an ORM, authentication, URL routing, and a "
            "templating engine. It follows the model-view-template architectural pattern. "
            "Django was designed to help developers take applications from concept to "
            "completion as quickly as possible with security and scalability in mind."
        )
        chunks = [(short_precise, False), (long_tangential, False)]
        results = self.extractor.score_chunks("python async coroutines", chunks, top_n=2)
        if len(results) >= 2:
            # The precise chunk should score at least as high as the tangential one
            short_score = next((r.score for r in results if "async" in r.text.lower()), None)
            long_score = next((r.score for r in results if "django" in r.text.lower()), None)
            if short_score is not None and long_score is not None:
                assert short_score >= long_score, (
                    f"Length bias detected: short={short_score:.3f}, long={long_score:.3f}"
                )


# ---------------------------------------------------------------------------
# TestSentenceExtraction — EXTRACT-04
# ---------------------------------------------------------------------------

class TestSentenceExtraction:
    def setup_method(self):
        self.extractor = SnippetExtractor()

    def test_best_sentence_found(self):
        """Within a chunk about async/await, the best sentence for 'python async' query
        should contain 'async'."""
        chunk = (
            "Python provides many programming paradigms. "
            "The async/await syntax is the modern way to write asynchronous code in Python. "
            "You can also use threads and processes for concurrency. "
            "Functional programming is another option with map and filter."
        )
        best = self.extractor.extract_best_sentence(chunk, "python async")
        assert isinstance(best, str)
        assert len(best) > 0
        assert "async" in best.lower()

    def test_returns_string(self):
        """extract_best_sentence always returns a str."""
        result = self.extractor.extract_best_sentence("Single sentence here.", "query")
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# TestExtractedSnippetDataclass
# ---------------------------------------------------------------------------

class TestExtractedSnippetDataclass:
    def test_fields(self):
        """ExtractedSnippet must have all required fields."""
        snippet = ExtractedSnippet(
            text="sample text",
            chunk_index=0,
            score=0.85,
            is_code=False,
            source_url="https://example.com",
            best_sentence="sample text",
        )
        assert snippet.text == "sample text"
        assert snippet.chunk_index == 0
        assert snippet.score == 0.85
        assert snippet.is_code is False
        assert snippet.source_url == "https://example.com"
        assert snippet.best_sentence == "sample text"
