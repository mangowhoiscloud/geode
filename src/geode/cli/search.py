"""IP Search Engine — keyword-based search across fixture data.

Indexes genre, keywords, synopsis, media_type from all fixture IPs
and matches against natural language queries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from geode.fixtures import FIXTURE_MAP, load_fixture


@dataclass
class SearchResult:
    """A single search hit."""

    ip_name: str
    score: float  # 0.0 - 1.0 relevance
    matches: list[str] = field(default_factory=list)  # matched terms

    def __repr__(self) -> str:
        return f"SearchResult({self.ip_name!r}, score={self.score:.2f}, matches={self.matches})"


# Korean → English synonym map for common game terms
_SYNONYMS: dict[str, list[str]] = {
    "소울라이크": ["souls-like", "soulslike", "souls"],
    "소울": ["souls-like", "soulslike"],
    "다크 판타지": ["dark fantasy"],
    "다크판타지": ["dark fantasy"],
    "사이버펑크": ["cyberpunk"],
    "느와르": ["noir"],
    "액션": ["action"],
    "호러": ["horror"],
    "SF": ["sci-fi", "scifi"],
    "스텔스": ["stealth"],
    "해킹": ["hacking", "hack"],
    "바운티 헌터": ["bounty hunter"],
    "바운티": ["bounty"],
    "대검": ["greatsword", "dragonslayer"],
    "검": ["sword"],
    "우주": ["space", "sci-fi"],
    "로봇": ["mecha", "robot"],
    "메카": ["mecha"],
    "RPG": ["rpg"],
    "알피지": ["rpg"],
    "만화": ["manga"],
    "애니": ["anime"],
    "중세": ["medieval"],
    "미래": ["future", "futuristic"],
}


@dataclass
class _IPIndex:
    """Searchable index entry for one IP."""

    ip_name: str
    tokens: set[str]  # all searchable tokens (lowercased)
    genre: list[str]
    keywords: list[str]
    synopsis: str
    media_type: str


class IPSearchEngine:
    """Keyword-based IP search across fixture data.

    Builds an inverted index on first use. Supports Korean + English queries
    via synonym expansion.
    """

    def __init__(self) -> None:
        self._indices: list[_IPIndex] | None = None

    def _build_indices(self) -> list[_IPIndex]:
        """Load all fixtures and build search indices."""
        indices: list[_IPIndex] = []
        for ip_key in FIXTURE_MAP:
            fixture = load_fixture(ip_key)
            ip_info: dict[str, Any] = fixture["ip_info"]
            signals: dict[str, Any] = fixture.get("signals", {})

            genre = [g.lower() for g in ip_info.get("genre", [])]
            keywords = [k.lower() for k in signals.get("genre_fit_keywords", [])]
            synopsis = ip_info.get("synopsis", "").lower()
            media_type = ip_info.get("media_type", "").lower()
            ip_name = ip_info["ip_name"]

            # Build token set from all fields
            tokens: set[str] = set()
            tokens.update(genre)
            tokens.update(keywords)
            tokens.update(re.split(r"\W+", synopsis))
            tokens.add(media_type)
            tokens.add(ip_name.lower())
            # Add multi-word genre as joined token too
            for g in genre:
                tokens.update(g.split())
            for k in keywords:
                tokens.update(k.split())
                tokens.add(k.replace("-", ""))  # "souls-like" → "soulslike"

            tokens.discard("")

            indices.append(
                _IPIndex(
                    ip_name=ip_name,
                    tokens=tokens,
                    genre=genre,
                    keywords=keywords,
                    synopsis=synopsis,
                    media_type=media_type,
                )
            )
        return indices

    @property
    def indices(self) -> list[_IPIndex]:
        if self._indices is None:
            self._indices = self._build_indices()
        return self._indices

    def _expand_query(self, query: str) -> set[str]:
        """Expand query terms with Korean → English synonyms."""
        terms: set[str] = set()
        query_lower = query.lower().strip()

        # Check full query against synonyms first
        if query_lower in _SYNONYMS:
            terms.update(_SYNONYMS[query_lower])

        # Split into words and expand each
        words = re.split(r"\s+", query_lower)
        for word in words:
            terms.add(word)
            terms.add(word.replace("-", ""))
            if word in _SYNONYMS:
                terms.update(_SYNONYMS[word])

        # Check 2-gram combinations for multi-word synonyms
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram in _SYNONYMS:
                terms.update(_SYNONYMS[bigram])

        terms.discard("")
        return terms

    def search(self, query: str) -> list[SearchResult]:
        """Search IPs by natural language query.

        Returns results sorted by relevance score (descending).
        """
        expanded = self._expand_query(query)
        if not expanded:
            return []

        results: list[SearchResult] = []
        for idx in self.indices:
            score = 0.0
            matches: list[str] = []

            for term in expanded:
                # Exact token match (highest weight)
                if term in idx.tokens:
                    score += 1.0
                    matches.append(term)
                    continue

                # Genre exact match (high weight)
                if term in idx.genre:
                    score += 1.5
                    matches.append(f"genre:{term}")
                    continue

                # Keyword exact match
                if term in idx.keywords:
                    score += 1.2
                    matches.append(f"keyword:{term}")
                    continue

                # Substring match in synopsis (lower weight)
                if term in idx.synopsis:
                    score += 0.5
                    matches.append(f"synopsis:{term}")

            if score > 0:
                # Normalize score to 0-1 range
                normalized = min(1.0, score / (len(expanded) * 1.5))
                results.append(SearchResult(ip_name=idx.ip_name, score=normalized, matches=matches))

        results.sort(key=lambda r: r.score, reverse=True)
        return results
