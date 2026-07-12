"""Git-native receipts that prevent duplicate stochastic train tickets."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract import ContractError, ExperimentContract

CANDIDATE_FINGERPRINT_SCHEMA = "crucible.candidate-fingerprint.v1"
CANDIDATE_FINGERPRINT_OBSERVATION_SCHEMA = "crucible.candidate-fingerprint-observation.v1"

_ZERO_SHA = "0" * 40
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CandidateFingerprintStore:
    repository: Path
    git: str
    prefix: str = "refs/crucible/candidate-fingerprints"

    def _git(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(  # noqa: S603 - fixed git executable and argv
            [self.git, *args],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode:
            raise ContractError(result.stderr.strip() or "candidate fingerprint git failure")
        return result.stdout.strip()

    def fingerprint(
        self,
        *,
        contract: ExperimentContract,
        surfaces: Sequence[str],
    ) -> str:
        """Bind one stable patch to the baseline and frozen measurement world."""

        diff = subprocess.run(  # noqa: S603 - fixed git executable and argv
            [
                self.git,
                "--no-replace-objects",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--binary",
                contract.baseline_sha,
                contract.candidate_sha,
                "--",
                *surfaces,
            ],
            cwd=self.repository,
            check=False,
            capture_output=True,
        )
        if diff.returncode:
            raise ContractError("cannot derive the candidate patch fingerprint")
        patch_id = subprocess.run(  # noqa: S603 - fixed git executable and argv
            [self.git, "patch-id", "--stable"],
            cwd=self.repository,
            input=diff.stdout,
            check=False,
            capture_output=True,
            text=False,
        )
        fields = patch_id.stdout.decode("ascii", errors="strict").split()
        if patch_id.returncode or len(fields) < 2 or _GIT_SHA.fullmatch(fields[0]) is None:
            raise ContractError("candidate patch has no stable git patch identity")
        return _canonical_hash(
            {
                "schema": "crucible.candidate-treatment-identity.v1",
                "baseline_sha": contract.baseline_sha,
                "stable_patch_id": fields[0],
                "evaluator_sha256": contract.evaluator_sha256,
                "harness_sha256": contract.harness_sha256,
                "task_pack_sha256": contract.task_pack_sha256,
                "agent_route": contract.agent_route,
                "user_route": contract.user_route,
                "assay_config_sha256": contract.assay_config_sha256,
                "promotion": contract.promotion.to_dict(),
                "budget": contract.budget.to_dict(),
                "vetoes": list(contract.vetoes),
            }
        )

    def reference(self, fingerprint: str) -> str:
        if _SHA256.fullmatch(fingerprint) is None:
            raise ContractError("candidate fingerprint must be a SHA-256 digest")
        return f"{self.prefix}/{fingerprint}"

    def load(self, fingerprint: str) -> dict[str, Any] | None:
        reference = self.reference(fingerprint)
        object_id = self._git("rev-parse", "--verify", "--quiet", reference, check=False)
        if not object_id:
            return None
        encoded = self._git("cat-file", "blob", object_id)
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ContractError("candidate fingerprint ref is not valid JSON") from exc
        if not isinstance(value, dict) or value.get("schema") != CANDIDATE_FINGERPRINT_SCHEMA:
            raise ContractError("candidate fingerprint ref has an unsupported schema")
        if value.get("fingerprint_sha256") != fingerprint:
            raise ContractError("candidate fingerprint ref does not match its name")
        candidate_sha = value.get("candidate_sha")
        if not isinstance(candidate_sha, str) or _GIT_SHA.fullmatch(candidate_sha) is None:
            raise ContractError("candidate fingerprint candidate_sha must be a full git SHA")
        for field in ("contract_id", "verdict_id"):
            digest = value.get(field)
            if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
                raise ContractError(f"candidate fingerprint {field} must be a SHA-256 digest")
        if value.get("verdict") not in {"KEEP", "REJECT"}:
            raise ContractError("candidate fingerprint requires a valid train verdict")
        return value

    def persist(
        self,
        fingerprint: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """CAS one valid verdict receipt; return a racing prior receipt if present."""

        prior = self.load(fingerprint)
        if prior is not None:
            return prior
        encoded = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
        blob = subprocess.run(  # noqa: S603 - fixed git executable and argv
            [self.git, "hash-object", "-w", "--stdin"],
            cwd=self.repository,
            input=encoded,
            check=False,
            capture_output=True,
        )
        if blob.returncode:
            raise ContractError("cannot persist candidate fingerprint receipt")
        object_id = blob.stdout.decode("ascii", errors="strict").strip()
        try:
            self._git("update-ref", self.reference(fingerprint), object_id, _ZERO_SHA)
        except ContractError:
            prior = self.load(fingerprint)
            if prior is None:
                raise
            return prior
        return None
