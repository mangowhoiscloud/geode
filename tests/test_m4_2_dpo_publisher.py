"""ADR-012 M4.2 — DPO publisher adapter invariants.

Pins:
- 3 target adapters (``trl`` / ``openai`` / ``bedrock``) emit the
  per-provider JSONL row shape claimed in :mod:`core.self_improving_loop.dpo_publisher`.
- ``publish_pack(target, pack_path, out_path)`` overwrites ``out_path``
  with one transformed row per valid pack row, returning the count.
- Unsupported target → ``ValueError``.
- Pure transforms — no network, no SDK imports, no API keys.
- Graceful: missing pack → 0 rows, empty file; malformed lines dropped;
  rows missing the ``prompt``/``chosen``/``rejected`` triple skipped.
- Idempotency: second run over the same pack produces byte-equal output.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from core.self_improving_loop.dpo_publisher import (
    SUPPORTED_TARGETS,
    publish_pack,
    to_bedrock_format,
    to_openai_format,
    to_trl_format,
)


@pytest.fixture
def pack_path(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "pack.jsonl"


@pytest.fixture
def out_path(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "published" / "out.jsonl"


def _write_pack(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


_SAMPLE_PACK_ROW = {
    "signature": "abc123def4567890",
    "prompt": "What is DPO?",
    "chosen": "DPO is Direct Preference Optimization.",
    "rejected": "I don't know.",
    "fitness_chosen": 0.9,
    "fitness_rejected": 0.2,
    "fitness_delta": 0.7,
    "ts_chosen": 100.0,
    "ts_rejected": 200.0,
    "session_id_chosen": "s1",
    "session_id_rejected": "s2",
    "source_chosen": "petri_audit",
    "source_rejected": "live_session",
}


# Adapter shape -------------------------------------------------------------


def test_trl_format_returns_minimal_triple() -> None:
    out = to_trl_format(_SAMPLE_PACK_ROW)
    assert out == {
        "prompt": "What is DPO?",
        "chosen": "DPO is Direct Preference Optimization.",
        "rejected": "I don't know.",
    }
    assert set(out.keys()) == {"prompt", "chosen", "rejected"}


def test_openai_format_uses_messages_schema() -> None:
    out = to_openai_format(_SAMPLE_PACK_ROW)
    assert out["input"]["messages"] == [{"role": "user", "content": "What is DPO?"}]
    assert out["preferred_output"] == [
        {"role": "assistant", "content": "DPO is Direct Preference Optimization."}
    ]
    assert out["non_preferred_output"] == [{"role": "assistant", "content": "I don't know."}]


def test_bedrock_format_carries_fitness_metadata() -> None:
    """Bedrock passthrough keeps the audit fields so per-model adapters can use them."""
    out = to_bedrock_format(_SAMPLE_PACK_ROW)
    assert out["prompt"] == "What is DPO?"
    assert out["chosen"] == "DPO is Direct Preference Optimization."
    assert out["rejected"] == "I don't know."
    assert out["signature"] == "abc123def4567890"
    assert out["fitness_chosen"] == 0.9
    assert out["fitness_rejected"] == 0.2
    assert out["fitness_delta"] == 0.7


def test_bedrock_format_tolerates_missing_optionals() -> None:
    """Adapter doesn't crash when fitness fields are absent from the row."""
    row = {"prompt": "p", "chosen": "c", "rejected": "r"}
    out = to_bedrock_format(row)
    assert out["signature"] == ""
    assert out["fitness_chosen"] is None
    assert out["fitness_rejected"] is None


# Supported targets manifest ------------------------------------------------


def test_supported_targets_manifest() -> None:
    """The Literal type alias and SUPPORTED_TARGETS must stay in sync."""
    assert SUPPORTED_TARGETS == ("trl", "openai", "bedrock")


# publish_pack --------------------------------------------------------------


def test_publish_pack_writes_one_row_per_pack_row(pack_path: Path, out_path: Path) -> None:
    _write_pack(pack_path, [_SAMPLE_PACK_ROW, _SAMPLE_PACK_ROW])
    n = publish_pack(target="trl", pack_path=pack_path, out_path=out_path)
    assert n == 2
    rows = _read_jsonl(out_path)
    assert len(rows) == 2
    assert all(r["prompt"] == "What is DPO?" for r in rows)


def test_publish_pack_overwrites_existing_destination(pack_path: Path, out_path: Path) -> None:
    """First call writes 3 rows; second call with 1-row pack leaves only 1 row."""
    _write_pack(pack_path, [_SAMPLE_PACK_ROW, _SAMPLE_PACK_ROW, _SAMPLE_PACK_ROW])
    publish_pack(target="trl", pack_path=pack_path, out_path=out_path)
    _write_pack(pack_path, [_SAMPLE_PACK_ROW])
    n = publish_pack(target="trl", pack_path=pack_path, out_path=out_path)
    assert n == 1
    assert len(_read_jsonl(out_path)) == 1


def test_publish_pack_byte_equal_on_rerun(pack_path: Path, out_path: Path) -> None:
    """Same pack + same target → byte-equal output (idempotent)."""
    _write_pack(pack_path, [_SAMPLE_PACK_ROW, _SAMPLE_PACK_ROW])
    publish_pack(target="openai", pack_path=pack_path, out_path=out_path)
    bytes1 = out_path.read_bytes()
    publish_pack(target="openai", pack_path=pack_path, out_path=out_path)
    bytes2 = out_path.read_bytes()
    assert bytes1 == bytes2


def test_publish_pack_missing_pack_writes_empty_file(tmp_path: Path, out_path: Path) -> None:
    missing = tmp_path / "nope.jsonl"
    n = publish_pack(target="trl", pack_path=missing, out_path=out_path)
    assert n == 0
    assert out_path.is_file()
    assert out_path.read_text(encoding="utf-8") == ""


def test_publish_pack_invalid_target_raises(pack_path: Path, out_path: Path) -> None:
    _write_pack(pack_path, [_SAMPLE_PACK_ROW])
    with pytest.raises(ValueError, match="unsupported target"):
        publish_pack(
            target="anthropic",  # type: ignore[arg-type]  # intentional bad target
            pack_path=pack_path,
            out_path=out_path,
        )


def test_publish_pack_drops_malformed_lines(pack_path: Path, out_path: Path) -> None:
    """Bad JSON + non-dict + missing triple → skipped, no crash."""
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(
        "\n".join(
            [
                "not json",
                json.dumps(["array not dict"]),
                json.dumps({"prompt": "p"}),  # missing chosen/rejected
                json.dumps({"prompt": 123, "chosen": "c", "rejected": "r"}),  # non-str prompt
                json.dumps(_SAMPLE_PACK_ROW),
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    n = publish_pack(target="trl", pack_path=pack_path, out_path=out_path)
    assert n == 1  # only the valid row


# Per-target round-trip via publish_pack -------------------------------------


def test_publish_pack_dispatches_to_openai_adapter(pack_path: Path, out_path: Path) -> None:
    _write_pack(pack_path, [_SAMPLE_PACK_ROW])
    publish_pack(target="openai", pack_path=pack_path, out_path=out_path)
    rows = _read_jsonl(out_path)
    assert rows[0]["input"]["messages"][0]["role"] == "user"
    assert rows[0]["preferred_output"][0]["role"] == "assistant"


def test_publish_pack_dispatches_to_bedrock_adapter(pack_path: Path, out_path: Path) -> None:
    _write_pack(pack_path, [_SAMPLE_PACK_ROW])
    publish_pack(target="bedrock", pack_path=pack_path, out_path=out_path)
    rows = _read_jsonl(out_path)
    assert rows[0]["fitness_delta"] == 0.7
    assert rows[0]["signature"] == "abc123def4567890"


# No-network guard -----------------------------------------------------------


def test_no_network_imports_in_module() -> None:
    """Pure transform — no SDK imports in module source (static AST check).

    A runtime ``sys.modules`` check is fragile because the test file
    itself imports the publisher at top level, so any forbidden SDK
    pulled in transitively would already be loaded before the test
    captures its baseline. An AST walk of the module source is the
    definitive check: if the import statement isn't there, the SDK
    cannot have been loaded by this module.
    """
    import ast
    import inspect

    import core.self_improving_loop.dpo_publisher as pub

    forbidden = {
        "openai",
        "boto3",
        "transformers",
        "trl",
        "requests",
        "httpx",
        "urllib3",
        "anthropic",
    }
    source = inspect.getsource(pub)
    tree = ast.parse(source)
    imported_top_level: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_top_level.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_top_level.add(node.module.split(".", 1)[0])
    bad = imported_top_level & forbidden
    assert not bad, f"dpo_publisher must not import network SDKs; found: {bad}"
