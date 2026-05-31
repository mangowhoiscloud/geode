"""autoresearch — GEODE self-improving loop DATA + program SoT.

The loop *CODE* moved to :mod:`core.self_improving` (umbrella package,
PR-SELF-IMPROVING-UMBRELLA 2026-05-31). What stays here is the runtime
*DATA* and the program SoT the running campaign + gitignore guards depend
on, deliberately left in place:

* ``autoresearch/state/`` — baseline.json, mutations.jsonl, policies/,
  seed-pools, the campaign progress log (the canonical state directory the
  running campaign writes to; ``core.self_improving.train`` /
  ``core.self_improving.campaign`` resolve ``REPO_ROOT/"autoresearch"/"state"``).
* ``autoresearch/program.md`` — the program SoT the mutator reads.
* ``autoresearch/README.md`` — the loop overview.

This ``__init__`` is deliberately side-effect-free; nothing imports the
package for behaviour. To run the loop, invoke
``python -m core.self_improving.train`` (single audit) or
``python -m core.self_improving.campaign`` (the campaign driver).
"""
