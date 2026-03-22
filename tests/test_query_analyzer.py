"""Tests for query_analyzer.py — covers QUERY-01 through QUERY-04."""

import pytest
from query_analyzer import QueryAnalyzer, AnalyzedQuery


class TestIntentClassification:
    """Test QUERY-01: Intent classification with confidence scoring."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    def test_howto_intent(self):
        """'how to debug python exception' should yield how-to intent."""
        result = self.analyzer.analyze("how to debug python exception")
        assert result.intent == "how-to"
        assert result.confidence >= 0.7

    def test_code_intent(self):
        """'python import error traceback' should yield code intent."""
        result = self.analyzer.analyze("python import error traceback")
        assert result.intent == "code"
        assert result.confidence >= 0.7

    def test_news_intent(self):
        """'breaking news AI released today' should yield news intent."""
        result = self.analyzer.analyze("breaking news AI released today")
        assert result.intent == "news"
        assert result.confidence >= 0.7

    def test_research_intent(self):
        """'what is quantum computing overview' should yield research intent."""
        result = self.analyzer.analyze("what is quantum computing overview")
        assert result.intent == "research"
        assert result.confidence >= 0.7

    def test_comparison_intent(self):
        """'react vs vue pros and cons' should yield comparison intent."""
        result = self.analyzer.analyze("react vs vue pros and cons")
        assert result.intent == "comparison"
        assert result.confidence >= 0.7

    def test_lookup_intent(self):
        """'python 3.12' should return lookup or general, confidence is a valid float."""
        result = self.analyzer.analyze("python 3.12")
        assert result.intent in ("lookup", "general")
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0

    def test_low_confidence_returns_general(self):
        """Ambiguous query 'python release' should return general when confidence < 0.7."""
        result = self.analyzer.analyze("python release")
        # Either it's general (because confidence < 0.7) or it's a lookup with low confidence
        # Per D-03: confidence < 0.7 maps to "general"
        if result.confidence < 0.7:
            assert result.intent == "general"

    def test_confidence_range(self):
        """All intents must return confidence in 0.0–1.0 range."""
        queries = [
            "how to install pip",
            "python syntax error fix",
            "latest tech news",
            "explain machine learning",
            "django vs flask",
            "numpy array",
            "random gibberish xyz",
        ]
        for q in queries:
            result = self.analyzer.analyze(q)
            assert 0.0 <= result.confidence <= 1.0, (
                f"Confidence {result.confidence} out of range for query '{q}'"
            )


class TestQueryExpansion:
    """Test QUERY-02: Query expansion with abbreviation resolution."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    def test_expand_react_hooks(self):
        """'react hooks' should expand to include 'react useState useEffect'."""
        result = self.analyzer.analyze("react hooks")
        combined = " ".join(result.expanded_queries)
        assert "useState" in combined or "react useState useEffect" in combined, (
            f"Expected useState/useEffect in expansions, got: {result.expanded_queries}"
        )

    def test_expand_abbreviation(self):
        """'JS' should expand to include JavaScript."""
        result = self.analyzer.analyze("JS tutorial")
        combined = " ".join(result.expanded_queries)
        assert "javascript" in combined.lower() or "JavaScript" in combined, (
            f"Expected JavaScript in expansions, got: {result.expanded_queries}"
        )

    def test_original_preserved(self):
        """Original query is always included in expanded_queries."""
        query = "docker container"
        result = self.analyzer.analyze(query)
        assert query in result.expanded_queries, (
            f"Original query '{query}' not found in: {result.expanded_queries}"
        )


class TestQueryDecomposition:
    """Test QUERY-03: Conjunction-based query decomposition."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    def test_and_split(self):
        """'python and rust' should decompose into ['python', 'rust']."""
        result = self.analyzer.analyze("python and rust")
        assert "python" in result.sub_queries
        assert "rust" in result.sub_queries
        assert len(result.sub_queries) == 2

    def test_vs_split(self):
        """'react vs vue' should decompose into ['react', 'vue']."""
        result = self.analyzer.analyze("react vs vue")
        assert "react" in result.sub_queries
        assert "vue" in result.sub_queries
        assert len(result.sub_queries) == 2

    def test_compared_to_split(self):
        """'flask compared to django' should decompose into ['flask', 'django']."""
        result = self.analyzer.analyze("flask compared to django")
        assert "flask" in result.sub_queries
        assert "django" in result.sub_queries
        assert len(result.sub_queries) == 2

    def test_no_split_simple_query(self):
        """'python tutorial' has no conjunction — should return ['python tutorial']."""
        result = self.analyzer.analyze("python tutorial")
        assert result.sub_queries == ["python tutorial"]


class TestEntityExtraction:
    """Test QUERY-04: Regex-based entity extraction."""

    def setup_method(self):
        self.analyzer = QueryAnalyzer()

    def test_version_number(self):
        """'python 3.12.1' should contain entity {text: '3.12.1', type: 'version'}."""
        result = self.analyzer.analyze("python 3.12.1")
        entity_types = {e["type"] for e in result.entities}
        entity_texts = {e["text"] for e in result.entities}
        assert "version" in entity_types, f"Expected 'version' entity, got: {result.entities}"
        assert "3.12.1" in entity_texts, f"Expected '3.12.1' in entities, got: {result.entities}"

    def test_language_name(self):
        """'python async tutorial' should contain entity {text: 'python', type: 'language'}."""
        result = self.analyzer.analyze("python async tutorial")
        entity_types = {e["type"] for e in result.entities}
        entity_texts = {e["text"].lower() for e in result.entities}
        assert "language" in entity_types, f"Expected 'language' entity, got: {result.entities}"
        assert "python" in entity_texts, f"Expected 'python' in entities, got: {result.entities}"

    def test_library_name(self):
        """'install numpy' should contain entity {text: 'numpy', type: 'library'}."""
        result = self.analyzer.analyze("install numpy")
        entity_types = {e["type"] for e in result.entities}
        entity_texts = {e["text"].lower() for e in result.entities}
        assert "library" in entity_types, f"Expected 'library' entity, got: {result.entities}"
        assert "numpy" in entity_texts, f"Expected 'numpy' in entities, got: {result.entities}"


class TestAnalyzedQueryDataclass:
    """Test that AnalyzedQuery dataclass has all required fields."""

    def test_dataclass_fields(self):
        """AnalyzedQuery must expose: original, intent, confidence, expanded_queries, sub_queries, entities."""
        import dataclasses
        fields = {f.name for f in dataclasses.fields(AnalyzedQuery)}
        required = {"original", "intent", "confidence", "expanded_queries", "sub_queries", "entities"}
        assert required.issubset(fields), f"Missing fields: {required - fields}"
