"""GEODE product-shell CLI composition."""

from core.cli import build_app
from core.cli.commands.config import build_config_app

from geode_product.config_cli import register_config_commands
from geode_product.petri_audit.cli_agreement import audit_agreement_app
from geode_product.petri_audit.cli_audit import audit, petri_archive
from geode_product.seed_generation.cli import audit_seeds_app
from geode_product.self_improving.cli_commands import (
    register_commands as register_self_improving_commands,
)
from geode_product.self_improving.config import load_self_improving_loop_config
from geode_product.slash_commands import PRODUCT_COMMAND_SPECS
from geode_product.wiring import serve

_self_improving_config = load_self_improving_loop_config()
QUOTA_THRESHOLDS = (
    _self_improving_config.warn_threshold,
    _self_improving_config.abort_threshold,
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
