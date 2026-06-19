"""GAP-17 — OpenAI HTML ``data:text/html`` URL guard.

Two layers:

1. ``core.llm.html_output`` recovers HTML when a model emits
   the address-bar shape anyway.
2. ``core.agent.system_prompt._build_model_card`` prepends a provider-gated
   guard that tells OpenAI/Codex models not to emit the shape in the
   first place.
"""

from __future__ import annotations

import base64
import urllib.parse
from pathlib import Path

import pytest
from core.llm.html_output import (
    decode_html,
    detect_data_url,
    extract_artifact_to,
)

# ---------------------------------------------------------------------------
# detect_data_url — recognize the address-bar shape
# ---------------------------------------------------------------------------


def test_detect_plain_percent_encoded() -> None:
    html = "<html><body>Hello world</body></html>"
    url = f"data:text/html,{urllib.parse.quote(html)}"
    match = detect_data_url(url)
    assert match is not None
    assert not match.is_base64
    assert match.params == ""
    assert match.raw == url


def test_detect_charset_only() -> None:
    """``;charset=utf-8`` declared but no base64 → percent-decoded payload."""
    url = "data:text/html;charset=utf-8,%3Cdiv%3Ehi%3C/div%3E"
    match = detect_data_url(url)
    assert match is not None
    assert not match.is_base64
    assert "charset" in match.params


def test_detect_base64() -> None:
    html = "<h1>multiline\nbody</h1>"
    payload = base64.b64encode(html.encode("utf-8")).decode("ascii")
    url = f"data:text/html;base64,{payload}"
    match = detect_data_url(url)
    assert match is not None
    assert match.is_base64
    assert match.payload == payload


def test_detect_base64_with_charset() -> None:
    """Both ``;charset=...`` and ``;base64`` declared — order varies."""
    payload = base64.b64encode(b"<p>x</p>").decode("ascii")
    url = f"data:text/html;charset=utf-8;base64,{payload}"
    match = detect_data_url(url)
    assert match is not None
    assert match.is_base64


def test_detect_embedded_in_prose() -> None:
    """Some models prefix the URL with a sentence — still detect."""
    payload = base64.b64encode(b"<html/>").decode("ascii")
    text = f"Here is the slide:\n\ndata:text/html;base64,{payload}\n\nPaste this."
    match = detect_data_url(text)
    assert match is not None
    assert match.is_base64
    # The lead-in prose is NOT part of ``match.raw``
    assert not match.raw.startswith("Here")
    assert match.raw.startswith("data:text/html")


def test_detect_missing_returns_none() -> None:
    assert detect_data_url("") is None
    assert detect_data_url("<html>plain</html>") is None
    assert detect_data_url("https://example.com/page.html") is None


# ---------------------------------------------------------------------------
# decode_html — round-trip through both encoding strategies
# ---------------------------------------------------------------------------


def test_decode_base64_roundtrip() -> None:
    body = "<!DOCTYPE html><body>한글 + emoji 🎉</body>"
    payload = base64.b64encode(body.encode("utf-8")).decode("ascii")
    match = detect_data_url(f"data:text/html;base64,{payload}")
    assert match is not None
    assert decode_html(match) == body


def test_decode_percent_encoded_roundtrip() -> None:
    body = "<div class='x'>café</div>"
    match = detect_data_url(f"data:text/html,{urllib.parse.quote(body)}")
    assert match is not None
    assert decode_html(match) == body


def test_decode_malformed_base64_falls_back() -> None:
    """When ``;base64`` is declared but the payload isn't valid base64,
    fall back to percent-decoding so the helper never raises.
    """
    url = "data:text/html;base64,%3Ch1%3Ehi%3C/h1%3E"
    match = detect_data_url(url)
    assert match is not None
    decoded = decode_html(match)
    # Either base64 garbage or percent-decoded HTML — must not raise
    assert isinstance(decoded, str)


# ---------------------------------------------------------------------------
# extract_artifact_to — disk round-trip
# ---------------------------------------------------------------------------


def test_extract_writes_to_dest(tmp_path: Path) -> None:
    body = "<!DOCTYPE html><body>chart</body>"
    payload = base64.b64encode(body.encode("utf-8")).decode("ascii")
    match = detect_data_url(f"data:text/html;base64,{payload}")
    assert match is not None

    out = extract_artifact_to(match, tmp_path / "artifacts")
    assert out.exists()
    assert out.parent == tmp_path / "artifacts"
    assert out.suffix == ".html"
    assert out.read_text(encoding="utf-8") == body


def test_extract_idempotent_filename(tmp_path: Path) -> None:
    """Same payload → same filename (hash-derived), so repeat calls
    overwrite-not-duplicate.
    """
    body = "<p>stable</p>"
    payload = base64.b64encode(body.encode("utf-8")).decode("ascii")
    match = detect_data_url(f"data:text/html;base64,{payload}")
    assert match is not None

    p1 = extract_artifact_to(match, tmp_path)
    p2 = extract_artifact_to(match, tmp_path)
    assert p1 == p2


# ---------------------------------------------------------------------------
# system_prompt guard — provider-gated injection
# ---------------------------------------------------------------------------


_GUARD_NEEDLE = "data:text/html"


@pytest.mark.parametrize("openai_model", ["gpt-5.5", "gpt-5.4-mini"])
def test_guard_present_for_openai(monkeypatch: pytest.MonkeyPatch, openai_model: str) -> None:
    """OpenAI models must receive the data-URL ban in their model card."""
    from core.agent.system_prompt import _build_model_card

    _build_model_card.cache_clear()
    card = _build_model_card(openai_model)
    assert _GUARD_NEEDLE in card, f"Missing GAP-17 guard for {openai_model}"
    assert "address bar" in card.lower()


def test_guard_present_for_codex() -> None:
    """Codex shares the OpenAI tendency — guard should apply via provider
    routing (Codex resolves to ``openai`` or ``codex`` depending on config).
    """
    from core.agent.system_prompt import _build_model_card

    _build_model_card.cache_clear()
    # Codex model id from CODEX_PRIMARY
    card = _build_model_card("gpt-5.3-codex")
    # Codex routes through OpenAI provider in _resolve_provider; check the
    # guard fires.  If the resolver renames codex models later this test
    # still asserts the address-bar phrase is present for any OpenAI-family
    # model card.
    assert _GUARD_NEEDLE in card


@pytest.mark.parametrize(
    "non_openai_model",
    ["claude-opus-4-7", "claude-sonnet-4-6", "glm-5.1", "glm-4.7"],
)
def test_guard_absent_for_non_openai(non_openai_model: str) -> None:
    """Anthropic / GLM do not exhibit the data-URL drift — guard must not
    bleed into their cards (cache pressure + irrelevant instructions).
    """
    from core.agent.system_prompt import _build_model_card

    _build_model_card.cache_clear()
    card = _build_model_card(non_openai_model)
    assert _GUARD_NEEDLE not in card, f"GAP-17 guard leaked into {non_openai_model} model card"
