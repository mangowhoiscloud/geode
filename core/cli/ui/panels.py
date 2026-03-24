"""Rich panel rendering for each pipeline step."""

from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from core import __version__
from core.state import AnalysisResult, EvaluatorResult, PSMResult, SynthesisResult
from core.cli.ui.console import console


def header_panel(ip_name: str, pipeline_mode: str, model: str) -> None:
    content = Text()
    content.append("  Analyzing: ", style="label")
    content.append(f"{ip_name}\n", style="value")
    content.append("  Pipeline: ", style="label")
    content.append(f"{pipeline_mode}", style="value")
    content.append(" | Model: ", style="label")
    content.append(model, style="value")
    console.print(
        Panel(
            content,
            title=f"[header]GEODE v{__version__} — Autonomous Execution Harness[/header]",
            border_style="cyan",
        )
    )
    console.print()


def gather_panel(
    ip_info: dict[str, Any],
    monolake: dict[str, Any],
    signals: dict[str, Any],
) -> None:
    console.print("[step]▸ [GATHER][/step] Loading IP data from MonoLake...")
    tree = Tree("", guide_style="dim")
    tree.add(
        f"[label]IP:[/label] {ip_info['ip_name']} "
        f"({ip_info['media_type']}, {ip_info['release_year']}, {ip_info['studio']})"
    )
    active = monolake["active_game_count"]
    active_str = "no active game" if active == 0 else f"{active} active"
    tree.add(
        f"[label]MonoLake:[/label] DAU={monolake['dau_current']}, "
        f"Revenue=${monolake['revenue_ltm']:,} ({active_str})"
    )

    yt = signals.get("youtube_views", 0)
    rd = signals.get("reddit_subscribers", 0)
    fa = signals.get("fan_art_yoy_pct", 0)
    yt_str = f"{yt / 1_000_000:.0f}M" if yt >= 1_000_000 else f"{yt:,}"
    rd_str = f"{rd / 1000:.0f}K" if rd >= 1000 else f"{rd:,}"
    tree.add(f"[label]Signals:[/label] YouTube {yt_str} | Reddit {rd_str} | FanArt {fa:+.0f}% YoY")
    console.print(tree)
    console.print()


def analyst_panel(analyses: list[AnalysisResult]) -> None:
    console.print("[step]▸ [ANALYZE][/step] Running 4 Analysts (Clean Context)...")
    table = Table(show_header=True, header_style="bold", border_style="dim")
    table.add_column("Analyst", style="label", width=14)
    table.add_column("Score", justify="center", width=7)
    table.add_column("Key Finding", width=40)

    for a in sorted(analyses, key=lambda x: x.analyst_type):
        score_style = "bold green" if a.score >= 4.0 else "yellow" if a.score >= 3.0 else "red"
        table.add_row(
            a.analyst_type.capitalize(),
            f"[{score_style}]{a.score:.1f}[/{score_style}]",
            a.key_finding,
        )
    console.print(table)
    console.print()


def evaluator_panel(evaluations: dict[str, EvaluatorResult]) -> None:
    console.print("[step]▸ [EVALUATE][/step] 14-Axis Rubric Scoring...")
    labels = {
        "quality_judge": "Quality",
        "hidden_value": "Hidden",
        "community_momentum": "Momentum",
    }
    table = Table(show_header=True, header_style="bold", border_style="dim")
    table.add_column("Evaluator", style="label", width=14)
    table.add_column("Score", justify="center", width=9)
    table.add_column("Rationale", width=40)

    for key, ev in sorted(evaluations.items()):
        label = labels.get(key, key.replace("_", " ").title())
        score = ev.composite_score
        score_style = "bold green" if score >= 80 else "yellow" if score >= 60 else "red"
        # Truncate rationale to first sentence for table readability
        rationale = ev.rationale.split(".")[0] + "." if ev.rationale else ""
        table.add_row(
            label,
            f"[{score_style}]{score:.0f}/100[/{score_style}]",
            rationale,
        )
    console.print(table)
    console.print()


def score_panel(
    psm: PSMResult,
    final_score: float,
    subscores: dict[str, float],
    confidence: float = 0.0,
) -> None:
    console.print("[step]▸ [SCORE][/step] PSM + Final Calculation")

    z_mark = "[success]\u2713[/success]" if psm.z_value > 1.645 else "[error]\u2717[/error]"
    g_mark = "[success]\u2713[/success]" if psm.rosenbaum_gamma <= 2.0 else "[error]\u2717[/error]"
    console.print(
        f"  [label]PSM:[/label] ATT={psm.att_pct:+.1f}% | "
        f"Z={psm.z_value:.2f} ({z_mark}>1.645) | "
        f"\u0393={psm.rosenbaum_gamma:.1f} ({g_mark}\u22642.0)"
    )
    console.print(
        "  [muted]ATT=IP 노출 효과, Z>1.645=95% 유의, \u0393\u22642.0=인과 강건성 확인[/muted]"
    )

    filled = int(final_score / 100 * 40)
    bar = "[yellow]" + "\u2588" * filled + "[/yellow][dim]" + "\u2591" * (40 - filled) + "[/dim]"
    console.print(f"  [label]Final Score:[/label] {bar} {final_score:.1f}/100")
    if confidence > 0:
        conf_style = "success" if confidence >= 80 else "warning"
        if confidence < 60:
            conf_style = "error"
        console.print(
            f"  [label]Confidence:[/label] [{conf_style}]{confidence:.1f}%[/{conf_style}]"
        )
    console.print()


def verify_panel(guardrails_pass: bool, biasbuster_pass: bool) -> None:
    g_mark = "[success]\u2713[/success]" if guardrails_pass else "[error]\u2717[/error]"
    b_mark = "[success]\u2713[/success]" if biasbuster_pass else "[error]\u2717[/error]"
    console.print(f"[step]▸ [VERIFY][/step] Guardrails G1-G4 {g_mark} | BiasBuster {b_mark}")
    console.print()


def result_panel(
    tier: str,
    final_score: float,
    synthesis: SynthesisResult,
) -> None:
    tier_info = {
        "S": ("tier_s", "\u226580"),
        "A": ("tier_a", "60-79"),
        "B": ("tier_b", "40-59"),
        "C": ("tier_c", "<40"),
    }
    tier_style, tier_range = tier_info.get(tier, ("bold", "?"))

    content = Text()
    content.append("  ", style="default")
    content.append(f" {tier} ", style=tier_style)
    content.append(
        f"  |  {final_score:.1f} pts ({tier_range})  |  {synthesis.undervaluation_cause}\n\n"
    )
    content.append(f"  {synthesis.value_narrative}\n\n")
    content.append("  Target Segment: ", style="label")
    content.append(f"{synthesis.target_segment}\n")
    content.append("  Recommended Action: ", style="label")

    action_display = synthesis.action_type.replace("_", " ").title()
    content.append(action_display)

    console.print(
        Panel(
            content,
            title="[bold]RESULT[/bold]",
            border_style="green",
        )
    )
