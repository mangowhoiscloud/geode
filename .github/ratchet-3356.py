"""One-shot, pinned-source edits for PR #3356; executed in its owned CI checkout."""
from pathlib import Path
import hashlib
import re

EXPECTED = {
    'core/memory/fts_query.py': 'a05e4b4f4dbb5ca77f64359f0facc6e2ef0cac33',
    'scripts/check_architecture_performance.py': 'd3ba6f27f2e748a1b0b9d5df86cba4249dae1e88',
    'tests/core/memory/test_hermes_1c_fts5.py': 'b049f183b2f37c516f6178837ca9c94e68e4f607',
    'tests/scripts/test_check_architecture_performance.py': '73433c8291ac8ab9ead71e1f2d1f04f84323868a',
    '.github/workflows/ci.yml': '1d28b6213ed5d27fdaf962fc4f4ef0a49fad63bb',
    'CHANGELOG.md': '3a1e31afe03bc7511b2fb96682280579e6ea0c0b',
    '.agents/skills/geode-workflow/references/verification-gates.md': 'da25fedffe5ee70e60be1200307c58541ee246b8',
}
for name, expected in EXPECTED.items():
    data = Path(name).read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if actual != expected:
        raise RuntimeError(f'Stale source: {name}: {actual} != {expected}')


def replace(name: str, old: str, new: str) -> None:
    path = Path(name)
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f'Expected one exact anchor in {name}: {old[:80]!r}')
    path.write_text(text.replace(old, new))


fts = 'core/memory/fts_query.py'
replace(fts, 'import sqlite3\n', 'import sqlite3\nimport uuid\n')
replace(fts, '''    Runs a one-shot ``CREATE VIRTUAL TABLE ... USING fts5(... tokenize='trigram')``
    on a throwaway name and drops it. SQLite ≥ 3.34 has trigram baked
    in; older builds raise ``sqlite3.OperationalError``. Returns
''', '''    Create and drop a uniquely named virtual table in this connection's TEMP
    schema. Capability detection must not mutate the durable session schema,
    generate main-database WAL writes, or commit the caller's transaction.
    Do not cache across connections: available modules and authorizers can differ.
    SQLite ≥ 3.34 has trigram baked in; older builds raise
    ``sqlite3.OperationalError``. Returns
''')
replace(fts, '    probe_name = "_geode_trigram_probe"', '    probe_name = f"temp._geode_trigram_probe_{uuid.uuid4().hex}"')
replace(fts, '        # Best-effort cleanup; leaving the probe table behind is harmless.', '        # Only our unique TEMP object is eligible for cleanup; never a caller table.')

checker = 'scripts/check_architecture_performance.py'
replace(checker, 'import json\n', 'import json\nimport math\n')
replace(checker, '''    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise PerformanceBaselineError(f"{label} must be a positive number")
    return float(value)
''', '''    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PerformanceBaselineError(f"{label} must be a positive finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise PerformanceBaselineError(f"{label} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise PerformanceBaselineError(f"{label} must be a positive finite number")
    return number
''')
replace(checker, '    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:\n', '''    if (
        not isinstance(raw, dict)
        or type(raw.get("schema_version")) is not int
        or raw["schema_version"] != SCHEMA_VERSION
    ):
''')
replace(checker, '        value = measurements[name]\n', '''        try:
            value = _positive_number(measurements[name], label=name)
        except PerformanceBaselineError as exc:
            errors.append(str(exc))
            continue
''')
replace(checker, '\ndef _median_ms(', '''
def _validated_measurements(raw: object) -> dict[str, float]:
    """Reject malformed individual samples before a median can hide them."""
    if not isinstance(raw, dict) or not raw:
        raise PerformanceBaselineError("performance sample must be a non-empty object")
    result: dict[str, float] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise PerformanceBaselineError("performance metric names must be non-empty strings")
        result[name] = _positive_number(value, label=name)
    return result


def _median_ms(''')
replace(checker, 'async def _measure_async(bound: Any) -> dict[str, float]:', 'async def _measure_async(bound: Any, *, profile_first_turn: bool = False) -> dict[str, float]:')
replace(checker, '''    started = time.perf_counter()
    turn_result = await loop.arun("Return ok.")
    first_turn_ms = (time.perf_counter() - started) * 1000.0
''', '''    # Profiling runs only in a separate diagnostic child, never in scored samples.
    if profile_first_turn:
        import cProfile

        profile = cProfile.Profile()
        profile.enable()
    else:
        profile = None
    started = time.perf_counter()
    try:
        turn_result = await loop.arun("Return ok.")
    finally:
        first_turn_ms = (time.perf_counter() - started) * 1000.0
        if profile is not None:
            profile.disable()
            import pstats

            print("First-turn profile: diagnostic only, not acceptance", file=sys.stderr)
            pstats.Stats(profile, stream=sys.stderr).strip_dirs().sort_stats(
                "cumulative"
            ).print_stats(20)
''')
replace(checker, 'def _measure_probe() -> dict[str, float]:', 'def _measure_probe(*, profile_first_turn: bool = False) -> dict[str, float]:')
replace(checker, '    measurements.update(asyncio.run(_measure_async(_minimal_bound_plan())))', '''    measurements.update(
        asyncio.run(_measure_async(_minimal_bound_plan(), profile_first_turn=profile_first_turn))
    )''')
replace(checker, 'def collect_measurements(*, samples: int = 3) -> dict[str, float]:', '''def collect_measurements(
    *, samples: int = 3, diagnostic: bool = False
) -> dict[str, float]:''')
replace(checker, '                [sys.executable, str(Path(__file__).resolve()), "--probe"],', '''                [sys.executable, str(Path(__file__).resolve()), "--probe"]
                + (["--profile-first-turn"] if diagnostic else []),''')
replace(checker, '''            row = json.loads(completed.stdout)
            rows.append(row)
            print(
                f"performance sample {index + 1}/{samples}: {json.dumps(row, sort_keys=True)}",
                flush=True,
            )
''', '''            row = json.loads(completed.stdout)
            label = "diagnostic" if diagnostic else "performance"
            print(
                f"{label} sample {index + 1}/{samples}: {json.dumps(row, sort_keys=True)}",
                flush=True,
            )
            rows.append(_validated_measurements(row))
''')
replace(checker, '    for name in sorted(measurements):\n', '    for name in sorted(set(measurements) & set(baseline)):\n')
replace(checker, '    mode.add_argument("--check", action="store_true")\n', '''    mode.add_argument("--check", action="store_true")
    mode.add_argument("--diagnose", action="store_true", help="profile one unscored isolated probe")
    parser.add_argument("--profile-first-turn", action="store_true", help=argparse.SUPPRESS)
''')
replace(checker, '    if args.probe:\n', '''    if args.profile_first_turn and not args.probe:
        parser.error("--profile-first-turn requires internal --probe mode")
    if args.probe:
''')
replace(checker, '        print(json.dumps(_measure_probe(), sort_keys=True))', '        print(json.dumps(_measure_probe(profile_first_turn=args.profile_first_turn), sort_keys=True))')
replace(checker, '''    try:
        baseline = load_baseline(args.baseline)
''', '''    try:
        if args.diagnose:
            print("Diagnostic only: profiled values are not performance acceptance evidence")
            collect_measurements(samples=1, diagnostic=True)
            return 0
        baseline = load_baseline(args.baseline)
''')

with Path('tests/core/memory/test_hermes_1c_fts5.py').open('a') as out:
    out.write('''

@pytest.mark.parametrize("pending_write", [False, True])
def test_trigram_probe_preserves_main_schema_transaction_and_caller_tables(
    tmp_path: Path, pending_write: bool
) -> None:
    from core.memory.fts_query import has_trigram_support

    conn = sqlite3.connect(tmp_path / "probe.db")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE retained(value TEXT)")
        conn.execute("CREATE TABLE _geode_trigram_probe(value TEXT)")
        conn.execute("CREATE TEMP TABLE _geode_trigram_probe(value TEXT)")
        conn.commit()
        version = conn.execute("PRAGMA main.schema_version").fetchone()[0]
        schema = conn.execute("SELECT name, sql FROM main.sqlite_master ORDER BY name").fetchall()
        if pending_write:
            conn.execute("INSERT INTO retained VALUES ('pending')")
        for _ in range(4):
            assert has_trigram_support(conn) is True
        assert conn.in_transaction is pending_write
        assert conn.execute("PRAGMA main.schema_version").fetchone()[0] == version
        assert conn.execute(
            "SELECT name, sql FROM main.sqlite_master ORDER BY name"
        ).fetchall() == schema
        assert conn.execute(
            "SELECT name FROM sqlite_temp_master WHERE name LIKE '_geode_trigram_probe%'"
        ).fetchall() == [("_geode_trigram_probe",)]
        conn.rollback()
        assert conn.execute("SELECT * FROM retained").fetchall() == []
    finally:
        conn.close()


def test_trigram_probe_works_with_read_only_main(tmp_path: Path) -> None:
    from core.memory.fts_query import has_trigram_support

    path = tmp_path / "readonly.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE retained(value TEXT)")
    conn.close()
    readonly = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        assert has_trigram_support(readonly) is True
        assert readonly.execute("SELECT name FROM sqlite_temp_master").fetchall() == []
    finally:
        readonly.close()


def test_trigram_probe_does_not_cache_past_connection_authority_changes() -> None:
    from core.memory.fts_query import has_trigram_support

    def deny_virtual_table(action: int, *_args: object) -> int:
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_VTABLE else sqlite3.SQLITE_OK

    conn = sqlite3.connect(":memory:")
    try:
        assert has_trigram_support(conn) is True
        conn.set_authorizer(deny_virtual_table)
        assert has_trigram_support(conn) is False
        conn.set_authorizer(None)
        assert has_trigram_support(conn) is True
        assert conn.execute("SELECT name FROM sqlite_temp_master").fetchall() == []
    finally:
        conn.close()


def test_session_manager_reopen_does_not_rewrite_fts_capability_schema(tmp_path: Path) -> None:
    from core.memory.session_manager import SessionManager

    path = tmp_path / "sessions.db"
    versions = []
    for _ in range(3):
        manager = SessionManager(db_path=path)
        try:
            assert manager._has_trigram is True
            versions.append(manager._conn.execute("PRAGMA main.schema_version").fetchone()[0])
        finally:
            manager.close()
    assert len(set(versions)) == 1
''')

with Path('tests/scripts/test_check_architecture_performance.py').open('a') as out:
    out.write('''

@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 0, -1, True, "1", None])
@pytest.mark.parametrize("field", ["observed", "maximum"])
def test_baseline_rejects_non_finite_or_non_positive_values(
    tmp_path: Path, field: str, value: object
) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path)
    data = json.loads(path.read_text())
    data["metrics"]["probe_ms"][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(checker.PerformanceBaselineError, match="positive finite"):
        checker.load_baseline(path)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_baseline_requires_integer_schema_identity(tmp_path: Path, version: object) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path)
    data = json.loads(path.read_text())
    data["schema_version"] = version
    path.write_text(json.dumps(data))
    with pytest.raises(checker.PerformanceBaselineError, match="schema_version"):
        checker.load_baseline(path)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 0, -1, True])
def test_compare_rejects_invalid_measurements(value: float) -> None:
    baseline = {"probe_ms": {"unit": "ms", "observed": 1.0, "maximum": 2.0}}
    errors = checker.compare_measurements({"probe_ms": value}, baseline)
    assert errors == ["probe_ms must be a positive finite number"]


@pytest.mark.parametrize("row", [{"probe_ms": float("nan")}, {"probe_ms": -1}, {}, [], None])
def test_invalid_sample_cannot_be_hidden_by_a_passing_median(
    monkeypatch: pytest.MonkeyPatch, row: object, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path)
    samples = iter([{"probe_ms": 1.0}, row, {"probe_ms": 1.0}])

    def run_probe(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, json.dumps(next(samples)), "")

    monkeypatch.setattr(checker.subprocess, "run", run_probe)
    assert checker.main(["--check", "--baseline", str(path)]) == 1
    output = capsys.readouterr()
    assert "architecture performance OK" not in output.out
    assert "architecture performance check failed" in output.err


def test_check_reports_unexpected_metric_without_rendering_key_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path)

    def run_probe(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, '{"unexpected_ms": 1.0}', "")

    monkeypatch.setattr(checker.subprocess, "run", run_probe)
    assert checker.main(["--check", "--baseline", str(path)]) == 1
    output = capsys.readouterr()
    assert "missing metrics: probe_ms" in output.err
    assert "unexpected metrics: unexpected_ms" in output.err
    assert "architecture performance OK" not in output.out


@pytest.mark.parametrize("diagnostic", [False, True])
def test_profile_flag_is_only_used_for_unscored_diagnostics(
    monkeypatch: pytest.MonkeyPatch, diagnostic: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    commands: list[list[str]] = []

    def run_probe(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '{"first_turn_ms": 1.0}', "")

    monkeypatch.setattr(checker.subprocess, "run", run_probe)
    checker.collect_measurements(samples=1, diagnostic=diagnostic)
    assert ("--profile-first-turn" in commands[0]) is diagnostic
    assert capsys.readouterr().out.startswith("diagnostic" if diagnostic else "performance")


def test_diagnose_never_reports_acceptance_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[dict[str, object]] = []

    def collect(**kwargs: Any) -> dict[str, float]:
        seen.append(kwargs)
        return {"first_turn_ms": 9999.0}

    monkeypatch.setattr(checker, "collect_measurements", collect)
    assert checker.main(["--diagnose"]) == 0
    assert seen == [{"samples": 1, "diagnostic": True}]
    output = capsys.readouterr().out
    assert "Diagnostic only" in output
    assert "architecture performance OK" not in output
''')

replace('.github/workflows/ci.yml', '''      - name: Architecture performance baseline
        if: needs.changes.outputs.code == 'true'
        run: uv run python scripts/check_architecture_performance.py --check
''', '''      - name: Architecture performance contracts
        if: needs.changes.outputs.code == 'true'
        run: |
          uv run pytest -q tests/core/memory/test_hermes_1c_fts5.py \\
            tests/scripts/test_check_architecture_performance.py
      - name: Architecture performance baseline
        id: architecture_performance
        if: needs.changes.outputs.code == 'true'
        run: uv run python scripts/check_architecture_performance.py --check
      - name: Architecture performance failure profile
        if: failure() && steps.architecture_performance.outcome == 'failure'
        run: uv run python scripts/check_architecture_performance.py --diagnose
''')

replace('.agents/skills/geode-workflow/references/verification-gates.md', '## Full Suite\n', '''## Performance Ratchet

The existing `scripts/check_architecture_performance.py --check` retains its
three isolated samples, raw measurements, median per metric, and independent
limits in `docs/architecture/performance-baseline.json`. Invalid individual
samples fail before aggregation; NaN, infinity, non-positive values and metric
set drift cannot become a passing measurement.

CI runs the mirrored FTS and checker contract tests before performance
acceptance. A failed performance step triggers one separate `--diagnose` probe
with bounded, redacted first-turn profile output. This is unscored evidence,
not a warm-up, substitute measurement, retry-to-green, or permission to loosen
the baseline. The original failed step still fails Test and Gate.

SQLite capability probes must not write the durable session schema, commit
caller work, or cache another connection's authority. Keep the real
checkpoint/timeline writes and durability settings in the measured path.
The FTS regression checks these boundaries without a wall-clock assertion.

## Full Suite
''')

path = Path('CHANGELOG.md')
text = path.read_text()
heading = re.search(r'^## \[Unreleased\][^\n]*\n', text, re.M)
if heading is None:
    raise RuntimeError('Unreleased heading missing')
end = re.search(r'^## ', text[heading.end():], re.M)
limit = len(text) if end is None else heading.end() + end.start()
anchor = text.find('### Fixed\n\n', heading.end(), limit)
if anchor < 0:
    raise RuntimeError('Unreleased Fixed section missing')
point = anchor + len('### Fixed\n\n')
entry = '''- Keep SQLite trigram capability probes in connection-local TEMP tables instead
  of repeatedly creating and dropping FTS shadow tables in the durable session
  database. Preserve caller transactions, existing tables, connection-specific
  capability checks, and checkpoint/timeline durability.
- Harden the architecture performance ratchet against non-finite, non-positive,
  malformed, or mismatched measurements before aggregation. Run deterministic
  FTS/checker contracts before the unchanged three-sample limits, and retain a
  separate bounded first-turn profile after failure without replacing the
  original failed result or relaxing the baseline.

'''
path.write_text(text[:point] + entry + text[point:])
print('Applied pinned FTS, performance, regression, CI, and documentation edits')
