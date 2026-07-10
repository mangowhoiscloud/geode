# Crucible class-prior store

One JSON file per mutation class (`crucible.class-prior.v1`), each carrying
Beta posteriors on the class's fix and regression rates plus the task-pack
SHA-256 the evidence was measured against. `plugins.crucible.calibration`
reads these when deriving contract parameters; the
`python -m plugins.crucible priors-update` writer folds each campaign's
measured flips back in, so the priors track reality instead of rotting.

Files here are git-tracked deliberately: a prior is promotion-relevant
evidence, and an ignored path would silently break the writer
(writer-destination-tracked rule). Do not hand-edit — the derivation block
in every contract records which prior state produced its numbers.
