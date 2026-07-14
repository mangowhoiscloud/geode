"""Gateway machine-instance identity — one messaging thread, one session.

v0.99.329: the gateway derives a stable checkpoint session id from the
binding session_key so a thread's turns share ONE checkpoint chain
(docs/architecture/session-state-machine.md § Machine instance).
"""

from __future__ import annotations

from core.cli.typer_serve import _gateway_checkpoint_session_id


def test_derivation_is_stable():
    key = "slack:C123:U9:thread-1"
    assert _gateway_checkpoint_session_id(key) == _gateway_checkpoint_session_id(key)


def test_distinct_threads_get_distinct_instances():
    base = _gateway_checkpoint_session_id("slack:C123:U9:thread-1")
    assert base != _gateway_checkpoint_session_id("slack:C123:U9:thread-2")
    assert base != _gateway_checkpoint_session_id("telegram:C123:U9:thread-1")


def test_id_shape_pins_sha256():
    import hashlib

    key = "slack:C1:U1:t1"
    sid = _gateway_checkpoint_session_id(key)
    assert sid.startswith("s-gw-")
    assert sid == "s-gw-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
