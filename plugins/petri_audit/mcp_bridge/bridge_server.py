"""Compatibility launcher for the Petri MCP bridge."""

if __name__ == "__main__":
    from geode_product.petri_audit.mcp_bridge.bridge_server import main

    main()
else:
    from plugins._compat import canonical_module as _canonical_module

    _canonical_module(__name__, "geode_product.petri_audit.mcp_bridge.bridge_server")
