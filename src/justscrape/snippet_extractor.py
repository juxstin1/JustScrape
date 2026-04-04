"""
Snippet Extractor — Precision content extraction for JustScrape.

Extracts clean text from HTML via trafilatura, chunks content by headings and
paragraphs, scores chunks with BM25+TF-IDF blended ranking, and identifies
the most relevant sentence within the best chunk.

EXTRACT-01: trafilatura-based HTML text extraction
EXTRACT-02: hybrid heading/paragraph chunking with code block detection
EXTRACT-03: BM25+TF-IDF blended scoring with code intent boost
EXTRACT-04: sentence-level TF-IDF matching within top chunks
"""

import re
from dataclasses import dataclass
from typing import List, Tuple

import trafilatura
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ---------------------------------------------------------------------------
# Module-level compiled regex patterns (per D-12/D-15 codebase conventions)
# ---------------------------------------------------------------------------

_HEADING_PATTERN = re.compile(r'^#{1,6}\s+.+$', re.MULTILINE)
_CODE_FENCE_PATTERN = re.compile(r'```[\s\S]*?```', re.MULTILINE)
_INDENTED_CODE_PATTERN = re.compile(r'(?:(?:^(?:    |\t).+\n?){2,})', re.MULTILINE)

from .config import CHUNK_SIZE_THRESHOLD


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class ExtractedSnippet:
    """A single extracted and scored content snippet.

    Per D-13: returned by score_chunks, populated by extract_snippets.
    """
    text: str
    chunk_index: int
    score: float           # blended BM25+TF-IDF, 0.0-1.0 (per D-14)
    is_code: bool          # True if chunk is a code block (per D-15)
    source_url: str
    best_sentence: str     # Most relevant sentence within chunk (per EXTRACT-04)


# ---------------------------------------------------------------------------
# SnippetExtractor
# ---------------------------------------------------------------------------

class SnippetExtractor:
    """Extract precise content snippets from raw HTML using BM25+TF-IDF ranking.

    Pipeline:
        extract_text(html) -> chunk_content(text) -> score_chunks(query, chunks)

    Each step is also available as a standalone method for testing and composition.
    """

    # ------------------------------------------------------------------
    # EXTRACT-01: Text extraction via trafilatura
    # ------------------------------------------------------------------

    def extract_text(self, html: str, url: str = "") -> str:
        """Extract clean text from HTML using trafilatura.

        Per D-16/EXTRACT-01: favor_precision=True, include_tables, no comments.
        Per Pitfall P4: trafilatura.extract() can return None — always coerce to str.

        Args:
            html: Raw HTML string.
            url:  Source URL hint for trafilatura (improves extraction quality).

        Returns:
            Clean text string. Empty string on failure — never None.
        """
        if not html:
            return ""
        try:
            result = trafilatura.extract(
                html,
                url=url if url else None,
                favor_precision=True,
                include_tables=True,
                include_comments=False,
                include_formatting=False,
            )
            # Pitfall P4: coerce None to empty string
            return result or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # EXTRACT-02: Hybrid chunking — headings → paragraphs → code blocks
    # ------------------------------------------------------------------

    def chunk_content(self, text: str) -> List[Tuple[str, bool]]:
        """Chunk text into (chunk_text, is_code) tuples.

        Algorithm (per D-12):
        1. Extract code fences (```...```) → replace with placeholders.
        2. Detect 4-space/tab indented blocks of 2+ lines → replace with placeholders.
        3. Split remaining text on heading patterns (# through ######).
        4. For heading-sections > CHUNK_SIZE_THRESHOLD chars, split further on
           double newlines (paragraph boundaries).
        5. Restore code placeholders as atomic chunks with is_code=True.
        6. Strip empty results.

        Args:
            text: Plain text (post-extraction), not HTML.

        Returns:
            List of (chunk_text, is_code) tuples. Empty list for empty input.
        """
        if not text or not text.strip():
            return []

        code_blocks: List[Tuple[str, bool]] = []  # (placeholder_key, original_text)
        working = text

        # Step 1: Extract triple-backtick code fences
        def _replace_fence(m: re.Match) -> str:
            idx = len(code_blocks)
            placeholder = f"\x00CODE_BLOCK_{idx}\x00"
            code_blocks.append((placeholder, m.group(0)))
            return placeholder

        working = _CODE_FENCE_PATTERN.sub(_replace_fence, working)

        # Step 2: Extract 4-space/tab indented code blocks (2+ consecutive lines)
        def _replace_indented(m: re.Match) -> str:
            # Only treat as code if it looks like code (not just indented prose)
            block = m.group(0)
            # Skip if already replaced
            if "\x00CODE_BLOCK_" in block:
                return block
            idx = len(code_blocks)
            placeholder = f"\x00CODE_BLOCK_{idx}\x00"
            code_blocks.append((placeholder, block))
            return placeholder

        working = _INDENTED_CODE_PATTERN.sub(_replace_indented, working)

        # Step 3: Split on headings — find heading positions
        heading_positions = [m.start() for m in _HEADING_PATTERN.finditer(working)]

        if not heading_positions:
            # No headings — treat the whole text as one section for paragraph splitting
            sections = [working]
        else:
            sections = []
            for i, pos in enumerate(heading_positions):
                start = pos
                end = heading_positions[i + 1] if i + 1 < len(heading_positions) else len(working)
                sections.append(working[start:end])
            # Include any text before the first heading
            preamble = working[: heading_positions[0]].strip()
            if preamble:
                sections.insert(0, preamble)

        # Step 4: For each section > threshold, split on double newlines
        raw_chunks: List[str] = []
        for section in sections:
            if len(section) > CHUNK_SIZE_THRESHOLD:
                # Split on blank lines (paragraph boundaries)
                paragraphs = re.split(r'\n\s*\n', section)
                raw_chunks.extend(p for p in paragraphs if p.strip())
            else:
                if section.strip():
                    raw_chunks.append(section)

        # Step 5: Build final chunk list, restoring code placeholders
        code_lookup = {ph: orig for ph, orig in code_blocks}
        result: List[Tuple[str, bool]] = []

        for chunk in raw_chunks:
            if not chunk.strip():
                continue
            # Check if this chunk is (or contains) a code placeholder
            if "\x00CODE_BLOCK_" in chunk:
                # Split around placeholders to handle mixed content
                parts = re.split(r'(\x00CODE_BLOCK_\d+\x00)', chunk)
                for part in parts:
                    if not part.strip():
                        continue
                    if part in code_lookup:
                        original = code_lookup[part]
                        result.append((original.strip(), True))
                    else:
                        result.append((part.strip(), False))
            else:
                result.append((chunk.strip(), False))

        # Also emit any code blocks not yet emitted (guard for edge cases)
        all_raw = "".join(raw_chunks)
        for ph, orig in code_blocks:
            if ph not in all_raw:
                result.append((orig.strip(), True))

        return [(t, c) for t, c in result if t]

    # ------------------------------------------------------------------
    # EXTRACT-03: BM25 + TF-IDF blended scoring
    # ------------------------------------------------------------------

    def score_chunks(
        self,
        query: str,
        chunks: List[Tuple[str, bool]],
        intent: str = "general",
        top_n: int = 3,
        bm25_weight: float = 0.5,
    ) -> List[ExtractedSnippet]:
        """Score and rank chunks using blended BM25 + TF-IDF.

        Per D-14/EXTRACT-03:
        - Tokenize with .lower().split()
        - BM25Okapi scoring, normalize by max (guard max==0, per Pitfall P3)
        - TfidfVectorizer + cosine_similarity
        - Blend: bm25_weight * bm25_norm + (1 - bm25_weight) * tfidf_score
        - Per D-15: +0.2 boost for is_code chunks when intent=="code" (cap at 1.0)
        - NO length component (Pitfall P2 anti-pattern explicitly avoided)

        Args:
            query:       Search query string.
            chunks:      List of (chunk_text, is_code) tuples.
            intent:      Query intent: "general", "code", "research", "news".
            top_n:       Maximum number of results to return.
            bm25_weight: Weight for BM25 score (1 - bm25_weight for TF-IDF).

        Returns:
            List of ExtractedSnippet sorted by score descending, up to top_n.
        """
        if not chunks:
            return []

        texts = [t for t, _ in chunks]
        is_code_flags = [c for _, c in chunks]

        # BM25 scoring (per Pitfall P3: normalize by max, guard max==0)
        tokenized_corpus = [t.lower().split() for t in texts]
        tokenized_query = query.lower().split()

        bm25 = BM25Okapi(tokenized_corpus)
        bm25_raw = bm25.get_scores(tokenized_query)

        # Guard against NaN from degenerate inputs (C5)
        import math
        bm25_raw = [0.0 if (math.isnan(s) or math.isinf(s)) else float(s) for s in bm25_raw]
        bm25_max_val = max(bm25_raw) if bm25_raw else 0.0
        bm25_max = bm25_max_val if bm25_max_val > 0 else 1.0
        bm25_norm = [s / bm25_max for s in bm25_raw]

        # TF-IDF cosine similarity scoring
        all_texts = texts + [query]
        try:
            vectorizer = TfidfVectorizer(min_df=1, stop_words=None)
            tfidf_matrix = vectorizer.fit_transform(all_texts)
            query_vec = tfidf_matrix[-1]
            doc_vecs = tfidf_matrix[:-1]
            tfidf_scores_raw = cosine_similarity(query_vec, doc_vecs)[0]
        except Exception:
            tfidf_scores_raw = [0.0] * len(texts)

        tfidf_scores_raw = [0.0 if (math.isnan(s) or math.isinf(s)) else float(s) for s in tfidf_scores_raw]
        tfidf_max_val = max(tfidf_scores_raw) if tfidf_scores_raw else 0.0
        tfidf_max = tfidf_max_val if tfidf_max_val > 0 else 1.0
        tfidf_scores = [s / tfidf_max for s in tfidf_scores_raw]

        # Blend scores — NO length component (Pitfall P2)
        blended = [
            bm25_weight * bm25_norm[i] + (1.0 - bm25_weight) * tfidf_scores[i]
            for i in range(len(texts))
        ]

        # Code boost for code intent (per D-15)
        if intent == "code":
            blended = [
                min(s + 0.2, 1.0) if is_code_flags[i] else s
                for i, s in enumerate(blended)
            ]

        # Sort descending by score and take top_n with score > 0
        indexed = sorted(enumerate(blended), key=lambda x: x[1], reverse=True)
        results: List[ExtractedSnippet] = []
        for chunk_index, score in indexed:
            if len(results) >= top_n:
                break
            if score <= 0.0:
                continue
            best_sentence = self.extract_best_sentence(texts[chunk_index], query)
            results.append(ExtractedSnippet(
                text=texts[chunk_index],
                chunk_index=chunk_index,
                score=score,
                is_code=is_code_flags[chunk_index],
                source_url="",
                best_sentence=best_sentence,
            ))

        return results

    # ------------------------------------------------------------------
    # EXTRACT-04: Sentence-level TF-IDF matching
    # ------------------------------------------------------------------

    def extract_best_sentence(self, chunk_text: str, query: str) -> str:
        """Find the most relevant sentence within a chunk using TF-IDF cosine.

        Per EXTRACT-04: Split on sentence boundaries, score each against query
        with TF-IDF + cosine_similarity, return highest-scoring sentence.
        NOT neural — pure TF-IDF. Neural is Phase 3.

        Args:
            chunk_text: Text of the chunk to search within.
            query:      Search query.

        Returns:
            Best matching sentence string. Returns full chunk if <= 1 sentence.
        """
        if not chunk_text or not chunk_text.strip():
            return ""

        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.?!])\s+', chunk_text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) <= 1:
            return chunk_text.strip()

        try:
            all_texts = sentences + [query]
            vectorizer = TfidfVectorizer(min_df=1, stop_words=None)
            tfidf_matrix = vectorizer.fit_transform(all_texts)
            query_vec = tfidf_matrix[-1]
            doc_vecs = tfidf_matrix[:-1]
            scores = cosine_similarity(query_vec, doc_vecs)[0]
            best_idx = int(scores.argmax())
            return sentences[best_idx]
        except Exception:
            return sentences[0] if sentences else chunk_text.strip()

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def extract_snippets(
        self,
        html: str,
        query: str,
        intent: str = "general",
        url: str = "",
        top_n: int = 3,
    ) -> List[ExtractedSnippet]:
        """Orchestrate full extraction pipeline: extract → chunk → score.

        Args:
            html:   Raw HTML string to process.
            query:  Search query for scoring.
            intent: Query intent for code boost ("code", "general", etc.).
            url:    Source URL for trafilatura hint and result metadata.
            top_n:  Maximum number of snippets to return.

        Returns:
            List of ExtractedSnippet sorted by score descending. Empty list if
            extraction produces no text or no relevant chunks found.
        """
        # Detect if input is already plain text (no HTML tags) — skip trafilatura
        if html and "<" not in html[:1000]:
            text = html
        else:
            text = self.extract_text(html, url=url)
        if not text:
            return []

        chunks = self.chunk_content(text)
        if not chunks:
            return []

        results = self.score_chunks(query, chunks, intent=intent, top_n=top_n)

        # Set source_url on all results
        for snippet in results:
            snippet.source_url = url

        return results
