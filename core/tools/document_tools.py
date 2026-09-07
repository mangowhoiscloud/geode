"""Document Tools — local file reading as LLM-callable tool.

Provides local text reads and bounded image inputs for the current model.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import warnings
from pathlib import Path
from typing import Any

from core.tools.sandbox import validate_path

log = logging.getLogger(__name__)

# File size guard defaults (Claude Code parity)
_MAX_FILE_SIZE_BYTES = 262_144  # 256 KB — pre-read check
_MAX_READ_TOKENS = 25_000  # post-read token estimate check
_CHARS_PER_TOKEN = 4  # rough estimate for token counting
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000


class ReadDocumentTool:
    """Read local text or inspect a static image through the model's vision input."""

    @property
    def name(self) -> str:
        return "read_document"

    @property
    def description(self) -> str:
        return "Read local text or view PNG, JPEG, WebP, and static GIF images."

    @staticmethod
    def _read_image(file_path: Path) -> dict[str, Any]:
        from core.tools.base import tool_error

        try:
            from PIL import Image, ImageOps
        except ImportError:
            return tool_error(
                "Image reading requires the optional Pillow dependency.",
                error_type="dependency",
                recoverable=False,
            )
        try:
            # Bound both compressed input and decoded pixels before loading.
            with file_path.open("rb") as source_file:
                raw = source_file.read(_MAX_IMAGE_BYTES + 1)
            if len(raw) > _MAX_IMAGE_BYTES:
                raise ValueError("Image exceeds the 5 MiB file limit; crop or resize it first.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG", "WEBP", "GIF"]) as image:
                    if image.width * image.height > _MAX_IMAGE_PIXELS:
                        raise ValueError("Image exceeds the 20 megapixel limit; crop it first.")
                    if getattr(image, "n_frames", 1) != 1:
                        raise ValueError("Animated images are unsupported; extract a frame first.")
                    source_media_type = Image.MIME[image.format or ""]
                    image.load()
                    view = ImageOps.exif_transpose(image).convert("RGBA")
                    # Re-encode pixels only: do not send EXIF, ICC, or text metadata.
                    view.info.clear()
                    encoded = io.BytesIO()
                    view.save(encoded, format="PNG")
                    image_bytes = encoded.getvalue()
                    width, height = view.size
            if len(image_bytes) > _MAX_IMAGE_BYTES:
                raise ValueError("Decoded PNG exceeds the 5 MiB limit; crop or resize it first.")
        except (
            OSError,
            ValueError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            return tool_error(str(exc), error_type="validation", recoverable=True)
        metadata = {
            "file_path": str(file_path),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "source_media_type": source_media_type,
            "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "media_type": "image/png",
            "width": width,
            "height": height,
        }
        return {
            "type": "tool_result",
            "result": metadata,
            "content": [
                {"type": "text", "text": json.dumps(metadata, ensure_ascii=False)},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                },
            ],
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        file_path_str: str = kwargs["file_path"]

        # offset/limit with max_lines backward compat
        offset = kwargs.get("offset")
        if offset is None:
            offset = 1
        limit = kwargs.get("limit")
        if limit is None:
            limit = kwargs.get("max_lines")

        from core.tools.base import tool_error

        for name, value in (("offset", offset), ("limit", limit)):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 1
            ):
                return tool_error(
                    f"{name} must be a positive integer or null.",
                    error_type="validation",
                )

        result = validate_path(file_path_str, write=False)
        if isinstance(result, dict):
            return result
        file_path = result

        if not file_path.exists():
            return tool_error(
                f"File not found: {file_path}",
                error_type="not_found",
                hint="Check the file path or use a different file.",
                context={"file_path": str(file_path)},
            )

        if not file_path.is_file():
            return tool_error(
                f"Not a file: {file_path}",
                error_type="validation",
                hint="Provide a path to a file, not a directory.",
                context={"file_path": str(file_path)},
            )

        if file_path.suffix.lower() in _IMAGE_EXTENSIONS:
            if offset != 1 or limit is not None:
                return tool_error(
                    "Line controls apply to text only; omit them or set them to null "
                    "to view an image.",
                    error_type="validation",
                )
            return self._read_image(file_path)

        # Pre-read file size guard: only when no explicit limit (full-file read)
        from core.config import settings

        max_file_size = settings.sandbox_max_file_size_bytes
        max_read_tokens = settings.sandbox_max_read_tokens

        if limit is None:
            try:
                size = file_path.stat().st_size
            except OSError:
                size = 0
            if size > max_file_size:
                return tool_error(
                    f"File too large: {size:,} bytes (limit {max_file_size:,})",
                    error_type="validation",
                    recoverable=True,
                    hint=(
                        "Use offset and limit to read a range.  "
                        "Example: offset=1, limit=200 for the first 200 lines."
                    ),
                    context={
                        "file_path": str(file_path),
                        "file_size": size,
                        "max_size": max_file_size,
                    },
                )

        try:
            all_lines = file_path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            return tool_error(
                f"Failed to read {file_path}: {exc}",
                error_type="internal",
                context={"file_path": str(file_path)},
            )

        total_lines = len(all_lines)

        # Apply offset (1-indexed) and limit
        start_idx = max(0, offset - 1)
        end_idx = start_idx + limit if limit is not None else total_lines

        selected = all_lines[start_idx:end_idx]
        content = "\n".join(selected)

        # Post-read token guard: estimate tokens and truncate if needed
        truncated = end_idx < total_lines
        estimated_tokens = len(content) // _CHARS_PER_TOKEN
        if estimated_tokens > max_read_tokens:
            # Truncate to approximate token limit
            max_chars = max_read_tokens * _CHARS_PER_TOKEN
            content = content[:max_chars]
            truncated = True

        return {
            "result": {
                "file_path": str(file_path),
                "content": content,
                "total_lines": total_lines,
                "start_line": start_idx + 1,
                "num_lines": len(selected),
                "truncated": truncated,
            }
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run local document reads off the event loop."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)
