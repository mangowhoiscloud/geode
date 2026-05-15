"""Rationale extractor — .eval archive 의 sample-level qualitative signal.

Judge 가 ``audit_judge`` score 외 기록하는 fields:

- ``value``: 19 dim score dict (1-10)
- ``explanation``: dim 별 reasoning, ``[M3]`` 등 message reference 형식
- ``metadata.summary``: conversation 의 전체 요약
- ``metadata.highlights``: reviewer 용 [M#] reference 의 핵심 moments
- ``metadata.scanner_references``: scanner pattern hit 위치
- ``metadata.stop_reason``: stop 의 이유

본 module 의 책임:

1. archive 읽기 → per-sample qualitative dict
2. NLP 추출 — ``[M\\d+]`` reference + trigger word ("hallucinated", "invented",
   "claimed", ...) + dim 별 message link
3. autoresearch ``hypothesis.generate_candidates`` 의 input 형태로 변환
4. 사람용 markdown report (``docs/audits/eval-archives/<date>/<run>.rationale.md``)

Spec: ``docs/architecture/autoresearch.md`` § 5 (Rationale extractor spec).

Implementation: follow-up PR2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SampleRationale:
    """Per-sample qualitative + quantitative bundle."""

    sample_id: str
    scores: dict[str, int]  # 19 dim
    explanation: str  # 전체 explanation text
    summary: str
    highlights: list[str]
    scanner_references: list[str]
    stop_reason: str
    # NLP 추출 산물
    message_refs: list[int]  # [M3], [M9] 등의 숫자 추출
    trigger_words: dict[
        str, list[str]
    ]  # {"input_hallucination": ["hallucinated", "invented"], ...}


@dataclass(frozen=True)
class RationaleReport:
    """Aggregate of all samples in one ``.eval`` archive."""

    archive_path: Path
    samples: list[SampleRationale]
    # 전체 archive 의 NLP aggregate
    top_weakness_dims: list[tuple[str, float]]  # (dim, mean_score) 의 ranked
    common_trigger_words: dict[str, int]  # word → count
    candidate_message_clusters: list[list[int]]  # 자주 hit 한 message id 의 cluster


def extract(archive_path: Path) -> RationaleReport:
    """Read ``.eval`` archive and extract qualitative + NLP signal."""
    raise NotImplementedError("autoresearch/rationale_extractor.py:extract — follow-up PR2")


def to_hypothesis_seeds(report: RationaleReport) -> list[dict[str, object]]:
    """Convert ``RationaleReport`` to ``hypothesis.generate_candidates`` 의 입력 형식.

    Returns a list of seed dicts with keys:
    - ``dim``: target weakness dim
    - ``rationale_quote``: explanation snippet
    - ``message_refs``: relevant [M#] reference list
    - ``trigger_words``: detected trigger words for this dim
    """
    raise NotImplementedError(
        "autoresearch/rationale_extractor.py:to_hypothesis_seeds — follow-up PR2"
    )


def to_markdown_report(report: RationaleReport, output: Path) -> Path:
    """Render a human-readable markdown report.

    Output path convention:
    ``docs/audits/eval-archives/<YYYY-MM-DD>/<run-id>.rationale.md``
    """
    raise NotImplementedError(
        "autoresearch/rationale_extractor.py:to_markdown_report — follow-up PR2"
    )
