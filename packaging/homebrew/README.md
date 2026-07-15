# Homebrew/core packaging

GEODE supports Homebrew only through the upstream `homebrew/core` formula
named `geode-agent`. The former custom distribution repository is deleted and
must not be recreated. A namespace-qualified install command is not a supported
fallback.

`brew install geode-agent` is not an active public install path until the
formula is accepted into Homebrew/core, appears in the official formula API,
and passes an unqualified install on a clean machine. Until then, advertise the
PyPI/uv commands only.

## Files

- `geode-agent.rb.in` is the core-formula template.
- `../../scripts/render_homebrew_formula.py` binds the template to an immutable
  GitHub release sdist, its SHA-256, Homebrew's current Python formula, and
  pinned Python resources.
- The audited `0.99.331` first-submission candidate is preserved in the
  [`mangowhoiscloud/homebrew-core` fork](https://github.com/mangowhoiscloud/homebrew-core/tree/geode-agent-0.99.331/Formula/g).

## Candidate update

Start only after GitHub Release and PyPI agree on the exact version. Use the
previous candidate as the resource baseline:

```bash
python scripts/render_homebrew_formula.py \
  --version X.Y.Z \
  --sdist-url "https://github.com/mangowhoiscloud/geode/releases/download/vX.Y.Z/geode_agent-X.Y.Z.tar.gz" \
  --sdist-sha256 SDIST_SHA256 \
  --resources-from-formula /path/to/homebrew-core/Formula/g/geode-agent.rb \
  --output /path/to/homebrew-core/Formula/g/geode-agent.rb
```

Refresh the Python resources in a dedicated Homebrew/core development checkout,
then require every local gate:

```bash
brew update-python-resources --version X.Y.Z geode-agent
brew audit --strict --new --online geode-agent
brew style Formula/g/geode-agent.rb
brew install --build-from-source geode-agent
brew test geode-agent
geode version
brew uninstall geode-agent
```

The source URL must remain a `releases/download` asset, never a tag-generated
archive. Keep the Ruby class `GeodeAgent`, install both `geode` and `geode-mcp`,
and pin every Python resource by canonical URL and SHA-256.

## Upstream admission

Before opening a first-submission PR, re-read Homebrew's current
[acceptable formulae](https://docs.brew.sh/Acceptable-Formulae),
[submission workflow](https://docs.brew.sh/Adding-Software-to-Homebrew), and
[Python formula guidance](https://docs.brew.sh/Python-for-Formula-Authors).
Do not submit while GEODE is marked beta or misses upstream usage/notability
requirements. Keep the candidate in the fork instead.

After Homebrew/core accepts the formula, verify the official surface before
adding Homebrew to public installation UI:

```bash
curl -fsS https://formulae.brew.sh/api/formula/geode-agent.json
brew update
brew install geode-agent
geode version
brew test geode-agent
brew uninstall geode-agent
```
