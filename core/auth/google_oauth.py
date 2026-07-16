"""Google Workspace OAuth for locally installed GEODE distributions.

The flow is deliberately separate from LLM-provider authentication:

* a user-owned Google Desktop app client is imported at login time;
* Authorization Code + PKCE uses a random loopback port on 127.0.0.1;
* refresh tokens and the OAuth client secret live only in the OS keyring;
* ~/.geode/google/accounts.json stores bounded, non-secret account and
  granted-scope metadata.

Google native-app OAuth reference:
https://developers.google.com/identity/protocols/oauth2/native-app
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from core.memory.atomic_write import atomic_write_json
from core.paths import GLOBAL_GOOGLE_ACCOUNTS_FILE

log = logging.getLogger(__name__)
_ACCOUNT_STORE_LOCK = threading.RLock()

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_KEYRING_SERVICE = "geode.google.oauth"
GOOGLE_ACCOUNT_SCHEMA_VERSION = 1
GOOGLE_SECRET_SCHEMA_VERSION = 1

IDENTITY_SCOPES: tuple[str, ...] = ("openid", "email", "profile")


@dataclass(frozen=True, slots=True)
class GoogleServiceBundle:
    """Named least-privilege scope bundle exposed by /login google."""

    name: str
    scopes: tuple[str, ...]
    description: str
    risk: str


GOOGLE_SERVICE_BUNDLES: dict[str, GoogleServiceBundle] = {
    "gmail-send": GoogleServiceBundle(
        "gmail-send",
        ("https://www.googleapis.com/auth/gmail.send",),
        "Send mail without reading the mailbox",
        "sensitive",
    ),
    "gmail-read": GoogleServiceBundle(
        "gmail-read",
        ("https://www.googleapis.com/auth/gmail.readonly",),
        "Search and read Gmail messages",
        "restricted",
    ),
    "calendar-read": GoogleServiceBundle(
        "calendar-read",
        ("https://www.googleapis.com/auth/calendar.events.owned.readonly",),
        "Read events on calendars owned by the account",
        "sensitive",
    ),
    "calendar-write": GoogleServiceBundle(
        "calendar-write",
        ("https://www.googleapis.com/auth/calendar.events.owned",),
        "Read and edit events on calendars owned by the account",
        "sensitive",
    ),
    "workspace-files": GoogleServiceBundle(
        "workspace-files",
        ("https://www.googleapis.com/auth/drive.file",),
        "Use Drive, Docs, and Sheets files created or explicitly opened by GEODE",
        "non-sensitive",
    ),
    "tasks-read": GoogleServiceBundle(
        "tasks-read",
        ("https://www.googleapis.com/auth/tasks.readonly",),
        "Read Google Tasks",
        "sensitive",
    ),
    "tasks-write": GoogleServiceBundle(
        "tasks-write",
        ("https://www.googleapis.com/auth/tasks",),
        "Read and edit Google Tasks",
        "sensitive",
    ),
    "contacts-read": GoogleServiceBundle(
        "contacts-read",
        ("https://www.googleapis.com/auth/contacts.readonly",),
        "Read Google Contacts through the People API",
        "sensitive",
    ),
}

RECOMMENDED_GOOGLE_SERVICES: tuple[str, ...] = (
    "gmail-send",
    "calendar-read",
    "workspace-files",
)

_SERVICE_IMPLICATIONS: dict[str, frozenset[str]] = {
    "calendar-write": frozenset({"calendar-read"}),
    "tasks-write": frozenset({"tasks-read"}),
}


class GoogleOAuthError(RuntimeError):
    """Base error for deterministic Google OAuth failures."""


class GoogleCredentialStoreError(GoogleOAuthError):
    """The OS credential vault is unavailable or rejected an operation."""


class GoogleOAuthCallbackError(GoogleOAuthError):
    """The loopback OAuth callback failed validation."""


@dataclass(frozen=True, slots=True)
class GoogleOAuthClient:
    """Imported Google Desktop client fields used for one account."""

    client_id: str
    client_secret: str
    project_id: str = ""


@dataclass(frozen=True, slots=True)
class GoogleAccount:
    """Non-secret account registry row persisted in accounts.json."""

    account_id: str
    email: str
    display_name: str
    client_id: str
    project_id: str
    services: tuple[str, ...]
    granted_scopes: tuple[str, ...]
    secret_ref: str
    status: str
    created_at: str
    updated_at: str
    token_expires_at: float = 0.0
    last_refresh_at: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GoogleAccount:
        return cls(
            account_id=str(raw["account_id"]),
            email=str(raw.get("email", "")),
            display_name=str(raw.get("display_name", "")),
            client_id=str(raw.get("client_id", "")),
            project_id=str(raw.get("project_id", "")),
            services=tuple(str(v) for v in raw.get("services", [])),
            granted_scopes=tuple(str(v) for v in raw.get("granted_scopes", [])),
            secret_ref=str(raw.get("secret_ref", raw["account_id"])),
            status=str(raw.get("status", "connected")),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            token_expires_at=float(raw.get("token_expires_at", 0.0)),
            last_refresh_at=str(raw.get("last_refresh_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Account identity is Google user data. Keep it with credentials in
        # the encrypted OS keyring, never in the plaintext registry.
        payload.pop("email", None)
        payload.pop("display_name", None)
        payload["services"] = list(self.services)
        payload["granted_scopes"] = list(self.granted_scopes)
        return payload


@dataclass(frozen=True, slots=True)
class GoogleSecret:
    """Credential and private account label stored in the OS keyring."""

    client_secret: str
    refresh_token: str
    account_email: str = ""
    display_name: str = ""

    @classmethod
    def from_json(cls, raw: str) -> GoogleSecret:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoogleCredentialStoreError("Google keyring entry is malformed") from exc
        if not isinstance(data, dict) or int(data.get("schema_version", 0)) != 1:
            raise GoogleCredentialStoreError("Unsupported Google keyring schema")
        refresh_token = str(data.get("refresh_token", ""))
        if not refresh_token:
            raise GoogleCredentialStoreError("Google refresh token is missing from the keyring")
        return cls(
            client_secret=str(data.get("client_secret", "")),
            refresh_token=refresh_token,
            account_email=str(data.get("account_email", "")),
            display_name=str(data.get("display_name", "")),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": GOOGLE_SECRET_SCHEMA_VERSION,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "account_email": self.account_email,
                "display_name": self.display_name,
            },
            separators=(",", ":"),
        )


class GoogleSecretStore(Protocol):
    """Minimal secret-vault contract, injectable for tests."""

    def ensure_available(self) -> None: ...

    def get(self, secret_ref: str) -> GoogleSecret | None: ...

    def set(self, secret_ref: str, secret: GoogleSecret) -> None: ...

    def delete(self, secret_ref: str) -> None: ...


class KeyringGoogleSecretStore:
    """OS keyring implementation; fails closed when no secure backend exists."""

    def __init__(self, service_name: str | None = None) -> None:
        self._service_name = (
            service_name or os.environ.get("GEODE_GOOGLE_KEYRING_SERVICE") or GOOGLE_KEYRING_SERVICE
        )

    @staticmethod
    def _keyring() -> Any:
        try:
            import keyring
        except ImportError as exc:
            raise GoogleCredentialStoreError(
                "The keyring package is required; reinstall GEODE with current dependencies"
            ) from exc
        return keyring

    def ensure_available(self) -> None:
        keyring = self._keyring()
        try:
            backend = keyring.get_keyring()
            priority = float(getattr(backend, "priority", 0.0))
        except Exception as exc:
            raise GoogleCredentialStoreError(
                "Could not initialize the operating-system credential vault"
            ) from exc
        candidates = list(getattr(backend, "backends", ())) or [backend]
        effective = next(
            (
                candidate
                for candidate in candidates
                if float(getattr(candidate, "priority", 0.0)) > 0
            ),
            backend,
        )
        backend_name = f"{type(effective).__module__}.{type(effective).__name__}".lower()
        insecure_backend = any(
            marker in backend_name for marker in (".fail.", ".null.", "plaintext", "keyrings.alt")
        )
        if priority <= 0 or insecure_backend or backend_name.endswith(".failkeyring"):
            raise GoogleCredentialStoreError(
                "No secure OS keyring backend is available. Configure macOS Keychain, "
                "Windows Credential Locker, or Linux Secret Service before /login google."
            )

    def get(self, secret_ref: str) -> GoogleSecret | None:
        self.ensure_available()
        keyring = self._keyring()
        try:
            raw = keyring.get_password(self._service_name, secret_ref)
        except Exception as exc:
            raise GoogleCredentialStoreError("Could not read Google credentials") from exc
        return GoogleSecret.from_json(raw) if raw else None

    def set(self, secret_ref: str, secret: GoogleSecret) -> None:
        self.ensure_available()
        keyring = self._keyring()
        try:
            keyring.set_password(self._service_name, secret_ref, secret.to_json())
        except Exception as exc:
            raise GoogleCredentialStoreError("Could not save Google credentials") from exc

    def delete(self, secret_ref: str) -> None:
        self.ensure_available()
        keyring = self._keyring()
        try:
            keyring.delete_password(self._service_name, secret_ref)
        except keyring.errors.PasswordDeleteError:
            return
        except Exception as exc:
            raise GoogleCredentialStoreError("Could not delete Google credentials") from exc


class GoogleAccountStore:
    """Atomic metadata registry paired with an injected secret vault."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        secret_store: GoogleSecretStore | None = None,
    ) -> None:
        override = os.environ.get("GEODE_GOOGLE_ACCOUNTS_FILE")
        self.path = (
            Path(override).expanduser() if override else (path or GLOBAL_GOOGLE_ACCOUNTS_FILE)
        )
        self.secret_store = secret_store or KeyringGoogleSecretStore()

    def _read_registry(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": GOOGLE_ACCOUNT_SCHEMA_VERSION,
                "revision": 0,
                "active_account_id": "",
                "accounts": [],
            }
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GoogleOAuthError(f"Google account registry is unreadable: {self.path}") from exc
        if not isinstance(raw, dict):
            raise GoogleOAuthError(f"Malformed Google account registry: {self.path}")
        if int(raw.get("schema_version", 0)) != GOOGLE_ACCOUNT_SCHEMA_VERSION:
            raise GoogleOAuthError(
                f"Unsupported Google account schema in {self.path}; expected version "
                f"{GOOGLE_ACCOUNT_SCHEMA_VERSION}"
            )
        accounts = raw.get("accounts")
        if not isinstance(accounts, list):
            raise GoogleOAuthError(f"Malformed Google account registry: {self.path}")
        try:
            revision = int(raw.get("revision", 0))
        except (TypeError, ValueError) as exc:
            raise GoogleOAuthError(f"Malformed Google account registry: {self.path}") from exc
        if revision < 0:
            raise GoogleOAuthError(f"Malformed Google account registry: {self.path}")
        raw["revision"] = revision
        return raw

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            log.debug("Could not chmod %s to 0700", self.path.parent)
        payload["revision"] = int(payload.get("revision", 0)) + 1
        atomic_write_json(self.path, payload, indent=2)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            log.debug("Could not chmod %s to 0600", self.path)

    @contextmanager
    def _locked_registry(self) -> Iterator[None]:
        """Serialize account registry transactions across GEODE processes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            log.debug("Could not chmod %s to 0700", self.path.parent)
        lock_path = self.path.parent / ".accounts.lock"
        with lock_path.open("a+b") as lock_file:
            try:
                os.chmod(lock_path, 0o600)
            except OSError:
                log.debug("Could not chmod %s to 0600", lock_path)
            if os.name == "nt":
                msvcrt: Any = __import__("msvcrt")

                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                lock_file.seek(0)
                if os.name == "nt":
                    msvcrt = __import__("msvcrt")

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _accounts_from_payload(self, payload: dict[str, Any]) -> list[GoogleAccount]:
        rows: list[GoogleAccount] = []
        for raw in payload["accounts"]:
            if not isinstance(raw, dict):
                continue
            try:
                account = GoogleAccount.from_dict(raw)
                secret = self.secret_store.get(account.secret_ref)
                if secret is not None:
                    account = replace(
                        account,
                        email=secret.account_email,
                        display_name=secret.display_name,
                    )
                rows.append(account)
            except (KeyError, TypeError, ValueError):
                log.warning("Skipping malformed Google account metadata row")
        return rows

    def _find_in_payload(
        self,
        payload: dict[str, Any],
        account_id_or_email: str,
    ) -> GoogleAccount | None:
        needle = account_id_or_email.strip().lower()
        for account in self._accounts_from_payload(payload):
            if account.account_id.lower() == needle or account.email.lower() == needle:
                return account
        return None

    def list_accounts(self) -> list[GoogleAccount]:
        with _ACCOUNT_STORE_LOCK, self._locked_registry():
            return self._accounts_from_payload(self._read_registry())

    def active_account_id(self) -> str:
        with _ACCOUNT_STORE_LOCK, self._locked_registry():
            return str(self._read_registry().get("active_account_id", ""))

    def get(self, account_id_or_email: str) -> GoogleAccount | None:
        with _ACCOUNT_STORE_LOCK, self._locked_registry():
            return self._find_in_payload(self._read_registry(), account_id_or_email)

    def get_active(self) -> GoogleAccount | None:
        with _ACCOUNT_STORE_LOCK, self._locked_registry():
            payload = self._read_registry()
            accounts = self._accounts_from_payload(payload)
            active_id = str(payload.get("active_account_id", ""))
            if active_id:
                account = next(
                    (row for row in accounts if row.account_id == active_id),
                    None,
                )
                if account is not None:
                    return account
            return accounts[0] if len(accounts) == 1 else None

    def set_active(self, account_id_or_email: str) -> GoogleAccount:
        with _ACCOUNT_STORE_LOCK, self._locked_registry():
            payload = self._read_registry()
            account = self._find_in_payload(payload, account_id_or_email)
            if account is None:
                raise GoogleOAuthError(f"Google account not found: {account_id_or_email}")
            payload["active_account_id"] = account.account_id
            self._write(payload)
            return account

    def save(self, account: GoogleAccount, secret: GoogleSecret) -> None:
        with _ACCOUNT_STORE_LOCK, self._locked_registry():
            payload = self._read_registry()
            previous_secret = self.secret_store.get(account.secret_ref)
            private_payload = replace(
                secret,
                account_email=account.email,
                display_name=account.display_name,
            )
            self.secret_store.set(account.secret_ref, private_payload)
            rows = [
                raw
                for raw in payload["accounts"]
                if isinstance(raw, dict) and str(raw.get("account_id", "")) != account.account_id
            ]
            rows.append(account.to_dict())
            rows.sort(key=lambda row: str(row.get("account_id", "")))
            payload["accounts"] = rows
            payload["active_account_id"] = account.account_id
            try:
                self._write(payload)
            except Exception:
                try:
                    if previous_secret is None:
                        self.secret_store.delete(account.secret_ref)
                    else:
                        self.secret_store.set(account.secret_ref, previous_secret)
                except GoogleCredentialStoreError:
                    log.warning("Could not roll back Google keyring entry", exc_info=True)
                raise

    def update_refresh_metadata(
        self,
        account: GoogleAccount,
        *,
        expected_refresh_token: str | None = None,
        rotated_secret: GoogleSecret | None = None,
    ) -> bool:
        """Patch only volatile refresh fields on the latest account row.

        Reading the row under the cross-process lock prevents a refresh based
        on stale metadata from reverting a concurrent reauthorization's
        client, services, or granted scopes.  Comparing the refresh token used
        for the request also detects a same-client reauthorization or another
        concurrent token rotation whose public metadata did not change.
        """
        with _ACCOUNT_STORE_LOCK, self._locked_registry():
            payload = self._read_registry()
            found = False
            previous_secret: GoogleSecret | None = None
            rows: list[dict[str, Any]] = []
            for raw in payload["accounts"]:
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("account_id", "")) == account.account_id:
                    current = GoogleAccount.from_dict(raw)
                    current_auth = (
                        current.client_id,
                        current.project_id,
                        current.services,
                        current.granted_scopes,
                        current.secret_ref,
                    )
                    refreshed_auth = (
                        account.client_id,
                        account.project_id,
                        account.services,
                        account.granted_scopes,
                        account.secret_ref,
                    )
                    if current_auth != refreshed_auth:
                        log.info(
                            "Skipped stale Google refresh metadata: account_id=%s",
                            account.account_id,
                        )
                        return False
                    if expected_refresh_token is not None or rotated_secret is not None:
                        previous_secret = self.secret_store.get(account.secret_ref)
                    if expected_refresh_token is not None and (
                        previous_secret is None
                        or not secrets.compare_digest(
                            previous_secret.refresh_token,
                            expected_refresh_token,
                        )
                    ):
                        log.info(
                            "Skipped stale Google refresh secret: account_id=%s",
                            account.account_id,
                        )
                        return False
                    rows.append(
                        replace(
                            current,
                            token_expires_at=account.token_expires_at,
                            last_refresh_at=account.last_refresh_at,
                            updated_at=account.updated_at,
                        ).to_dict()
                    )
                    found = True
                else:
                    rows.append(raw)
            if not found:
                raise GoogleOAuthError(f"Google account not found: {account.account_id}")
            rows.sort(key=lambda row: str(row.get("account_id", "")))
            payload["accounts"] = rows
            if rotated_secret is not None:
                if previous_secret is None:
                    previous_secret = self.secret_store.get(account.secret_ref)
                self.secret_store.set(
                    account.secret_ref,
                    replace(
                        rotated_secret,
                        client_secret=(
                            previous_secret.client_secret
                            if previous_secret is not None
                            else rotated_secret.client_secret
                        ),
                        account_email=(
                            previous_secret.account_email if previous_secret is not None else ""
                        ),
                        display_name=(
                            previous_secret.display_name if previous_secret is not None else ""
                        ),
                    ),
                )
            try:
                self._write(payload)
            except Exception:
                if rotated_secret is not None:
                    try:
                        if previous_secret is None:
                            self.secret_store.delete(account.secret_ref)
                        else:
                            self.secret_store.set(account.secret_ref, previous_secret)
                    except GoogleCredentialStoreError:
                        log.warning("Could not roll back Google keyring entry", exc_info=True)
                raise
            return True

    def load_secret(self, account: GoogleAccount) -> GoogleSecret:
        secret = self.secret_store.get(account.secret_ref)
        if secret is None:
            raise GoogleCredentialStoreError(
                f"Google credential is missing for {account.email}; rerun /login google"
            )
        return secret

    def remove(self, account_id_or_email: str) -> GoogleAccount:
        with _ACCOUNT_STORE_LOCK, self._locked_registry():
            payload = self._read_registry()
            account = self._find_in_payload(payload, account_id_or_email)
            if account is None:
                raise GoogleOAuthError(f"Google account not found: {account_id_or_email}")
            previous_secret = self.secret_store.get(account.secret_ref)
            self.secret_store.delete(account.secret_ref)
            payload["accounts"] = [
                raw
                for raw in payload["accounts"]
                if isinstance(raw, dict) and str(raw.get("account_id", "")) != account.account_id
            ]
            if payload.get("active_account_id") == account.account_id:
                remaining = payload["accounts"]
                payload["active_account_id"] = (
                    str(remaining[0].get("account_id", "")) if remaining else ""
                )
            try:
                self._write(payload)
            except Exception:
                if previous_secret is not None:
                    try:
                        self.secret_store.set(account.secret_ref, previous_secret)
                    except GoogleCredentialStoreError:
                        log.warning("Could not roll back Google keyring entry", exc_info=True)
                raise
            return account


def normalize_google_services(services: Sequence[str]) -> tuple[str, ...]:
    """Validate, de-duplicate, and collapse bundles implied by write scopes."""
    normalized = {service.strip().lower() for service in services if service.strip()}
    unknown = sorted(normalized - GOOGLE_SERVICE_BUNDLES.keys())
    if unknown:
        raise GoogleOAuthError(
            f"Unknown Google service bundle(s): {', '.join(unknown)}. Available: "
            f"{', '.join(GOOGLE_SERVICE_BUNDLES)}"
        )
    for parent, implied in _SERVICE_IMPLICATIONS.items():
        if parent in normalized:
            normalized.difference_update(implied)
    return tuple(sorted(normalized))


def google_scopes_for_services(services: Sequence[str]) -> tuple[str, ...]:
    """Return stable, de-duplicated OAuth scopes including OIDC identity."""
    normalized = normalize_google_services(services)
    scopes = set(IDENTITY_SCOPES)
    for service in normalized:
        scopes.update(GOOGLE_SERVICE_BUNDLES[service].scopes)
    return tuple(sorted(scopes))


def load_google_client_json(path: Path) -> GoogleOAuthClient:
    """Validate a Google Desktop app client JSON without retaining the file."""
    try:
        raw = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoogleOAuthError(f"Could not read Google OAuth client JSON: {path}") from exc
    installed = raw.get("installed") if isinstance(raw, dict) else None
    if not isinstance(installed, dict):
        raise GoogleOAuthError("Google OAuth JSON must contain an 'installed' Desktop app client")
    client_id = str(installed.get("client_id", "")).strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise GoogleOAuthError("Google OAuth Desktop client_id is missing or malformed")
    return GoogleOAuthClient(
        client_id=client_id,
        client_secret=str(installed.get("client_secret", "")),
        project_id=str(installed.get("project_id", "")),
    )


def google_utc_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _account_id(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_google_authorization_url(
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    *,
    state: str,
    code_challenge: str,
    login_hint: str = "",
) -> str:
    """Build the official native-app authorization URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return GOOGLE_AUTHORIZATION_URL + "?" + urlencode(params)


@dataclass(frozen=True, slots=True)
class _CallbackResult:
    code: str = ""
    state: str = ""
    error: str = ""
    error_description: str = ""


class _CallbackHTTPServer(ThreadingHTTPServer):
    callback_result: _CallbackResult | None
    callback_event: threading.Event


class _GoogleCallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackHTTPServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/oauth2/callback":
            self.send_error(404)
            return
        query = parse_qs(parsed.query)
        result = _CallbackResult(
            code=query.get("code", [""])[0],
            state=query.get("state", [""])[0],
            error=query.get("error", [""])[0],
            error_description=query.get("error_description", [""])[0],
        )
        self.server.callback_result = result
        self.server.callback_event.set()
        ok = bool(result.code and not result.error)
        title = "Google account connected" if ok else "Google authorization did not complete"
        body = (
            "You can close this tab and return to GEODE."
            if ok
            else "Return to GEODE for the error details."
        )
        html = (
            "<!doctype html><html><head><meta charset='utf-8'><title>"
            + title
            + "</title></head><body><h1>"
            + title
            + "</h1><p>"
            + body
            + "</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class GoogleLoopbackReceiver:
    """One-shot loopback callback receiver bound to a random local port."""

    def __init__(self) -> None:
        self._server = _CallbackHTTPServer(("127.0.0.1", 0), _GoogleCallbackHandler)
        self._server.callback_result = None
        self._server.callback_event = threading.Event()
        host, port = cast(tuple[str, int], self._server.server_address)
        self.redirect_uri = f"http://{host}:{port}/oauth2/callback"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="geode-google-oauth-callback",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def wait(self, timeout_s: float) -> _CallbackResult:
        try:
            if not self._server.callback_event.wait(timeout_s):
                raise GoogleOAuthCallbackError(
                    f"Google authorization timed out after {int(timeout_s)} seconds"
                )
            result = self._server.callback_result
            if result is None:
                raise GoogleOAuthCallbackError("Google authorization callback was empty")
            return result
        finally:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2.0)


def _exchange_authorization_code(
    client: GoogleOAuthClient,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    http_client: httpx.Client,
) -> dict[str, Any]:
    form = {
        "client_id": client.client_id,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if client.client_secret:
        form["client_secret"] = client.client_secret
    try:
        response = http_client.post(GOOGLE_TOKEN_URL, data=form)
    except httpx.HTTPError as exc:
        raise GoogleOAuthError("Could not reach the Google token endpoint") from exc
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise GoogleOAuthError(f"Google token exchange failed ({response.status_code})") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleOAuthError("Google token response was not valid JSON") from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise GoogleOAuthError("Google token response did not contain an access token")
    return payload


def _fetch_google_userinfo(access_token: str, http_client: httpx.Client) -> dict[str, Any]:
    try:
        response = http_client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except httpx.HTTPError as exc:
        raise GoogleOAuthError("Could not reach the Google identity endpoint") from exc
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise GoogleOAuthError(f"Google identity lookup failed ({response.status_code})") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleOAuthError("Google identity response was not valid JSON") from exc
    if not isinstance(payload, dict) or not payload.get("sub") or not payload.get("email"):
        raise GoogleOAuthError("Google identity response was incomplete")
    return payload


def login_google(
    *,
    client_json: Path | None,
    services: Sequence[str],
    replace_services: bool = False,
    new_account: bool = False,
    timeout_s: float = 300.0,
    account_store: GoogleAccountStore | None = None,
    browser_open: Callable[[str], bool] = webbrowser.open,
    announce_url: Callable[[str], None] | None = None,
    http_client: httpx.Client | None = None,
) -> GoogleAccount:
    """Run native Google OAuth and persist the resulting account safely."""
    store = account_store or GoogleAccountStore()
    store.secret_store.ensure_available()
    active = store.get_active()
    target = None if new_account else active

    resolved_path = client_json
    if resolved_path is None:
        env_path = os.environ.get("GEODE_GOOGLE_CLIENT_JSON")
        if env_path:
            resolved_path = Path(env_path).expanduser()

    if resolved_path is not None:
        client = load_google_client_json(resolved_path)
    elif active is not None:
        existing_secret = store.load_secret(active)
        client = GoogleOAuthClient(
            client_id=active.client_id,
            client_secret=existing_secret.client_secret,
            project_id=active.project_id,
        )
    else:
        raise GoogleOAuthError(
            "A Google Desktop OAuth client JSON is required for the first login. "
            "Use /login google --client-json /path/to/client_secret.json"
        )

    requested = normalize_google_services(services)
    if target is not None and not replace_services:
        requested = normalize_google_services((*target.services, *requested))
    scopes = google_scopes_for_services(requested)

    try:
        receiver = GoogleLoopbackReceiver()
    except OSError as exc:
        raise GoogleOAuthError("Could not bind the Google OAuth loopback callback") from exc
    receiver.start()
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _pkce_pair()
    authorization_url = build_google_authorization_url(
        client.client_id,
        receiver.redirect_uri,
        scopes,
        state=state,
        code_challenge=code_challenge,
        login_hint=target.email if target is not None else "",
    )
    if announce_url is not None:
        announce_url(authorization_url)
    try:
        browser_open(authorization_url)
    except Exception:
        log.debug("Could not open the system browser", exc_info=True)

    callback = receiver.wait(timeout_s)
    if callback.state != state:
        raise GoogleOAuthCallbackError("Google OAuth state validation failed")
    if callback.error:
        detail = callback.error_description or callback.error
        raise GoogleOAuthCallbackError(f"Google authorization was denied: {detail}")
    if not callback.code:
        raise GoogleOAuthCallbackError("Google authorization code was missing")

    owns_client = http_client is None
    client_http = http_client or httpx.Client(timeout=30.0)
    try:
        token_payload = _exchange_authorization_code(
            client,
            code=callback.code,
            code_verifier=code_verifier,
            redirect_uri=receiver.redirect_uri,
            http_client=client_http,
        )
        access_token = str(token_payload["access_token"])
        userinfo = _fetch_google_userinfo(access_token, client_http)
        account_id = _account_id(str(userinfo["sub"]))
        if target is not None and account_id != target.account_id:
            try:
                client_http.post(
                    GOOGLE_REVOKE_URL,
                    data={"token": str(token_payload.get("refresh_token") or access_token)},
                )
            except httpx.HTTPError:
                log.warning("Could not revoke the mismatched Google browser grant")
            raise GoogleOAuthError(
                "Google returned a different account than the active reauthorization target. "
                "Retry with the active account, or use /login google --new-account to connect "
                "another account."
            )
    finally:
        if owns_client:
            client_http.close()

    previous = store.get(account_id)
    if new_account and previous is not None:
        raise GoogleOAuthError(
            f"{previous.email} is already connected. Use /login google use {previous.email}, "
            "or reauthorize it without --new-account."
        )
    refresh_token = str(token_payload.get("refresh_token", ""))
    if not refresh_token and previous is not None:
        refresh_token = store.load_secret(previous).refresh_token
    if not refresh_token:
        raise GoogleOAuthError(
            "Google did not return a refresh token. Revoke the existing grant and retry."
        )

    granted_scopes = tuple(
        sorted(
            scope for scope in str(token_payload.get("scope", " ".join(scopes))).split() if scope
        )
    )
    granted_scope_set = set(granted_scopes)
    granted_services = tuple(
        service
        for service in requested
        if set(GOOGLE_SERVICE_BUNDLES[service].scopes).issubset(granted_scope_set)
    )
    missing_services = sorted(set(requested) - set(granted_services))
    if missing_services:
        log.warning(
            "Google consent omitted service bundles: %s",
            ", ".join(missing_services),
        )
    now = google_utc_iso()
    account = GoogleAccount(
        account_id=account_id,
        email=str(userinfo["email"]),
        display_name=str(userinfo.get("name", "")),
        client_id=client.client_id,
        project_id=client.project_id,
        services=granted_services,
        granted_scopes=granted_scopes,
        secret_ref=f"account:{account_id}",
        status="connected",
        created_at=previous.created_at if previous is not None else now,
        updated_at=now,
        token_expires_at=time.time() + float(token_payload.get("expires_in", 3600)),
        last_refresh_at=now,
    )
    store.save(
        account,
        GoogleSecret(
            client_secret=client.client_secret,
            refresh_token=refresh_token,
        ),
    )
    log.info(
        "Google OAuth connected: account_id=%s services=%d scopes=%d",
        account.account_id,
        len(account.services),
        len(account.granted_scopes),
    )
    return account


def revoke_google_account(
    account_id_or_email: str | None = None,
    *,
    account_store: GoogleAccountStore | None = None,
    local_only: bool = False,
    http_client: httpx.Client | None = None,
) -> GoogleAccount:
    """Revoke the Google grant, then remove both keyring and metadata rows."""
    store = account_store or GoogleAccountStore()
    account = store.get(account_id_or_email) if account_id_or_email else store.get_active()
    if account is None:
        raise GoogleOAuthError("No matching Google account is connected")
    secret = store.load_secret(account)
    if not local_only:
        owns_client = http_client is None
        client_http = http_client or httpx.Client(timeout=30.0)
        try:
            try:
                response = client_http.post(
                    GOOGLE_REVOKE_URL,
                    data={"token": secret.refresh_token},
                )
            except httpx.HTTPError as exc:
                raise GoogleOAuthError(
                    "Could not reach Google token revocation; local credentials were preserved"
                ) from exc
            if response.status_code not in (200, 400):
                raise GoogleOAuthError(
                    f"Google token revocation failed ({response.status_code}); "
                    "local credentials were preserved"
                )
        finally:
            if owns_client:
                client_http.close()
    removed = store.remove(account.account_id)
    log.info("Google OAuth disconnected: account_id=%s", removed.account_id)
    return removed


def google_account_status(
    *,
    account_store: GoogleAccountStore | None = None,
) -> list[dict[str, Any]]:
    """Return bounded status rows with no secret material."""
    store = account_store or GoogleAccountStore()
    active_id = store.active_account_id()
    rows: list[dict[str, Any]] = []
    for account in store.list_accounts():
        rows.append(
            {
                "account_id": account.account_id,
                "email": account.email,
                "display_name": account.display_name,
                "active": account.account_id == active_id,
                "status": account.status,
                "services": list(account.services),
                "granted_scopes": list(account.granted_scopes),
                "token_expires_at": account.token_expires_at,
                "updated_at": account.updated_at,
            }
        )
    return rows
