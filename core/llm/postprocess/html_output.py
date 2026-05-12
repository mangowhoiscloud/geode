"""Detect + decode OpenAI-style HTML data URLs (GAP-17).

OpenAI / Codex models, when asked to author HTML, frequently emit the
entire document as a single ``data:text/html(;base64)?,...`` URL meant to
be pasted into a browser's address bar.  GEODE pipelines expect HTML to
land on disk as a regular file (slide builds, report PDF pipelines,
artifact archiving), so the address-bar shape silently breaks downstream
consumers AND inflates ``output_tokens`` 30–50% from base64 overhead.

This module provides three pure-function helpers:

- ``detect_data_url(text)`` — scan text for a leading ``data:text/html``
  URL and return a structured match (or ``None`` if absent).
- ``decode_html(match)`` — recover the original HTML string (percent- or
  base64-decoded as appropriate).
- ``extract_artifact_to(match, dest_dir)`` — write the recovered HTML
  to a unique file under ``dest_dir`` and return the path.

The system prompt (``core.agent.system_prompt._build_model_card``) carries
the primary guard — instructing OpenAI models to emit raw ``<!DOCTYPE
html>`` source.  These helpers are the safety net for the cases where
the model emits the address-bar form anyway.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

# Permissive regex — matches the address-bar shape regardless of optional
# parameters (``charset=utf-8``, ``;base64``).  The payload is captured
# greedily until end-of-string because a data URL is typically the
# entire response when the model adopts this shape.
_DATA_URL_RE = re.compile(
    r"data:text/html(?P<params>(?:;[\w=-]+)*),(?P<payload>.+)",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class DataUrlMatch:
    """Structured result of ``detect_data_url``.

    Attributes:
        params: Raw parameter segment (``;charset=utf-8;base64``) without
            the leading semicolon split — used to decide decoding strategy.
        payload: The raw payload after the comma. Still encoded — call
            ``decode_html`` to recover the original HTML string.
        is_base64: True when the URL declared ``;base64``.
        raw: The entire matched substring, including the ``data:`` prefix.
    """

    params: str
    payload: str
    is_base64: bool
    raw: str


def detect_data_url(text: str) -> DataUrlMatch | None:
    """Return a ``DataUrlMatch`` if *text* contains a ``data:text/html`` URL.

    The matcher is intentionally permissive — it does not anchor at start
    of string because some models prefix the URL with explanatory prose
    ("Here is the HTML: data:text/html;base64,...").  When the URL is
    not at the very start, the leading prose is *not* preserved in the
    match; callers wanting to drop both the URL and the lead-in should
    operate on ``match.raw``.
    """
    if not text or "data:text/html" not in text:
        return None
    m = _DATA_URL_RE.search(text)
    if m is None:
        return None
    params = m.group("params") or ""
    payload = m.group("payload") or ""
    return DataUrlMatch(
        params=params,
        payload=payload,
        is_base64=";base64" in params.lower(),
        raw=m.group(0),
    )


def decode_html(match: DataUrlMatch) -> str:
    """Recover the original HTML string from *match*.

    Base64 payloads round-trip through ``base64.b64decode`` (UTF-8
    decoded). Non-base64 payloads go through ``urllib.parse.unquote``
    to undo percent-encoding (``%3C`` → ``<``).  Malformed base64
    falls back to percent-decoding so the helper never raises on
    real-world model output.
    """
    payload = match.payload.strip()
    if match.is_base64:
        try:
            return base64.b64decode(payload, validate=False).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError):
            # Some models emit a base64 declaration but plain-encoded
            # content.  Fall through to percent-decoding.
            pass
    return urllib.parse.unquote(payload)


def extract_artifact_to(match: DataUrlMatch, dest_dir: Path) -> Path:
    """Write the recovered HTML to a unique file under *dest_dir*.

    The filename is derived from a short hash of the payload so repeated
    extraction of the same content stays idempotent — useful when the
    helper is wired into a retry loop.  Returns the resulting path.

    *dest_dir* is created if missing (``parents=True``).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    body = decode_html(match)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    target = dest_dir / f"openai_html_{digest}.html"
    target.write_text(body, encoding="utf-8")
    return target
