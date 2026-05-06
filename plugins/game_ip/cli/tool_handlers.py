"""Game-IP tool-handler bundle (analysis + signals + generate_data).

Step 4 (domain-free-core) relocated the IP-specific halves of
``core/cli/tool_handlers.py`` into this plugin module. Handlers re-merge
into the generic ``_DELEGATED_TOOLS`` registry and into the dispatcher
output dict at bootstrap via ``GameIPDomain.register_tool_handlers``
(see ``core/cli/tool_handlers.py:install_domain_tool_handlers``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.ui.console import console

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Game-IP signal tools (delegated via lazy import — same shape as core's
# ``_DELEGATED_TOOLS`` registry).
# ---------------------------------------------------------------------------

GAME_IP_DELEGATED_TOOLS: dict[str, tuple[str, str]] = {
    "youtube_search": ("plugins.game_ip.tools.signal_tools", "YouTubeSearchTool"),
    "reddit_sentiment": ("plugins.game_ip.tools.signal_tools", "RedditSentimentTool"),
    "steam_info": ("plugins.game_ip.tools.signal_tools", "SteamInfoTool"),
    "google_trends": ("plugins.game_ip.tools.signal_tools", "GoogleTrendsTool"),
}


def _clarify(
    tool: str,
    missing: list[str],
    hint: str,
    **extra: Any,
) -> dict[str, Any]:
    """Standard clarification response for missing required params."""
    return {
        "error": f"{tool} requires: {', '.join(missing)}",
        "clarification_needed": True,
        "missing": missing,
        "hint": hint,
        **extra,
    }


def _safe_delegate(tool_class: type, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Wrap delegated tool execution -- catch KeyError as clarification."""
    try:
        result: dict[str, Any] = tool_class().execute(**kwargs)
        return result
    except (KeyError, TypeError) as exc:
        param = str(exc).strip("'\"")
        return _clarify(
            tool_class.__name__,
            [param],
            f"'{param}' 값을 알려주세요.",
        )


def _make_delegate_handler(
    module_path: str,
    class_name: str,
) -> Callable[..., dict[str, Any]]:
    """Return a handler that lazily imports *class_name* from *module_path* and delegates."""

    def _handler(**kwargs: Any) -> dict[str, Any]:
        import importlib

        mod = importlib.import_module(module_path)
        tool_cls = getattr(mod, class_name)
        return _safe_delegate(tool_cls, kwargs)

    return _handler


# ---------------------------------------------------------------------------
# Analysis handlers (list_ips / analyze_ip / search_ips / compare_ips /
# generate_report / batch_analyze).
# ---------------------------------------------------------------------------


def _build_analysis_handlers(
    verbose: bool,
    force_dry: bool | None,
    skill_registry: Any,
) -> dict[str, Any]:
    """Build analysis-related tool handlers.

    ``force_dry`` may be ``None`` to defer the dry-run decision to call
    time (re-read ``_get_readiness()`` inside each handler). When the
    bundle is built from ``core/cli/tool_handlers.py:_build_tool_handlers``
    we pass the readiness-derived value at build time as before; when
    built via ``register_tool_handlers`` at bootstrap (no readiness in
    scope yet), ``None`` triggers the lazy lookup.
    """
    from core.cli import (
        _generate_report,
        _get_search_engine,
        _render_search_results,
        _run_analysis,
    )

    def _force_dry() -> bool:
        if force_dry is not None:
            return force_dry
        from core.cli import _get_readiness

        readiness = _get_readiness()
        return readiness.force_dry_run if readiness else True

    def handle_list_ips(**_kwargs: Any) -> dict[str, Any]:
        from plugins.game_ip.cli.commands import cmd_list
        from plugins.game_ip.fixtures import FIXTURE_MAP as _FM

        cmd_list()
        names = [n.title() for n in _FM]
        return {"status": "ok", "action": "list", "count": len(names), "ips": names}

    def handle_analyze_ip(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("analyze_ip", ["ip_name"], "어떤 IP를 분석할까요?")
        dry_run = kwargs.get("dry_run", _force_dry())
        result = _run_analysis(ip_name, dry_run=dry_run, verbose=verbose)
        # Pipeline cost/model notice for live runs (non-dry-run)
        pipeline_notice: str | None = None
        if not dry_run:
            pipeline_notice = (
                "이 분석은 claude-opus-4-6 (Primary) + gpt-5.4 (Cross-LLM)을 사용합니다. "
                "예상: ~8 LLM 호출, ~$0.15, ~15초."
            )
        if result is None:
            return {"error": f"Analysis failed for '{ip_name}'"}
        # Extract analyst summaries for LLM context
        analyses_summary = []
        for a in result.get("analyses", []):
            if hasattr(a, "model_dump"):
                a = a.model_dump()
            analyses_summary.append(
                {
                    "type": a.get("analyst_type", "?"),
                    "score": a.get("score", 0),
                    "finding": a.get("key_finding", ""),
                }
            )
        synthesis = result.get("synthesis")
        if synthesis is not None and hasattr(synthesis, "model_dump"):
            synthesis = synthesis.model_dump()
        out: dict[str, Any] = {
            "status": "ok",
            "action": "analyze",
            "ip_name": result.get("ip_name", ip_name),
            "tier": result.get("tier", "N/A"),
            "score": round(result.get("final_score", 0), 1),
            "cause": (
                (synthesis or {}).get("cause", "unknown")
                if isinstance(synthesis, dict)
                else "unknown"
            ),
            "analyses": analyses_summary,
        }
        if pipeline_notice:
            out["pipeline_notice"] = pipeline_notice
        return out

    def handle_search_ips(**kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        if not query:
            return _clarify("search_ips", ["query"], "무엇을 검색할까요?")
        results = _get_search_engine().search(query)
        _render_search_results(query, results)
        return {
            "status": "ok",
            "action": "search",
            "query": query,
            "count": len(results),
            "results": [{"name": r.ip_name, "score": r.score} for r in results],
        }

    def handle_compare_ips(**kwargs: Any) -> dict[str, Any]:
        ip_a = kwargs.get("ip_a", "")
        ip_b = kwargs.get("ip_b", "")
        dry_run = kwargs.get("dry_run", _force_dry())

        # Clarification: both IPs required
        if not ip_a or not ip_b:
            missing = [k for k, v in {"ip_a": ip_a, "ip_b": ip_b}.items() if not v]
            hint = "어떤 IP와 비교할까요?" if ip_a else "비교할 두 IP를 알려주세요."
            return _clarify("compare_ips", missing, hint, provided={"ip_a": ip_a, "ip_b": ip_b})

        console.print(f"\n  [header]Compare: {ip_a} vs {ip_b}[/header]\n")
        result_a = _run_analysis(ip_a, dry_run=dry_run, verbose=verbose)
        result_b = _run_analysis(ip_b, dry_run=dry_run, verbose=verbose)

        def _ip_summary(name: str, r: dict[str, Any] | None) -> dict[str, Any]:
            if not r:
                return {"name": name, "tier": "N/A", "score": 0}
            return {
                "name": name,
                "tier": r.get("tier", "N/A"),
                "score": round(r.get("final_score", 0), 1),
            }

        return {
            "status": "ok",
            "action": "compare",
            "ip_a": _ip_summary(ip_a, result_a),
            "ip_b": _ip_summary(ip_b, result_b),
        }

    def handle_generate_report(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("generate_report", ["ip_name"], "어떤 IP의 리포트를 생성할까요?")
        fmt = kwargs.get("format", "markdown")
        if fmt == "md":
            fmt = "markdown"
        template = kwargs.get("template", "summary")
        dry_run = kwargs.get("dry_run", _force_dry())
        report_result = _generate_report(
            ip_name,
            dry_run=dry_run,
            verbose=verbose,
            fmt=fmt,
            template=template,
            skill_registry=skill_registry,
        )
        if report_result is None:
            return {"error": f"Report generation failed for '{ip_name}'"}
        file_path, content = report_result
        return {
            "status": "ok",
            "action": "report",
            "ip_name": ip_name,
            "format": fmt,
            "template": template,
            "file_path": file_path,
            "content_preview": content[:500] if len(content) > 500 else content,
            "content_length": len(content),
        }

    def handle_batch_analyze(**kwargs: Any) -> dict[str, Any]:
        from plugins.game_ip.cli.batch import render_batch_table, run_batch

        top = kwargs.get("top", 20)
        genre = kwargs.get("genre")
        dry_run = kwargs.get("dry_run", _force_dry())
        batch_results = run_batch(top=top, genre=genre, dry_run=dry_run)
        render_batch_table(batch_results)
        summary = []
        for br in batch_results:
            if br:
                summary.append(
                    {
                        "ip_name": br.get("ip_name", "?"),
                        "tier": br.get("tier", "?"),
                        "score": round(br.get("final_score", 0), 1),
                    }
                )
        return {
            "status": "ok",
            "action": "batch",
            "count": len(batch_results),
            "results": summary[:20],
        }

    return {
        "list_ips": handle_list_ips,
        "analyze_ip": handle_analyze_ip,
        "search_ips": handle_search_ips,
        "compare_ips": handle_compare_ips,
        "generate_report": handle_generate_report,
        "batch_analyze": handle_batch_analyze,
    }


# ---------------------------------------------------------------------------
# Generate-data handler (calls the IP fixture generator via cmd_generate)
# ---------------------------------------------------------------------------


def handle_generate_data(**kwargs: Any) -> dict[str, Any]:
    """Generate synthetic IP fixture data — wraps ``cmd_generate``."""
    from plugins.game_ip.cli.commands import cmd_generate

    count = kwargs.get("count", 5)
    genre = kwargs.get("genre", "")
    gen_args = str(count)
    if genre:
        gen_args += f" {genre}"
    cmd_generate(gen_args)
    return {
        "status": "ok",
        "action": "generate",
        "count": count,
        "genre": genre or "random",
    }


# ---------------------------------------------------------------------------
# Aggregator — merged into core's tool-handler dict at bootstrap.
# ---------------------------------------------------------------------------


def build_game_ip_handlers(
    *,
    verbose: bool = False,
    force_dry: bool | None = None,
    skill_registry: Any = None,
) -> dict[str, Any]:
    """Return the full game-IP tool-handler bundle.

    Merged into the generic dispatcher dict via
    ``GameIPDomain.register_tool_handlers`` (called from
    ``core/cli/tool_handlers.py:install_domain_tool_handlers``).

    ``force_dry=None`` (default) defers the dry-run decision to call
    time — each handler re-reads ``_get_readiness()`` when invoked.
    """
    handlers: dict[str, Any] = {}
    handlers.update(_build_analysis_handlers(verbose, force_dry, skill_registry))
    handlers["generate_data"] = handle_generate_data
    # Signal tools — delegated lazy-import handlers.
    for name, (mod, cls) in GAME_IP_DELEGATED_TOOLS.items():
        handlers[name] = _make_delegate_handler(mod, cls)
    return handlers
