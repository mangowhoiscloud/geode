"""GEODE plugin namespace — domain-specific extensions outside the core scaffold.

Plugins live alongside `core/` rather than under it so the core scaffold
(general-purpose autonomous agent runtime) can evolve independently from
domain-specific code (game IP scoring, future research domains, etc.).

Each plugin is registered through ``core.domains.loader._DOMAIN_REGISTRY``
which maps a domain name to the importable adapter class.

Current plugins:
- ``plugins.game_ip`` — Game IP scoring domain (fixtures: Berserk, Cowboy
  Bebop, Ghost in the Shell). Originally lived at ``core/domains/game_ip/``;
  relocated in v0.64.0 per the plugin separation cycle.
"""
