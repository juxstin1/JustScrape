"""
QueryAnalyzer — Rules-based query understanding module.

Classifies user intent, expands queries with related terms, decomposes
conjunctive queries into sub-queries, and extracts named entities from
search terms — all using regex and lookup tables with zero ML dependencies.

Implements requirements QUERY-01 through QUERY-04.
"""

import re
from dataclasses import dataclass, field
from typing import List


# =============================================================================
# MODULE-LEVEL COMPILED REGEX PATTERNS (per codebase convention)
# =============================================================================

# QUERY-01: Intent classification patterns
_CODE_PATTERN = re.compile(
    r'\b(?:error|exception|traceback|bug|fix|debug|crash|syntax|import|'
    r'null|undefined|attribute|typeerror|valueerror|keyerror|indexerror|'
    r'stack\s*trace|segfault|compile|runtime|deprecat|warning|'
    r'function|class|method|loop|array|dict|list|object|pointer|'
    r'module|package|install\s+\w|pip\s+install|npm\s+install)\b',
    re.IGNORECASE,
)

_NEWS_PATTERN = re.compile(
    r'\b(?:news|breaking|latest|today|yesterday|announce|launch|release[sd]|'
    r'update[sd]|report[sed]|publish|event|incident|happen|occur|just\s+now|'
    r'this\s+week|this\s+month|recently|current\s+events?|current\s+news|'
    r'currently\s+happening|trending)\b',
    re.IGNORECASE,
)

_HOW_TO_PATTERN = re.compile(
    r'\b(?:how\s+to|how\s+do|how\s+can|steps?\s+to|guide\s+to|tutorial|'
    r'walkthrough|instructions?\s+for|learn\s+to|example\s+of|getting\s+started|'
    r'quickstart|beginners?\s+guide|set\s+up|setup\s+guide|configure|'
    r'install\s+and|usage\s+of)\b',
    re.IGNORECASE,
)

_RESEARCH_PATTERN = re.compile(
    r'\b(?:what\s+is|what\s+are|explain|overview|introduction|definition|'
    r'difference\s+between|concept|theory|understand|describe|summary|'
    r'fundamentals?|principles?|architecture|design|deep\s+dive|'
    r'in-depth|comprehensive|complete\s+guide)\b',
    re.IGNORECASE,
)

_COMPARISON_PATTERN = re.compile(
    r'\b(?:vs\.?|versus|compared\s+to|comparison|pros\s+and\s+cons|'
    r'difference\s+between|better\s+than|worse\s+than|which\s+is\s+better|'
    r'alternative\s+to|or\s+vs\s+|benchmark|tradeoff|trade-off)\b',
    re.IGNORECASE,
)

_LOOKUP_PATTERN = re.compile(
    r'\b(?:documentation|docs|api\s+reference|changelog|version|release\s+notes|'
    r'official\s+site|homepage|download|cheatsheet|cheat\s+sheet|'
    r'reference|spec|specification)\b',
    re.IGNORECASE,
)

# QUERY-03: Decomposition — split only on explicit conjunction tokens
_CONJUNCTION_PATTERN = re.compile(
    r'\s+(?:and|vs\.?|or|compared\s+to)\s+',
    re.IGNORECASE,
)

# QUERY-04: Entity extraction patterns
_VERSION_PATTERN = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b')

# =============================================================================
# LOOKUP TABLES
# =============================================================================

# QUERY-02: Abbreviation expansion map
_ABBREVIATION_MAP = {
    "JS": "JavaScript",
    "TS": "TypeScript",
    "py": "python",
    "ML": "machine learning",
    "AI": "artificial intelligence",
    "DB": "database",
    "API": "application programming interface",
    "CSS": "cascading style sheets",
    "HTML": "hypertext markup language",
    "SQL": "structured query language",
    "k8s": "kubernetes",
    "tf": "terraform",
}

# QUERY-02: Term expansion — related terms for common tech topics
_TERM_EXPANSION_MAP = {
    "react hooks": ["react useState useEffect", "react useCallback useMemo"],
    "docker": ["docker container dockerfile"],
    "git": ["git commit push pull branch"],
    "typescript": ["typescript types interfaces generics"],
    "async": ["async await promise"],
    "css": ["css flexbox grid responsive"],
    "sql": ["sql query select join where"],
    "api": ["api rest endpoint json"],
    "kubernetes": ["kubernetes pod deployment service"],
    "webpack": ["webpack bundler config"],
    "redux": ["redux store action reducer"],
    "graphql": ["graphql query mutation schema"],
}

# QUERY-04: Language names for entity extraction
_LANGUAGE_NAMES = {
    "python", "javascript", "typescript", "rust", "go", "java",
    "c++", "ruby", "php", "swift", "kotlin", "scala", "perl",
    "lua", "r", "julia", "elixir", "haskell", "clojure", "dart",
    "c#", "csharp", "cpp", "c",
}

# QUERY-04: Library / framework names for entity extraction
_LIBRARY_NAMES = {
    "numpy", "pandas", "react", "vue", "angular", "django", "flask",
    "fastapi", "express", "tensorflow", "pytorch", "scikit-learn",
    "matplotlib", "requests", "httpx", "playwright", "docker",
    "kubernetes", "redis", "postgres", "mongodb", "sqlalchemy",
    "celery", "pytest", "unittest", "selenium", "bs4", "beautifulsoup",
    "scipy", "pillow", "pydantic", "click", "typer", "fastapi",
    "starlette", "uvicorn", "gunicorn", "nginx", "apache",
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class AnalyzedQuery:
    """Container for the result of query analysis.

    Attributes:
        original: The raw query string as provided by the caller.
        intent: Classified intent — one of: code, research, news, how-to,
                lookup, comparison, general.
        confidence: Confidence score for the intent classification (0.0–1.0).
        expanded_queries: List of query variants including abbreviation
                          expansions and related-term variants. Always
                          includes the original query.
        sub_queries: List of individual parts after conjunction splitting.
                     Single-part queries return a list with the original.
        entities: List of extracted entities, each a dict with keys
                  ``text`` (matched string) and ``type`` (entity category).
    """

    original: str
    intent: str
    confidence: float
    expanded_queries: List[str] = field(default_factory=list)
    sub_queries: List[str] = field(default_factory=list)
    entities: List[dict] = field(default_factory=list)


# =============================================================================
# QUERY ANALYZER
# =============================================================================

class QueryAnalyzer:
    """Rules-based query analyzer with zero ML dependencies.

    Provides intent classification, query expansion, conjunction-based
    decomposition, and regex entity extraction. All logic is deterministic
    and reproducible — no probabilistic models, no external services.
    """

    def classify_intent(self, query: str) -> tuple[str, float]:
        """Classify the intent of a query and return a confidence score.

        Strategy: count pattern matches per intent category. The winning
        category is determined by highest match count. Confidence is
        computed as ``top_count / total_count + 0.3`` capped at 1.0.
        Zero matches yields ("lookup", 0.5). Confidence < 0.7 returns
        ("general", confidence) per D-03.

        Args:
            query: Raw search query string.

        Returns:
            Tuple of (intent_label, confidence) where intent_label is one
            of: ``code``, ``research``, ``news``, ``how-to``, ``lookup``,
            ``comparison``, ``general``.
        """
        patterns = {
            "how-to": _HOW_TO_PATTERN,
            "code": _CODE_PATTERN,
            "news": _NEWS_PATTERN,
            "research": _RESEARCH_PATTERN,
            "comparison": _COMPARISON_PATTERN,
            "lookup": _LOOKUP_PATTERN,
        }

        match_counts: dict[str, int] = {}
        for label, pattern in patterns.items():
            matches = pattern.findall(query)
            match_counts[label] = len(matches)

        total_matches = sum(match_counts.values())

        if total_matches == 0:
            return ("general", 0.5)

        # How-to is a strong structural signal — boost it if matched so it
        # wins over incidental code/research keyword matches in the same query
        # (e.g. "how to debug python exception" is how-to, not code).
        if match_counts.get("how-to", 0) > 0:
            match_counts["how-to"] = match_counts["how-to"] * 3

        # Comparison is also a strong structural signal ("vs", "compared to")
        if match_counts.get("comparison", 0) > 0:
            match_counts["comparison"] = match_counts["comparison"] * 2

        top_label = max(match_counts, key=lambda k: match_counts[k])
        top_count = match_counts[top_label]

        # Recompute total after boosting for proper confidence ratio
        boosted_total = sum(match_counts.values())

        # Compute confidence: proportion of top label's matches + base boost
        confidence = min(1.0, (top_count / boosted_total) + 0.3)

        if confidence < 0.7:
            return ("general", confidence)

        return (top_label, confidence)

    def expand_query(self, query: str) -> List[str]:
        """Expand a query with abbreviation resolutions and related terms.

        Always includes the original query as the first element. Expands
        known abbreviations and appends related term variants.

        Args:
            query: Raw search query string.

        Returns:
            List of query variants. The original query is always first.
        """
        expanded = [query]
        query_lower = query.lower()

        # Abbreviation expansion: replace abbreviations with full forms
        for abbrev, full_form in _ABBREVIATION_MAP.items():
            pattern = re.compile(r'\b' + re.escape(abbrev) + r'\b', re.IGNORECASE)
            if pattern.search(query):
                expanded_variant = pattern.sub(full_form, query)
                if expanded_variant != query and expanded_variant not in expanded:
                    expanded.append(expanded_variant)

        # Term expansion: add related terms for known phrases
        for term, variants in _TERM_EXPANSION_MAP.items():
            if term.lower() in query_lower:
                for variant in variants:
                    if variant not in expanded:
                        expanded.append(variant)

        return expanded

    def decompose_query(self, query: str) -> List[str]:
        """Decompose a query into sub-queries by splitting on conjunctions.

        Splits ONLY on: ``and``, ``vs``/``vs.``, ``or``, ``compared to``.
        Returns the original query in a single-element list if no conjunction
        is found (per D-05).

        Args:
            query: Raw search query string.

        Returns:
            List of sub-query strings. At minimum, returns ``[query]``.
        """
        parts = _CONJUNCTION_PATTERN.split(query)
        parts = [p.strip() for p in parts if p.strip()]
        return parts if len(parts) > 1 else [query]

    def extract_entities(self, query: str) -> List[dict]:
        """Extract named entities from a query using compiled regex patterns.

        Recognises three entity types:
        - ``version``: Semantic version numbers like ``3.12`` or ``v2.0.1``
        - ``language``: Known programming language names
        - ``library``: Known library / framework names

        Args:
            query: Raw search query string.

        Returns:
            List of entity dicts, each with ``text`` (matched string) and
            ``type`` (entity category string).
        """
        entities: List[dict] = []
        seen_spans: set[tuple[int, int]] = set()

        # Version numbers
        for match in _VERSION_PATTERN.finditer(query):
            span = (match.start(), match.end())
            if span not in seen_spans:
                seen_spans.add(span)
                entities.append({"text": match.group(), "type": "version"})

        # Language names (word-boundary match, case-insensitive)
        query_lower = query.lower()
        for lang in _LANGUAGE_NAMES:
            pattern = re.compile(r'\b' + re.escape(lang) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(query_lower):
                span = (match.start(), match.end())
                if span not in seen_spans:
                    seen_spans.add(span)
                    entities.append({"text": lang, "type": "language"})

        # Library / framework names
        for lib in _LIBRARY_NAMES:
            pattern = re.compile(r'\b' + re.escape(lib) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(query_lower):
                span = (match.start(), match.end())
                if span not in seen_spans:
                    seen_spans.add(span)
                    entities.append({"text": lib, "type": "library"})

        return entities

    def analyze(self, query: str) -> AnalyzedQuery:
        """Orchestrate all analysis steps and return a populated AnalyzedQuery.

        Args:
            query: Raw search query string.

        Returns:
            AnalyzedQuery dataclass with all fields populated.
        """
        intent, confidence = self.classify_intent(query)
        expanded_queries = self.expand_query(query)
        sub_queries = self.decompose_query(query)
        entities = self.extract_entities(query)

        return AnalyzedQuery(
            original=query,
            intent=intent,
            confidence=confidence,
            expanded_queries=expanded_queries,
            sub_queries=sub_queries,
            entities=entities,
        )
