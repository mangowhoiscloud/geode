"""LLM response post-processing helpers.

Currently exposes ``html_output`` — detects OpenAI/Codex's tendency to emit
HTML as a single ``data:text/html`` URL (the 'paste-into-address-bar'
shape) and converts it back into a regular HTML artifact (GAP-17).
"""

from __future__ import annotations

from core.llm.postprocess.html_output import (
    DataUrlMatch,
    decode_html,
    detect_data_url,
    extract_artifact_to,
)

__all__ = [
    "DataUrlMatch",
    "decode_html",
    "detect_data_url",
    "extract_artifact_to",
]
