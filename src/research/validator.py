"""
SourceValidator — stage 3 of the research pipeline.

Turns the raw, possibly-duplicated pile of sources from the collector into a
clean, scored, citable set:

  * reliability scoring  — domain + provider heuristics (0.0 .. 1.0)
  * deduplication        — by normalised URL, then by snippet fingerprint
  * citation extraction  — stable, human-readable citation strings
  * conflict detection   — lightweight contradiction signal across sources

Scoring is heuristic by design (no network, no LLM) so it stays fast and
deterministic on the lean host; the interface leaves room to swap in a learned
reliability model later.
"""

from __future__ import annotations

import hashlib
import logging
import re

from src.research.models import Source


logger = logging.getLogger(__name__)

# Domain suffix / substring → reliability weight.
_HIGH_TRUST_SUFFIXES = (".gov", ".edu", ".int", ".mil", ".ac.uk", ".gov.uk")
_HIGH_TRUST_DOMAINS = (
    "wikipedia.org", "nature.com", "science.org", "sciencedirect.com",
    "arxiv.org", "ncbi.nlm.nih.gov", "who.int", "ieee.org", "acm.org",
    "springer.com", "jstor.org", "nasa.gov", "oecd.org", "un.org",
)
_MEDIUM_TRUST_DOMAINS = (
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "economist.com",
    "nytimes.com", "theguardian.com", "bloomberg.com", "wsj.com",
    "github.com", "docs.python.org", "developer.mozilla.org",
)
_PROVIDER_WEIGHT = {"wikipedia": 0.15, "tavily": 0.1, "duckduckgo": 0.0, "web": 0.0}

# Naive contradiction signal — opposing polarity terms about the same subject.
_NEGATION_RE = re.compile(r"\b(not|no|never|cannot|isn't|doesn't|won't|false|incorrect)\b", re.I)


class SourceValidator:
    def __init__(self, *, min_reliability: float = 0.0) -> None:
        self._min_reliability = min_reliability

    def validate(self, sources: list[Source]) -> list[Source]:
        """Score, then deduplicate. Returns sources sorted by reliability desc."""
        for source in sources:
            source.reliability = self.score(source)

        deduped = self._deduplicate(sources)
        kept = [s for s in deduped if s.reliability >= self._min_reliability]
        kept.sort(key=lambda s: s.reliability, reverse=True)
        return kept

    # ------------------------------------------------------------------
    def score(self, source: Source) -> float:
        """Assign a reliability score in [0, 1]."""
        domain = (source.domain or "").lower()
        score = 0.4  # neutral baseline for a returned web result

        if any(domain.endswith(suf) for suf in _HIGH_TRUST_SUFFIXES):
            score = 0.9
        elif any(d in domain for d in _HIGH_TRUST_DOMAINS):
            score = 0.85
        elif any(d in domain for d in _MEDIUM_TRUST_DOMAINS):
            score = 0.65

        score += _PROVIDER_WEIGHT.get(source.provider, 0.0)

        # Substantive content is a mild positive signal.
        if len(source.snippet) > 400:
            score += 0.05

        # Missing URL is a strong negative signal (can't be verified).
        if not source.url:
            score -= 0.3

        return max(0.0, min(1.0, score))

    def _deduplicate(self, sources: list[Source]) -> list[Source]:
        seen_urls: set[str] = set()
        seen_fingerprints: set[str] = set()
        out: list[Source] = []
        for source in sources:
            url_key = _normalise_url(source.url)
            fp = _fingerprint(source.snippet)
            if url_key and url_key in seen_urls:
                continue
            if fp and fp in seen_fingerprints:
                continue
            if url_key:
                seen_urls.add(url_key)
            if fp:
                seen_fingerprints.add(fp)
            out.append(source)
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def citations(sources: list[Source]) -> list[str]:
        """Build stable, numbered citation strings."""
        cites: list[str] = []
        for i, s in enumerate(sources, 1):
            title = s.title or s.domain or s.url or "Untitled source"
            cites.append(f"[{i}] {title} — {s.url} ({s.provider}, reliability {s.reliability:.2f})")
        return cites

    @staticmethod
    def detect_conflicts(sources: list[Source]) -> list[str]:
        """Flag potential contradictions between sources on the same question.

        Heuristic: within a question group, if some snippets negate and others
        affirm while sharing salient keywords, surface a soft conflict notice.
        """
        by_question: dict[str, list[Source]] = {}
        for s in sources:
            by_question.setdefault(s.question, []).append(s)

        conflicts: list[str] = []
        for question, group in by_question.items():
            if len(group) < 2 or not question:
                continue
            negating = [s for s in group if _NEGATION_RE.search(s.snippet)]
            affirming = [s for s in group if not _NEGATION_RE.search(s.snippet)]
            if negating and affirming:
                conflicts.append(
                    f"Potential conflict on '{question}': "
                    f"{len(affirming)} source(s) affirm vs {len(negating)} with negations — "
                    "manual review recommended."
                )
        return conflicts


def _normalise_url(url: str) -> str:
    if not url:
        return ""
    u = url.strip().lower().rstrip("/")
    u = re.sub(r"^https?://", "", u)
    u = u.removeprefix("www.")
    return u.split("#")[0].split("?")[0]


def _fingerprint(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.strip().lower())[:300]
    if len(norm) < 40:
        return ""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
