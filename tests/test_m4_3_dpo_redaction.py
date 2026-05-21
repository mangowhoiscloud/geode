"""ADR-012 M4.3 — DPO pack PII / secret redaction invariants.

Pins:
- ``redact_text`` scrubs the 7 documented patterns (API keys, AWS keys,
  bearer tokens, email, phone, URL credentials, POSIX home paths).
- ``redact_pack_row`` only touches the 5 text fields (``prompt`` /
  ``chosen`` / ``rejected`` / ``source_chosen`` / ``source_rejected``);
  numeric / signature fields pass through unchanged.
- ``redact_pack`` reads → scrubs → writes a new JSONL; missing source
  yields an empty destination file (graceful). Re-running produces a
  byte-equal output (deterministic patterns).
- No false positives on common DPO content (model names, repo paths
  without usernames, plain integers).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from core.self_improving_loop.dpo_redaction import (
    PII_PATTERNS,
    redact_pack,
    redact_pack_row,
    redact_text,
)


@pytest.fixture
def src_pack(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "src" / "pack.jsonl"


@pytest.fixture
def dst_pack(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "dst" / "pack.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# Pattern coverage ----------------------------------------------------------


def test_redact_text_scrubs_anthropic_api_key() -> None:
    raw = "use key sk-ant-api03-abcdefghijklmnop-XYZ123456789 here"
    out = redact_text(raw)
    assert "sk-ant-api03" not in out
    assert "[REDACTED:secret]" in out


def test_redact_text_scrubs_openai_api_key() -> None:
    raw = "OpenAI key sk-abcdefghijklmnopqrstuvwx0123"
    out = redact_text(raw)
    assert "sk-abc" not in out
    assert "[REDACTED:secret]" in out


def test_redact_text_scrubs_email() -> None:
    raw = "Contact alice@example.com for details"
    out = redact_text(raw)
    assert "alice@example.com" not in out
    assert "[REDACTED:email]" in out


def test_redact_text_scrubs_aws_access_key() -> None:
    raw = "AWS access AKIAIOSFODNN7EXAMPLE leaked"
    out = redact_text(raw)
    assert "AKIA" not in out
    assert "[REDACTED:aws_key]" in out


def test_redact_text_scrubs_bearer_token() -> None:
    raw = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6"
    out = redact_text(raw)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6" not in out
    assert "[REDACTED:bearer]" in out


def test_redact_text_scrubs_url_credentials() -> None:
    raw = "fetch https://user:hunter2@example.com/path now"
    out = redact_text(raw)
    assert "user:hunter2" not in out
    assert "[REDACTED:url_credentials]" in out


def test_redact_text_scrubs_macos_home_path() -> None:
    raw = "wrote /Users/alice/secret/file.txt to disk"
    out = redact_text(raw)
    assert "/Users/alice/" not in out
    assert "[REDACTED:home]" in out
    assert "secret/file.txt" in out  # tail preserved


def test_redact_text_scrubs_linux_home_path() -> None:
    raw = "stored in /home/bob/.config/secrets.json"
    out = redact_text(raw)
    assert "/home/bob/" not in out
    assert "[REDACTED:home]" in out


def test_redact_text_scrubs_phone_number() -> None:
    raw = "call +1-415-555-0142 to reach support"
    out = redact_text(raw)
    assert "415-555-0142" not in out
    assert "[REDACTED:phone]" in out


def test_redact_text_empty_returns_empty() -> None:
    assert redact_text("") == ""


def test_redact_text_no_match_returns_unchanged() -> None:
    """Plain DPO content with model names + integers must NOT be touched."""
    raw = "Use claude-opus-4-7 with temperature 0.3 over 100 iterations."
    assert redact_text(raw) == raw


def test_redact_text_multiple_secrets_composed() -> None:
    """One text with email + home path + bearer all scrubbed in one pass."""
    raw = "from alice@example.com at /Users/alice/repo with Bearer abc123def456ghi789"
    out = redact_text(raw)
    assert "[REDACTED:email]" in out
    assert "[REDACTED:home]" in out
    assert "[REDACTED:bearer]" in out


# Pattern table sanity -----------------------------------------------------


def test_pii_patterns_table_nonempty_and_compilable() -> None:
    """Every entry must be a compiled regex + non-empty placeholder."""
    import re

    for pattern, placeholder in PII_PATTERNS:
        assert isinstance(pattern, re.Pattern)
        assert isinstance(placeholder, str) and placeholder


# redact_pack_row ---------------------------------------------------------


def test_redact_pack_row_only_touches_text_fields() -> None:
    row = {
        "signature": "abc123def4567890",
        "prompt": "from alice@example.com",
        "chosen": "good answer",
        "rejected": "bad answer",
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
    out = redact_pack_row(row)
    assert out["signature"] == "abc123def4567890"
    assert out["fitness_chosen"] == 0.9
    assert out["fitness_delta"] == 0.7
    assert out["ts_chosen"] == 100.0
    assert out["session_id_chosen"] == "s1"
    assert "[REDACTED:email]" in out["prompt"]
    assert out["chosen"] == "good answer"  # nothing to scrub


def test_redact_pack_row_tolerates_missing_fields() -> None:
    """Partial row with only some text fields → no KeyError."""
    row = {"prompt": "user@example.com asked", "chosen": "x"}
    out = redact_pack_row(row)
    assert "[REDACTED:email]" in out["prompt"]
    assert out["chosen"] == "x"


# redact_pack ---------------------------------------------------------------


def test_redact_pack_missing_source_writes_empty_file(tmp_path: Path, dst_pack: Path) -> None:
    missing = tmp_path / "nope.jsonl"
    n = redact_pack(missing, dst_pack)
    assert n == 0
    assert dst_pack.is_file()
    assert dst_pack.read_text(encoding="utf-8") == ""


def test_redact_pack_writes_scrubbed_rows(src_pack: Path, dst_pack: Path) -> None:
    src_pack.parent.mkdir(parents=True, exist_ok=True)
    src_pack.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "signature": "sig0",
                        "prompt": "email me at user@example.com",
                        "chosen": "ok",
                        "rejected": "no",
                        "fitness_chosen": 0.9,
                        "fitness_rejected": 0.1,
                    }
                ),
                json.dumps(
                    {
                        "signature": "sig1",
                        "prompt": "clean prompt",
                        "chosen": "Bearer abcdef1234567890abc",
                        "rejected": "/Users/alice/leak.txt",
                        "fitness_chosen": 0.8,
                        "fitness_rejected": 0.2,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    n = redact_pack(src_pack, dst_pack)
    assert n == 2
    rows = _read_jsonl(dst_pack)
    assert "[REDACTED:email]" in rows[0]["prompt"]
    assert "[REDACTED:bearer]" in rows[1]["chosen"]
    assert "[REDACTED:home]" in rows[1]["rejected"]
    assert rows[0]["signature"] == "sig0"
    assert rows[0]["fitness_chosen"] == 0.9  # untouched


def test_redact_pack_deterministic_byte_equal(src_pack: Path, dst_pack: Path) -> None:
    """Same input → same bytes out, twice."""
    src_pack.parent.mkdir(parents=True, exist_ok=True)
    src_pack.write_text(
        json.dumps(
            {
                "prompt": "alice@example.com",
                "chosen": "ok",
                "rejected": "no",
                "fitness_chosen": 0.5,
                "fitness_rejected": 0.1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    redact_pack(src_pack, dst_pack)
    bytes1 = dst_pack.read_bytes()
    redact_pack(src_pack, dst_pack)
    bytes2 = dst_pack.read_bytes()
    assert bytes1 == bytes2


def test_redact_pack_drops_malformed_lines(src_pack: Path, dst_pack: Path) -> None:
    """Bad JSON / non-dict input → skipped silently, valid rows still emitted."""
    src_pack.parent.mkdir(parents=True, exist_ok=True)
    src_pack.write_text(
        "\n".join(
            [
                "not json at all",
                json.dumps(["array not dict"]),
                json.dumps({"prompt": "alice@example.com", "chosen": "ok", "rejected": "no"}),
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    n = redact_pack(src_pack, dst_pack)
    assert n == 1
    rows = _read_jsonl(dst_pack)
    assert "[REDACTED:email]" in rows[0]["prompt"]
