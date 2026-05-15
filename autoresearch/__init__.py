"""autoresearch — Petri-signal fork of Karpathy/autoresearch (MIT, 2026-03).

Karpathy 의 3-file pattern (``prepare.py`` / ``train.py`` / ``program.md``)
을 GEODE alignment-audit 도메인으로 옮긴 fork. ML pre-train + ``val_bpb``
의 자리에 Petri seed pool + AlphaEval 5-axis fitness 가 들어간다. 본
``__init__`` 은 deliberately empty — 본 fork 의 outer-loop agent 는 모듈을
import 하지 않고 ``uv run python autoresearch/train.py`` 의 단일 script
패턴을 사용한다 (원본의 single-file constraint 보존).

Reference: ``autoresearch/README.md`` + ``autoresearch/program.md``.
"""
