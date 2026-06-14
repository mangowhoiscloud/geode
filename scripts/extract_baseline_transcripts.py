"""Extract the baseline audit's auditor↔target↔judge transcripts to JSON.

The self-improving baseline (the runtime ``baseline.json`` under
``~/.geode/self-improving/``) is produced by one Petri audit over the survivor
seed pool. That audit's ``.eval`` log holds
everything the baseline hub page needs to *show its work*: the seed scenario
bodies, the auditor↔target conversation per seed, and the judge's 22-dim scores
that aggregate into the promoted ``dim_means``.

This script reads that ``.eval`` once (it depends on ``inspect_ai``, which the
Pages CI does not install) and writes a self-contained, git-tracked
``transcripts.json`` next to the rendered page. ``build_self_improving_hub.py``
then renders from that JSON alone — no ``inspect_ai`` import on the build path,
no dependence on a local ``.eval`` that other machines lack.

Run locally after a baseline ``--promote``::

    uv run python scripts/extract_baseline_transcripts.py

By default it resolves the ``.eval`` from ``baseline.json``'s ``eval_archive``
field. Override with ``--eval <path>``; change the destination with ``--out``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.paths import BASELINE_JSON_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
# baseline.json is RUNTIME (out-of-repo) post PR-STATE-SOT-RUNTIME-SPLIT — resolve
# it from the single core.paths SoT (honours GEODE_STATE_ROOT) rather than the
# deleted repo-root ``state/`` tree. The served output dir keeps the
# ``autoresearch`` lineage name.
DEFAULT_BASELINE = BASELINE_JSON_PATH
DEFAULT_OUT = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "baseline" / "transcripts.json"
)

# Cap any single message body so the committed JSON + rendered page stay small;
# effort=high reasoning blocks can run long. Full fidelity lives in the .eval.
_MAX_TEXT = 8000


def _content_text(content: Any) -> tuple[str, str]:
    """Return (visible_text, reasoning_text) from a message's content.

    inspect_ai message content is either a plain ``str`` or a list of typed
    content blocks (``ContentText`` / ``ContentReasoning`` / tool results).
    """
    if isinstance(content, str):
        return content[:_MAX_TEXT], ""
    visible: list[str] = []
    reasoning: list[str] = []
    for block in content or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            visible.append(str(getattr(block, "text", "")))
        elif btype == "reasoning":
            reasoning.append(str(getattr(block, "reasoning", "") or getattr(block, "summary", "")))
        else:
            text_attr = getattr(block, "text", None)
            if text_attr:
                visible.append(str(text_attr))
    return ("\n".join(visible)[:_MAX_TEXT], "\n".join(r for r in reasoning if r)[:_MAX_TEXT])


def _speaker(role: str, visible: str) -> str:
    """Classify a message for display on the baseline page."""
    if role == "system":
        return "system"
    if role == "user":
        return "setup"
    if role == "assistant":
        return "auditor"
    if role == "tool":
        # The target's reply comes back to the auditor as a tool result whose
        # body is wrapped in <target_response>…</target_response>.
        return "target" if "<target_response>" in visible else "tool_ack"
    return role


def _extract_turns(messages: list[Any]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for msg in messages or []:
        role = str(getattr(msg, "role", "?"))
        visible, reasoning = _content_text(getattr(msg, "content", ""))
        tool_calls: list[dict[str, Any]] = []
        for call in getattr(msg, "tool_calls", None) or []:
            fn = getattr(call, "function", None)
            name = fn if isinstance(fn, str) else getattr(fn, "name", str(fn))
            args = getattr(call, "arguments", None) or {}
            if not isinstance(args, dict):
                args = {"_": str(args)}
            sent = args.get("message")
            other = {k: v for k, v in args.items() if k != "message"}
            tool_calls.append(
                {
                    "tool": name,
                    "message": (str(sent)[:_MAX_TEXT] if sent is not None else None),
                    "args": other or None,
                }
            )
        turns.append(
            {
                "speaker": _speaker(role, visible),
                "role": role,
                "text": visible,
                "reasoning": reasoning,
                "tool_calls": tool_calls,
            }
        )
    return turns


def _role_model(eval_spec: Any, role: str) -> str | None:
    """Pull the resolved model id for a Petri model-role from the eval header."""
    roles = getattr(eval_spec, "model_roles", None) or {}
    entry = roles.get(role) if isinstance(roles, dict) else None
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry.get("model")
    return getattr(entry, "model", None) or str(entry)


def _resolve_eval_path(baseline_path: Path) -> Path | None:
    if not baseline_path.is_file():
        return None
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    raw = data.get("raw") if isinstance(data, dict) else None
    archive = (raw or {}).get("eval_archive") or data.get("eval_archive")
    return Path(archive) if archive else None


def extract(eval_path: Path, *, fitness: float | None = None) -> dict[str, Any]:
    from inspect_ai.log import read_eval_log

    log = read_eval_log(str(eval_path), resolve_attachments=True)
    samples_out: list[dict[str, Any]] = []
    for sample in log.samples or []:
        audit_judge = (sample.scores or {}).get("audit_judge")
        raw_value = audit_judge.value if audit_judge else None
        scores = dict(raw_value) if isinstance(raw_value, dict) else {}
        explanation = str(getattr(audit_judge, "explanation", "") or "") if audit_judge else ""
        meta = sample.metadata or {}
        samples_out.append(
            {
                "id": str(sample.id),
                "name": meta.get("name") or str(sample.id),
                "target_dims": meta.get("target_dims") or meta.get("tags") or [],
                "category": meta.get("category"),
                "seed_body": str(sample.input),
                "turns": _extract_turns(sample.messages),
                "scores": scores,
                "judge_explanation": explanation[:_MAX_TEXT],
                "total_time_s": round(float(sample.total_time or 0.0), 1),
            }
        )
    return {
        "eval_file": eval_path.name,
        "status": str(log.status),
        "fitness": fitness,
        "auditor_model": _role_model(log.eval, "auditor"),
        "target_model": _role_model(log.eval, "target"),
        "judge_model": _role_model(log.eval, "judge"),
        "sample_count": len(samples_out),
        "samples": samples_out,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", type=Path, default=None, help="path to the .eval log")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--fitness",
        type=float,
        default=None,
        help="promoted fitness scalar (from the run's FITNESS_RESULT line); "
        "baseline.json does not persist it (derived at decision time)",
    )
    args = parser.parse_args(argv)

    eval_path = args.eval or _resolve_eval_path(args.baseline)
    if eval_path is None or not eval_path.is_file():
        print(
            f"error: no .eval found (eval={eval_path}, baseline={args.baseline})",
            file=sys.stderr,
        )
        return 1

    payload = extract(eval_path, fitness=args.fitness)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.out} — {payload['sample_count']} samples from {payload['eval_file']} "
        f"(auditor={payload['auditor_model']}, target={payload['target_model']})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
