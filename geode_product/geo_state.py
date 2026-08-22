"""Typed evidence-state projection for the product ``/geo`` surface."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from html import escape
from pathlib import Path
from typing import Any

from core.memory.sqlite_store import short_sqlite_connection


class GeoPhase(StrEnum):
    PREFLIGHT = "preflight"
    OFFLINE_MEASURE = "offline_measure"
    LIVE_OBSERVE = "live_observe"
    EXPERIMENT = "experiment"
    COMPLETE = "complete"


class GeoStage(StrEnum):
    FETCH = "F"
    RETRIEVAL = "R"
    CITATION = "C"
    PLACEMENT = "P"
    ABSORPTION = "A"
    QUALITY = "Q"
    OUTCOME = "O"


class MeasurementStatus(StrEnum):
    NOT_MEASURED = "not_measured"
    PARTIAL = "partial"
    MEASURED = "measured"


@dataclass(frozen=True, slots=True)
class GeoEvidence:
    stage: GeoStage
    phase: GeoPhase
    status: MeasurementStatus
    numerator: int | None
    denominator: int | None
    finding: str
    evidence: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Any) -> GeoEvidence:
        required = {
            "stage",
            "phase",
            "status",
            "numerator",
            "denominator",
            "finding",
            "evidence",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError(f"GEO evidence requires exactly {sorted(required)}")
        stage = GeoStage(str(raw["stage"]))
        phase = GeoPhase(str(raw["phase"]))
        status = MeasurementStatus(str(raw["status"]))
        numerator = raw["numerator"]
        denominator = raw["denominator"]
        finding = str(raw["finding"]).strip()
        locators = raw["evidence"]
        if phase is GeoPhase.COMPLETE:
            raise ValueError("measurements must belong to an executable GEO phase")
        if not finding or len(finding) > 2000:
            raise ValueError("GEO finding must contain 1-2000 characters")
        if not isinstance(locators, list) or len(locators) > 24:
            raise ValueError("GEO evidence must be a list of at most 24 locators")
        evidence = tuple(str(item).strip() for item in locators)
        if any(not item or len(item) > 1000 for item in evidence):
            raise ValueError("GEO evidence locators must contain 1-1000 characters")
        if len(evidence) != len(set(evidence)):
            raise ValueError("GEO evidence locators must be unique")
        if status is MeasurementStatus.NOT_MEASURED:
            if numerator is not None or denominator is not None:
                raise ValueError("not_measured must preserve a null numerator and denominator")
        else:
            if type(numerator) is not int or type(denominator) is not int:
                raise ValueError(
                    "partial/measured stages require integer numerator and denominator"
                )
            if denominator <= 0 or not 0 <= numerator <= denominator or not evidence:
                raise ValueError(
                    "measured GEO evidence requires 0<=numerator<=denominator and locators"
                )
        return cls(stage, phase, status, numerator, denominator, finding, evidence)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        payload["phase"] = self.phase.value
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True, slots=True)
class GeoRun:
    session_id: str
    run_id: str
    subject: str
    phase: GeoPhase
    measurements: dict[str, GeoEvidence]
    config: dict[str, Any] = field(default_factory=dict)
    revision: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def missing_stages(self) -> tuple[str, ...]:
        return tuple(stage.value for stage in GeoStage if stage.value not in self.measurements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "subject": self.subject,
            "phase": self.phase.value,
            "vector": {
                stage.value: (
                    self.measurements[stage.value].to_dict()
                    if stage.value in self.measurements
                    else {"status": MeasurementStatus.NOT_MEASURED.value}
                )
                for stage in GeoStage
            },
            "missing_stages": list(self.missing_stages),
            "config": dict(self.config),
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS thread_geo_runs (
    session_id        TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL UNIQUE,
    subject           TEXT NOT NULL,
    phase             TEXT NOT NULL CHECK (
        phase IN ('preflight', 'offline_measure', 'live_observe', 'experiment', 'complete')
    ),
    measurements_json TEXT NOT NULL,
    config_json       TEXT NOT NULL,
    revision          INTEGER NOT NULL DEFAULT 0,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
)
"""


def ensure_geo_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(thread_geo_runs)")}
    if "revision" not in columns:
        try:
            conn.execute(
                "ALTER TABLE thread_geo_runs ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(thread_geo_runs)")}
            if "revision" not in columns:
                raise


class GeoStore:
    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            from core.paths import resolve_sessions_dir

            db_path = resolve_sessions_dir() / "sessions.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def get(self, session_id: str) -> GeoRun | None:
        with short_sqlite_connection(self._db_path, ensure_geo_schema) as conn:
            row = conn.execute(
                "SELECT * FROM thread_geo_runs WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def start(self, session_id: str, subject: str) -> GeoRun:
        subject = subject.strip()
        if not session_id or not subject or len(subject) > 4000:
            raise ValueError("GEO requires an active session and a 1-4000 character subject")
        now = time.time()
        run_id = f"geo-{uuid.uuid4().hex[:16]}"
        with short_sqlite_connection(self._db_path, ensure_geo_schema, immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM thread_geo_runs WHERE session_id = ?", (session_id,)
            ).fetchone()
            current = self._from_row(row) if row is not None else None
            if current is not None and current.phase is not GeoPhase.COMPLETE:
                if current.subject != subject:
                    raise ValueError(
                        "an active GEO run already owns this thread; "
                        "complete it before starting another"
                    )
                return current
            conn.execute(
                """INSERT INTO thread_geo_runs
                       (session_id, run_id, subject, phase, measurements_json, config_json,
                        revision, created_at, updated_at)
                   VALUES (?, ?, ?, 'preflight', '{}', '{}', 0, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       run_id=excluded.run_id, subject=excluded.subject, phase='preflight',
                       measurements_json='{}', config_json='{}', revision=0,
                       created_at=excluded.created_at, updated_at=excluded.updated_at""",
                (session_id, run_id, subject, now, now),
            )
        result = self.get(session_id)
        if result is None:
            raise RuntimeError("GEO run was not persisted")
        return result

    def configure(self, session_id: str, raw: Any) -> GeoRun:
        if not isinstance(raw, dict):
            raise ValueError("GEO config must be an object")
        allowed = {
            "workload_digest",
            "engine",
            "model",
            "locale",
            "repetitions",
            "approval_ref",
            "preregistration_ref",
        }
        if not raw or not set(raw) <= allowed:
            raise ValueError(f"GEO config keys must be a non-empty subset of {sorted(allowed)}")
        current = self._require(session_id)
        if current.phase in {GeoPhase.EXPERIMENT, GeoPhase.COMPLETE}:
            raise ValueError(f"{current.phase.value} GEO runs cannot be configured")
        if current.phase is GeoPhase.LIVE_OBSERVE and set(raw) != {"preregistration_ref"}:
            raise ValueError(
                "only a trusted preregistration receipt may be added after live starts"
            )
        config = dict(current.config)
        for key, value in raw.items():
            if key == "repetitions":
                if type(value) is not int or not 1 <= value <= 1000:
                    raise ValueError("GEO repetitions must be an integer from 1 to 1000")
                config[key] = value
                continue
            text = str(value).strip()
            if not text or len(text) > 1000:
                raise ValueError(f"GEO config {key} must contain 1-1000 characters")
            config[key] = text
        return self._update(current, config=config)

    def authorize_live(self, session_id: str, approval_ref: str) -> GeoRun:
        """Attach an operator-owned live-observation approval receipt."""
        return self.configure(session_id, {"approval_ref": approval_ref})

    def preregister_experiment(self, session_id: str, preregistration_ref: str) -> GeoRun:
        """Attach an operator-owned experiment preregistration receipt."""
        return self.configure(session_id, {"preregistration_ref": preregistration_ref})

    def record(self, session_id: str, raw: Any) -> GeoRun:
        current = self._require(session_id)
        if current.phase is GeoPhase.COMPLETE:
            raise ValueError("completed GEO runs cannot accept evidence")
        if not isinstance(raw, dict):
            raise ValueError("GEO evidence must be an object")
        evidence = GeoEvidence.from_dict({**raw, "phase": current.phase.value})
        if current.phase is GeoPhase.PREFLIGHT and evidence.stage is not GeoStage.FETCH:
            raise ValueError("preflight may record only F; later stages require a later phase")
        measurements = {**current.measurements, evidence.stage.value: evidence}
        return self._update(current, measurements=measurements)

    def advance(self, session_id: str, target: str) -> GeoRun:
        current = self._require(session_id)
        next_phase = GeoPhase(target)
        expected = {
            GeoPhase.PREFLIGHT: GeoPhase.OFFLINE_MEASURE,
            GeoPhase.OFFLINE_MEASURE: GeoPhase.LIVE_OBSERVE,
            GeoPhase.LIVE_OBSERVE: GeoPhase.EXPERIMENT,
        }.get(current.phase)
        if expected is None:
            raise ValueError(f"completed GEO phase {current.phase.value} cannot advance")
        if next_phase is not expected:
            raise ValueError(f"GEO phase must advance from {current.phase.value} to {expected}")
        if current.phase is GeoPhase.PREFLIGHT and GeoStage.FETCH.value not in current.measurements:
            raise ValueError("preflight must explicitly record F before offline measurement")
        if current.phase is not GeoPhase.PREFLIGHT and not any(
            evidence.phase is current.phase for evidence in current.measurements.values()
        ):
            raise ValueError(f"{current.phase.value} must record evidence before advancing")
        if next_phase is GeoPhase.LIVE_OBSERVE:
            required = {
                "workload_digest",
                "engine",
                "model",
                "locale",
                "repetitions",
                "approval_ref",
            }
            if missing := sorted(required - set(current.config)):
                raise ValueError(f"live observation requires frozen config: {missing}")
        if next_phase is GeoPhase.EXPERIMENT and "preregistration_ref" not in current.config:
            raise ValueError("experiment requires preregistration_ref")
        return self._update(current, phase=next_phase)

    def complete(self, session_id: str) -> GeoRun:
        current = self._require(session_id)
        if current.phase is GeoPhase.COMPLETE:
            raise ValueError("completed GEO runs cannot be completed again")
        if current.phase is not GeoPhase.EXPERIMENT:
            raise ValueError("GEO runs may complete only after the experiment phase")
        if not any(
            evidence.phase is GeoPhase.EXPERIMENT for evidence in current.measurements.values()
        ):
            raise ValueError("experiment must record evidence before completion")
        if current.missing_stages:
            raise ValueError(
                "GEO completion requires an explicit measured/partial/not_measured "
                f"record for every stage: {current.missing_stages}"
            )
        return self._update(current, phase=GeoPhase.COMPLETE)

    def render_prompt(self, session_id: str) -> str:
        current = self.get(session_id)
        if current is None:
            return ""
        lines = [
            '<geo_state authority="typed_projection">',
            f"<run_id>{current.run_id}</run_id>",
            f"<phase>{current.phase.value}</phase>",
            f"<subject>{escape(current.subject, quote=False)}</subject>",
            "<vector>",
        ]
        for stage in GeoStage:
            evidence = current.measurements.get(stage.value)
            status = evidence.status.value if evidence else MeasurementStatus.NOT_MEASURED.value
            denominator = evidence.denominator if evidence else None
            lines.append(
                f'<stage id="{stage.value}" status="{status}" '
                f'denominator="{denominator if denominator is not None else "not_measured"}" />'
            )
        lines.extend(
            (
                "</vector>",
                "Use get_geo/update_geo; prose cannot advance, aggregate, or complete this run.",
                "</geo_state>",
            )
        )
        return "\n".join(lines)

    def _require(self, session_id: str) -> GeoRun:
        current = self.get(session_id)
        if current is None:
            raise ValueError("no GEO run exists for this thread")
        return current

    def _update(
        self,
        current: GeoRun,
        *,
        phase: GeoPhase | None = None,
        measurements: dict[str, GeoEvidence] | None = None,
        config: dict[str, Any] | None = None,
    ) -> GeoRun:
        with short_sqlite_connection(self._db_path, ensure_geo_schema, immediate=True) as conn:
            cursor = conn.execute(
                """UPDATE thread_geo_runs
                   SET phase = ?, measurements_json = ?, config_json = ?,
                       revision = revision + 1, updated_at = ?
                   WHERE session_id = ? AND run_id = ? AND revision = ?""",
                (
                    (phase or current.phase).value,
                    json.dumps(
                        {
                            key: value.to_dict()
                            for key, value in (measurements or current.measurements).items()
                        }
                    ),
                    json.dumps(config if config is not None else current.config),
                    time.time(),
                    current.session_id,
                    current.run_id,
                    current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("stale GEO run update")
        return self._require(current.session_id)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> GeoRun:
        raw_measurements = json.loads(str(row["measurements_json"]))
        measurements = {
            str(key): GeoEvidence.from_dict(value) for key, value in raw_measurements.items()
        }
        if set(measurements) - {stage.value for stage in GeoStage}:
            raise ValueError("stored GEO vector contains an unknown stage")
        return GeoRun(
            session_id=str(row["session_id"]),
            run_id=str(row["run_id"]),
            subject=str(row["subject"]),
            phase=GeoPhase(str(row["phase"])),
            measurements=measurements,
            config=dict(json.loads(str(row["config_json"]))),
            revision=int(row["revision"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )


def _session_id() -> str:
    from core.agent.cognitive_state_ctx import get_session_id

    return get_session_id()


def _record(run: GeoRun, *, trigger: str) -> None:
    from core.agent.cognitive_state_ctx import get_tool_call_id
    from core.observability.session_timeline import (
        SessionEventKind,
        current_session_timeline,
    )

    timeline = current_session_timeline()
    if timeline is not None:
        kind = (
            SessionEventKind.GEO_COMPLETED
            if run.phase is GeoPhase.COMPLETE
            else SessionEventKind.GEO_UPDATED
        )
        timeline.record_control_state(
            kind,
            run,
            trigger=trigger,
            call_id=get_tool_call_id(),
        )


def _mark_prompt_dirty() -> None:
    from core.cli.session_state import get_current_loop

    loop = get_current_loop()
    if loop is not None:
        loop._prompt_dirty = True


def build_geo_handlers(store: GeoStore | None = None) -> Any:
    from core.tools.handlers.registration import UniqueEntries

    geo_store = store or GeoStore()

    def get_geo(**_: Any) -> dict[str, Any]:
        run = geo_store.get(_session_id())
        return {"status": "ok", "geo": run.to_dict() if run else None}

    def update_geo(**kwargs: Any) -> dict[str, Any]:
        action = str(kwargs.get("action") or "")
        try:
            if action == "configure":
                config = kwargs.get("config")
                if isinstance(config, dict) and {
                    "approval_ref",
                    "preregistration_ref",
                } & set(config):
                    raise ValueError(
                        "approval_ref and preregistration_ref are operator-owned slash receipts"
                    )
                run = geo_store.configure(_session_id(), config)
            elif action == "record":
                evidence = kwargs.get("evidence")
                run = geo_store.record(_session_id(), evidence)
            elif action == "advance":
                run = geo_store.advance(_session_id(), str(kwargs.get("phase") or ""))
            elif action == "complete":
                run = geo_store.complete(_session_id())
            else:
                raise ValueError(
                    "update_geo action must be configure, record, advance, or complete"
                )
        except (TypeError, ValueError) as exc:
            return {"error": str(exc), "action": action}
        _record(run, trigger=f"update_geo:{action}")
        _mark_prompt_dirty()
        return {"status": "ok", "action": action, "geo": run.to_dict()}

    return UniqueEntries((("get_geo", get_geo), ("update_geo", update_geo)))


__all__ = [
    "GeoEvidence",
    "GeoPhase",
    "GeoRun",
    "GeoStage",
    "GeoStore",
    "MeasurementStatus",
    "build_geo_handlers",
]
