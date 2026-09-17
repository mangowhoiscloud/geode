"""Upload verified blobs and print a manifest; never create trees or move refs."""
from __future__ import annotations
import base64
import json
import os
import subprocess
import urllib.request
from pathlib import Path

REPO = 'mangowhoiscloud/geode'
BRANCH = 'fix/architecture-performance-guards-20260917'
EXPECTED = os.environ['EXPECTED_HEAD']
ALLOWED = {
    'core/memory/fts_query.py', 'scripts/check_architecture_performance.py',
    'tests/core/memory/test_hermes_1c_fts5.py', 'tests/scripts/test_check_architecture_performance.py',
    '.github/workflows/ci.yml', '.agents/skills/geode-workflow/references/verification-gates.md',
    'CHANGELOG.md', 'AGENTS.md', 'docs/architecture/extensibility-roadmap.md',
    'site/src/data/geode/architecture-baseline.json', 'site/src/data/geode/changelog.ts',
    'site/src/data/geode/sot.ts', 'site/public/llms.txt', 'site/public/llms-full.txt',
    '.github/ratchet-3356.py', '.github/publish-ratchet-3356.py',
    '.github/workflows/architecture-performance-diagnostic.yml',
}

def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args])

def api(path: str, payload: object | None = None) -> dict:
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPO}/{path}',
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {os.environ["GH_TOKEN"]}',
                 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'},
        method='GET' if payload is None else 'POST')
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)

if git('rev-parse', 'HEAD').decode().strip() != EXPECTED:
    raise RuntimeError('Checkout moved')
if api(f'git/ref/heads/{BRANCH}')['object']['sha'] != EXPECTED:
    raise RuntimeError('Remote topic branch moved; no candidate publication')
if git('diff', '--name-only'):
    raise RuntimeError('Unstaged changes present')
changed = git('diff', '--cached', '--name-only', '-z').decode().strip('\0').split('\0')
if not changed or '' in changed or set(changed) - ALLOWED:
    raise RuntimeError(f'Unexpected staged paths: {changed}')
if git('diff', '--cached', '--name-only', '--', 'docs/architecture/performance-baseline.json'):
    raise RuntimeError('Performance baseline must remain unchanged')
entries = []
for path in changed:
    if not Path(path).exists():
        entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None})
        continue
    data = git('show', f':{path}')
    blob = api('git/blobs', {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
    expected_blob = subprocess.check_output(['git', 'hash-object', '--stdin'], input=data).decode().strip()
    if blob['sha'] != expected_blob:
        raise RuntimeError(f'Uploaded bytes differ: {path}')
    mode = git('ls-files', '--stage', '--', path).decode().split()[0]
    entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': blob['sha']})
# The runner does not have workflow-tree publication authority. Keep that write
# in the authorized connector; emit only verified object IDs and the exact tree.
print('VERIFIED_CANDIDATE_MANIFEST')
print(json.dumps({'parent': EXPECTED,
                  'base_tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
                  'expected_tree': git('write-tree').decode().strip(),
                  'entries': entries, 'ref_updated': False}, ensure_ascii=False, indent=2))
