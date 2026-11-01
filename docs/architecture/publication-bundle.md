# GEODE publication bundle

GEODE is moving its website out of this repository. The downstream site
repository will render the GEODE docs and the self-improving hub from one
archive that GEODE produces: the publication bundle. GEODE owns the raw inputs
and the constants that describe them. The consumer owns templates, generated
pages, the Inspect viewer and hosting.

Producer: [`scripts/build_publication_bundle.py`](../../scripts/build_publication_bundle.py).
Tests: [`tests/scripts/test_build_publication_bundle.py`](../../tests/scripts/test_build_publication_bundle.py).
Upload and CI wiring are not part of this step.

## Build

```bash
uv run python scripts/build_publication_bundle.py --out DIR          # write the bundle
uv run python scripts/build_publication_bundle.py --check            # build twice, compare bytes
```

`--out` writes `geode-publication-<sha256>.tar.gz` and a sidecar
`manifest.json`. `<sha256>` is the digest of the archive bytes. The same
manifest bytes are also the first archive member. The CLI refuses to build when
a bundled file is untracked or differs from `HEAD`, so `source_commit`
identifies the bundled bytes.

## Determinism

- Entries are regular files in sorted path order, after `manifest.json`.
- Every tar header has mode `0644`, uid/gid `0`, empty user and group names, and
  mtime equal to `source_date_epoch`. The tar format is PAX.
- The gzip stream uses level 9 with no file name and a zero timestamp.
- `source_date_epoch` is `SOURCE_DATE_EPOCH` when set, otherwise the `HEAD`
  commit time.
- The manifest is JSON with sorted keys, two-space indentation and a trailing
  newline.

Archive bytes are reproducible for the same inputs and the same zlib build.
`tree_sha256` identifies the content regardless of compressor, so consumers
should compare content with it rather than with the archive name.

## Layout (`layout_version` 1)

| Bundle path | Source | Required |
|---|---|---|
| `changelog/CHANGELOG.md` | `CHANGELOG.md` | yes |
| `eval/index.json` | `docs/eval/index.json` | yes |
| `architecture/architecture-baseline.json` | output of `scripts/architecture_baseline.py` (currently `site/src/data/geode/`) | yes |
| `hub/petri-bundle/logs/{*.eval,listing.json}` | `docs/self-improving/petri-bundle/logs/` | no |
| `hub/petri-bundle/seeds/**` | `docs/self-improving/petri-bundle/seeds/` | no |
| `hub/petri-bundle/literature/*.json` (not `listing.json`) | `docs/self-improving/petri-bundle/literature/` | no |
| `hub/seed-generation/bundle/logs/{*.eval,listing.json}` | `docs/self-improving/seed-generation/bundle/logs/` | no |
| `hub/autoresearch/baseline/transcripts.json` | `docs/self-improving/autoresearch/baseline/` | no |
| `hub/run-*.md` | `docs/self-improving/run-*.md` | no |
| `hub/state/{mutations.jsonl,results.tsv,results.jsonl,baseline_archive.jsonl,policies/*.json}` | `evolve/scaffold_search/state/` | no |
| `hub/audits/eval-logs/{MANIFEST.jsonl,*.summary.yaml}` | `docs/audits/eval-logs/` | no |
| `hub/seed-candidates/seeds_gen*/**/*.md` | `evals/petri/seeds_gen*/` (literature listing input) | no |

Files ending in `.html`, `.htm` or `.template`, anything under an `assets/`
directory, and dot files are never bundled. Symlinked inputs fail the build. A
missing required input fails the build. A missing optional pattern is listed in
`optional_absent`.

The authoritative layout is `BUNDLE_SOURCES` in the producer. The manifest
repeats it as `sources`.

## Manifest (`schema_version` 1)

| Field | Meaning |
|---|---|
| `schema` | Always `geode-publication-bundle` |
| `schema_version` | Manifest schema version |
| `layout_version` | In-bundle path layout version |
| `geode_version` | `[project].version` from `pyproject.toml` |
| `source_commit` | `HEAD` commit the inputs were read from |
| `source_date_epoch`, `generated_at` | Source date, as an integer and as UTC ISO 8601 |
| `repository_url` | `core.paths.GEODE_REPO_URL` |
| `sources[]` | `{bundle_dir, source_dir, patterns, required}` |
| `optional_absent[]` | Optional `source_dir/pattern` entries that matched nothing |
| `hub_constants` | Values the hub generator previously mirrored by hand (below) |
| `file_count`, `total_bytes` | Totals over `files[]` |
| `files[]` | `{path, bytes, sha256}` in sorted path order, excluding `manifest.json` |
| `tree_sha256` | SHA-256 of the lines `"<sha256> <bytes> <path>\n"`, one per file in `files[]` order |

`hub_constants` is computed by importing GEODE modules, never from copied
literals:

| Key | GEODE source |
|---|---|
| `results_tsv_header` | `evolve.scaffold_search.ledger.RESULTS_TSV_HEADER` |
| `policy_kind_to_path` | `evolve.scaffold_search.loop.mutate.policies._KIND_TO_PATH`, relative to the state dir (`hub/state/`) |
| `statistical_power` | `DEFAULT_TARGET_EFFECT_SIZE`, `DEFAULT_ALPHA`, `DEFAULT_POWER` in `evolve.scaffold_search.loop.observe.statistical_power` |
| `judge_dimensions` | Names in the default set resolved by `evals.petri.judge_dims.resolve_dim_set` |
| `promote_policies` | `evolve.scaffold_search.gate._VALID_PROMOTE_POLICIES` |
| `baseline_registry_kind` | `evolve.scaffold_search.ledger._BASELINE_REGISTRY_KIND` |

The heatmap abbreviations for judge dimensions and the campaign progress-log
regex have no GEODE source. The abbreviations are consumer presentation. The
log line format is written by f-strings in `evolve/scaffold_search/campaign.py`.

## Versioning

- Bump `layout_version` when a bundle path moves or a source group changes its
  destination.
- Bump `schema_version` when a manifest field is removed or changes meaning.
  Adding a field or a `hub_constants` key does not need a bump. Consumers must
  ignore unknown fields.
- Consumers must reject a bundle whose `schema` is not `geode-publication-bundle`
  or whose versions they do not support.
- Consumers must verify every `files[]` digest and `tree_sha256` before use.

## Not yet in the bundle

The hub generator also reads runtime-only inputs: `~/.geode/self-improving/`
(`baseline.json`, `campaign-progress.log` and the gen-0 snapshot) and the
gitignored crucible ledgers under `artifacts/eval/runs/crucible/campaigns/`.
Pages built only from the bundle show their absent states until GEODE publishes
committed snapshots of those inputs.
