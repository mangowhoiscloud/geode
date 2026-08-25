# Crucible package map

Crucible is the promotion layer above executable assays. Its package tree
follows the runtime flow while keeping shared evidence contracts at the root:

```text
evolve/crucible/
├── admission/       # curate -> power/runtime fit -> prepare
├── search/          # propose -> preflight -> evaluate -> decide -> record
│   └── producers/   # candidate producer protocols
├── assays/          # trusted tau2 execution, receipts, verifiers
│   └── verifiers/
├── attestation/     # promotion bundle and one-shot sealed evaluation
├── contract.py      # experiment identity and validation
├── evidence.py      # immutable assay-neutral evidence
├── promotion.py     # pure KEEP / REJECT / INVALID decision
├── artifacts.py     # shared durable file operations
└── cli.py           # operational composition root
```

`prepare.py`, `supervisor.py`, and `tau2_geode_agent.py` at the package root
are v1.0.x compatibility facades. Persisted provenance continues to use
`evolve.crucible.prepare` and `evolve.crucible.supervisor`.

The runtime admission path is a directed evidence loop rather than a shared
utility layer:

```text
regime ─┬─> budget ─> forecast
        └─> assays/receipt
evidence + receipt + budget ─> pilot ─> next admission
```
