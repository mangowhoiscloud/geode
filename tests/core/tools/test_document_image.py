"""Local image input: guarded files, model pixels, and byte-free durable evidence."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from core.agent.tool_executor.executor import ToolExecutor
from core.agent.tool_executor.processor import ToolCallProcessor
from core.llm.adapters._openai_common import build_codex_input, build_messages
from core.llm.adapters.base import AdapterCallRequest, Message
from core.memory.session_checkpoint import SessionCheckpoint, SessionState
from core.observability.session_timeline import SessionTimeline
from core.orchestration.context_monitor import summarize_tool_results
from core.tools import document_tools, sandbox
from core.tools.base import load_all_tool_definitions
from core.tools.document_tools import ReadDocumentTool
from core.tools.handlers.delegated import _build_delegated_handlers
from PIL import Image, PngImagePlugin


@pytest.fixture(autouse=True)
def _image_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(sandbox, "_additional_dirs", [])


@pytest.mark.parametrize("suffix", ["png", "jpg", "webp", "gif"])
def test_reads_pixels_and_retains_source_provenance(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"picture.{suffix}"
    Image.new("RGB", (32, 24), "white").save(path)
    result = asyncio.run(ReadDocumentTool().aexecute(file_path=str(path)))
    metadata = result["result"]
    image_bytes = base64.b64decode(result["content"][1]["source"]["data"])
    assert metadata["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert metadata["image_sha256"] == hashlib.sha256(image_bytes).hexdigest()
    assert (metadata["width"], metadata["height"]) == (32, 24)
    assert metadata["media_type"] == "image/png"
    with Image.open(io.BytesIO(image_bytes)) as image:
        assert image.size == (32, 24)
        assert image.getpixel((0, 0)) == (255, 255, 255, 255)


def test_missing_pillow_is_an_explicit_dependency_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "picture.png"
    Image.new("RGB", (8, 8)).save(path)
    monkeypatch.setitem(sys.modules, "PIL", None)
    result = asyncio.run(ReadDocumentTool().aexecute(file_path=str(path)))
    assert result["error_type"] == "dependency"
    assert result["recoverable"] is False


def test_rejects_invalid_large_animated_and_outside_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = ReadDocumentTool()
    path = tmp_path / "image.png"
    path.write_bytes(b"not an image")
    assert asyncio.run(tool.aexecute(file_path=str(path)))["error_type"] == "validation"
    Image.new("RGB", (16, 16)).save(path)
    monkeypatch.setattr(document_tools, "_MAX_IMAGE_PIXELS", 100)
    assert "megapixel" in asyncio.run(tool.aexecute(file_path=str(path)))["error"]
    monkeypatch.setattr(document_tools, "_MAX_IMAGE_PIXELS", 20_000_000)
    monkeypatch.setattr(document_tools, "_MAX_IMAGE_BYTES", 10)
    assert "file limit" in asyncio.run(tool.aexecute(file_path=str(path)))["error"]
    monkeypatch.setattr(document_tools, "_MAX_IMAGE_BYTES", 5 * 1024 * 1024)
    assert "text only" in asyncio.run(tool.aexecute(file_path=str(path), limit=1))["error"]
    animation = tmp_path / "frames.gif"
    Image.new("RGB", (8, 8), "red").save(
        animation, save_all=True, append_images=[Image.new("RGB", (8, 8), "blue")]
    )
    assert "Animated" in asyncio.run(tool.aexecute(file_path=str(animation)))["error"]
    link = tmp_path / "outside.png"
    link.symlink_to(tmp_path.parent / "outside.png")
    assert asyncio.run(tool.aexecute(file_path=str(link)))["error_type"] == "permission"


def test_native_registration_to_responses_and_durable_stores(tmp_path: Path) -> None:
    path = tmp_path / "plot.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("private_note", "not model input")
    Image.new("RGB", (31, 23), "red").save(path, pnginfo=info)
    definitions = {item["name"]: item for item in load_all_tool_definitions()}
    assert "PNG" in definitions["read_document"]["description"]
    handlers = _build_delegated_handlers()
    executor = ToolExecutor(
        action_handlers={"read_document": handlers["read_document"]},
        auto_approve=True,
        hitl_level=0,
    )
    timeline = SessionTimeline(
        "image-session",
        db_path=tmp_path / "events.db",
        projection_path=tmp_path / "events.jsonl",
    )
    logger = MagicMock()
    offload = MagicMock(threshold=1)
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=logger,
        error_recovery=MagicMock(),
        timeline=timeline,
        offload_store=offload,
    )
    call = {
        "type": "tool_use",
        "id": "view-1",
        "name": "read_document",
        "input": {"file_path": str(path)},
    }
    outputs = asyncio.run(processor.process(SimpleNamespace(content=[SimpleNamespace(**call)])))
    image_b64 = outputs[0]["content"][1]["source"]["data"]
    wire = build_codex_input(
        AdapterCallRequest(
            model="gpt-5.6-sol",
            messages=(
                Message(role="assistant", content=[call]),
                Message(role="user", content=outputs),
            ),
        )
    )
    item = wire[-1]
    assert item["type"] == "function_call_output"
    assert item["call_id"] == "view-1"
    assert item["output"][1] == {
        "type": "input_image",
        "image_url": f"data:image/png;base64,{image_b64}",
        "detail": "high",
    }
    assert not any(item.get("type") == "computer_call_output" for item in wire)
    offload.offload.assert_not_called()
    with Image.open(io.BytesIO(base64.b64decode(image_b64))) as image:
        assert "private_note" not in image.info
    # The real event writer and checkpoint writer both retain hashes, never pixels.
    timeline.record_tool_result("read_document", "ok", call_id="direct", result=outputs[0])
    checkpoint = SessionCheckpoint(tmp_path / "checkpoints")
    state = SessionState(
        session_id="image-session",
        messages=[{"role": "user", "content": outputs}],
        tool_log=processor.tool_log,
    )
    checkpoint.save(state)
    loaded = checkpoint.load("image-session")
    assert loaded is not None
    for stored in (
        json.dumps(processor.tool_log),
        str(logger.mock_calls),
        (tmp_path / "events.jsonl").read_text(),
        json.dumps(loaded.messages),
        json.dumps(loaded.tool_log),
    ):
        assert image_b64 not in stored
        assert "image_sha256" in stored
    assert image_b64 == state.messages[0]["content"][0]["content"][1]["source"]["data"]
    decorated = {**outputs[0], "additional_context": "Observe only; do not claim verification."}
    projected = asyncio.run(processor._serialize_tool_result(decorated, "view-2", "read_document"))
    assert "Observe only" in projected["content"][-1]["text"]


def test_responses_rejects_malformed_image_source() -> None:
    request = AdapterCallRequest(
        model="gpt-5.6-sol",
        messages=(
            Message(
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": "bad",
                        "content": [{"type": "image", "source": {"type": "base64", "data": "x"}}],
                    }
                ],
            ),
        ),
    )
    with pytest.raises(ValueError, match="supported base64"):
        build_codex_input(request)


def test_image_results_are_not_text_summarized_or_stringified() -> None:
    image = {"type": "image", "source": {"type": "base64", "data": "x" * 200_000}}
    outputs = [{"type": "tool_result", "tool_use_id": "view", "content": [image]}]
    messages = [{"role": "user", "content": outputs}]
    count, _before, _after = summarize_tool_results(messages, target_window=10_000)
    assert count == 0
    assert messages[0]["content"][0]["content"][0] == image
    request = AdapterCallRequest(
        model="chat-only", messages=(Message(role="user", content=outputs),)
    )
    with pytest.raises(ValueError, match="Chat Completions image tool output is unsupported"):
        build_messages(request)
