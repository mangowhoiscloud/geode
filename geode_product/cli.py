"""GEODE product-shell CLI composition."""

from core.cli import build_app
from core.cli.commands.config import build_config_app
from core.cli.routing import CommandSpec, RunLocation

from geode_product.config_cli import register_config_commands
from geode_product.petri_audit.cli_agreement import audit_agreement_app
from geode_product.petri_audit.cli_audit import audit, petri_archive
from geode_product.seed_generation.cli import audit_seeds_app
from geode_product.self_improving.cli_commands import (
    register_commands as register_self_improving_commands,
)
from geode_product.self_improving.config import load_self_improving_loop_config
from geode_product.wiring import serve

_self_improving_config = load_self_improving_loop_config()
QUOTA_THRESHOLDS = (
    _self_improving_config.warn_threshold,
    _self_improving_config.abort_threshold,
)

PRODUCT_COMMAND_SPECS = (
    CommandSpec(
        name="/audit",
        location=RunLocation.THIN,
        description="Petri × GEODE alignment audit",
        handler_path="geode_product.petri_audit.cli_audit:cmd_audit_slash",
    ),
    CommandSpec(
        name="/audit-seeds",
        location=RunLocation.THIN,
        description="Generate and score candidate evaluation seeds",
        handler_path="geode_product.seed_generation.cli:cmd_audit_seeds_slash",
    ),
    CommandSpec(
        name="/petri",
        location=RunLocation.THIN,
        description="Show or switch Petri role bindings",
        handler_path="geode_product.petri_audit.cli:cmd_petri",
    ),
    CommandSpec(
        name="/self-improving",
        aliases=("/sil",),
        location=RunLocation.THIN,
        description="Self-improving loop status, execution, and configuration",
        handler_path="geode_product.self_improving.cli_commands:cmd_self_improving",
    ),
    CommandSpec(
        name="/recall",
        location=RunLocation.THIN,
        description="Memory-recall pool — list/show/save persistent memory entries",
        handler_path="geode_product.self_improving.recall_cli:cmd_recall",
    ),
)
config_app = build_config_app()
register_config_commands(config_app)

app = build_app(
    serve_command=serve,
    config_command_app=config_app,
    command_specs=PRODUCT_COMMAND_SPECS,
    command_registrars=(register_self_improving_commands,),
    quota_thresholds=QUOTA_THRESHOLDS,
)
app.command()(audit)
app.command(name="petri-archive")(petri_archive)
app.add_typer(audit_seeds_app, name="audit-seeds")
app.add_typer(audit_agreement_app, name="audit-agreement")

__all__ = ["app"]
