"""Game IP plugin — system prompt static prefix composer.

Step 3 (domain-free-core) extracted the IP-specific portion of
``core.agent.system_prompt.build_system_prompt`` into this module so
``core/agent/system_prompt.py`` no longer reaches into
``plugins.game_ip.fixtures`` / ``plugins.game_ip.cli.ip_names``.

The composer formats ``ROUTER_SYSTEM`` (which contains ``{ip_count}``
and ``{ip_examples}`` placeholders) using game-IP fixture data and
returns the rendered prefix. ``GameIPDomain.compose_static_prefix``
delegates here.
"""

from __future__ import annotations

import logging

from core.llm.prompts import ROUTER_SYSTEM

log = logging.getLogger(__name__)

# Well-known IPs to surface as examples (recognizable across languages)
_NOTABLE_IPS = {
    "berserk",
    "cowboy bebop",
    "ghost in shell",
    "hollow knight",
    "disco elysium",
    "hades",
    "celeste",
    "cult of the lamb",
    "dead cells",
    "slay the spire",
    "vampire survivors",
    "factorio",
    "stardew valley",
    "cuphead",
    "balatro",
    "rimworld",
}


def compose_static_prefix(model: str = "") -> str:
    """Render the game-IP-flavored static system prompt prefix.

    Substitutes ``{ip_count}`` and ``{ip_examples}`` in ``ROUTER_SYSTEM``
    using the plugin's fixture map. ``model`` is currently unused at the
    static-prefix level (model card lives in the dynamic section), but
    the parameter is part of the DomainPort v2 contract so future
    domains can vary the prefix per model if needed.
    """
    from plugins.game_ip.cli.ip_names import get_ip_name_map
    from plugins.game_ip.fixtures import FIXTURE_MAP, load_fixture

    name_map = get_ip_name_map()
    ip_count = len(name_map)

    # Prefer notable IPs as examples, then fill with others
    examples: list[str] = []
    for fk in _NOTABLE_IPS:
        if fk in FIXTURE_MAP:
            try:
                canonical = load_fixture(fk)["ip_info"]["ip_name"]
                examples.append(canonical)
            except Exception:
                examples.append(fk.title())

    return ROUTER_SYSTEM.format(
        ip_count=ip_count,
        ip_examples=", ".join(sorted(examples)),
    )
