# Google Workspace OAuth and data boundary

Status: implemented. This document records the native installed-app OAuth,
storage, scope, and agent-consent contract behind `/login google`.

## User flow

1. The user creates a Google Cloud OAuth client whose application type is
   **Desktop app**, enables the APIs they need, and downloads its client JSON.
2. In an interactive GEODE session, the user runs `/login google` (recommended)
   or `/login google --client-json PATH --services a,b`.
3. On first connection, GEODE requires an explicit service-bundle selection.
   `recommended` means `gmail-send,calendar-read,workspace-files`; `all` is an
   explicit opt-in and includes the restricted `gmail-read` bundle.
4. GEODE opens the system browser and listens on a random
   `http://127.0.0.1:<port>/oauth2/callback` address. The authorization-code
   exchange uses PKCE S256 and validates a random `state` value.
5. The client JSON is read once. GEODE does not copy the source file. The
   refresh token, client secret, account email, and display name are saved in
   the OS credential vault. The access token exists only in process memory.

Google's installed-app guide recommends a Desktop client, the system browser,
a random loopback port, PKCE, and state. Manual OOB copy/paste is no longer
supported. Installed apps also do not support incremental authorization, so a
reauthorization targets the active account (including a `login_hint`) and
requests the union of that account's existing bundles and the new bundles.
GEODE rejects a browser callback for a different identity instead of copying
the active account's scopes onto it. Use `--new-account` to connect a second
identity; it starts with its own explicit bundle choice while reusing the saved
Desktop client when no new client JSON is supplied. To deliberately narrow a
grant, pass `--replace-services` together with the complete bundle list to
keep; Google then shows a fresh consent screen for only that requested set.

## Service bundles

The bundle name, not a raw scope URI, is the public CLI contract. This keeps
the consent choice understandable while preserving exact granted scopes in the
registry.

| Bundle | Google scope | Risk | GEODE surface |
|---|---|---|---|
| `gmail-send` | `gmail.send` | Sensitive | `gmail_send` |
| `gmail-read` | `gmail.readonly` | Restricted | `gmail_search` |
| `calendar-read` | `calendar.events.owned.readonly` | Sensitive | `calendar_list_events` |
| `calendar-write` | `calendar.events.owned` | Sensitive | `calendar_list_events`, `calendar_create_event`, `calendar_sync_scheduler`; no general update/delete tool in v1.0.0 |
| `workspace-files` | `drive.file` | Non-sensitive, per-file | Drive search/create, Docs read/write, Sheets read/write |
| `tasks-read` | `tasks.readonly` | Sensitive | `google_tasks_list` |
| `tasks-write` | `tasks` | Sensitive | `google_tasks_list`, `google_tasks_write` |
| `contacts-read` | `contacts.readonly` | Sensitive | `google_contacts_list` |

`drive.file` deliberately does not expose the user's whole Drive. The supported
v1.0.0 path covers files GEODE creates. The scope can also cover files a user
opens through a Google Picker, but GEODE v1.0.0 does not ship that Picker; a
future Picker surface can add the existing-file path without adopting the
restricted whole-Drive scopes.

If a user deselects a scope on Google's consent screen, GEODE records only the
bundles whose scopes were actually granted. A missing bundle fails before an
API request and points back to `/login google --services <bundle>`.

## Storage schema

The registry is global because OAuth identity is user-level and a GEODE daemon
serves projects without sharing a project working directory. It supports
multiple accounts and one explicit active account.

`~/.geode/google/accounts.json` is an atomic, mode `0600` metadata registry
inside a mode `0700` directory:

```json
{
  "schema_version": 1,
  "revision": 7,
  "active_account_id": "sha256(google_sub)[:24]",
  "accounts": [
    {
      "account_id": "sha256(google_sub)[:24]",
      "client_id": "...apps.googleusercontent.com",
      "project_id": "user-owned-google-cloud-project",
      "services": ["calendar-read", "gmail-send", "workspace-files"],
      "granted_scopes": ["openid", "email", "profile", "..."],
      "secret_ref": "account:<account_id>",
      "status": "connected",
      "created_at": "RFC3339",
      "updated_at": "RFC3339",
      "token_expires_at": 0.0,
      "last_refresh_at": "RFC3339"
    }
  ]
}
```

The registry never contains an access token, refresh token, client secret,
account email, display name, message, event, file, task, contact, or model
output. Corrupt or unknown schema versions fail closed instead of being reset.
Every read-modify-write transaction takes both a process lock and
`~/.geode/google/.accounts.lock`, then atomically replaces the JSON file. The
monotonic `revision` makes completed registry writes observable. Token refresh
patches only `token_expires_at`, `last_refresh_at`, and `updated_at` on the
latest row. If its client/scope fingerprint or the keyring refresh token used
for the request changed during refresh, GEODE discards the stale patch and any
rotated refresh token instead of reverting a concurrent reauthorization or
token rotation.

The OS keyring service `geode.google.oauth` stores one opaque value per
`secret_ref`:

```json
{
  "schema_version": 1,
  "client_secret": "...",
  "refresh_token": "...",
  "account_email": "user@example.com",
  "display_name": "User"
}
```

GEODE refuses Google login if the platform has no secure keyring backend; it
does not fall back to a plaintext token file. A refreshed access token is kept
in the in-memory `_TOKEN_CACHE` keyed by `account_id`, with its expiry, and is
discarded on daemon auth reload or logout. Google API responses are returned to
the active turn but are not added to this account store. Built-in durable tool
logs, transcripts, session-checkpoint JSON, and the SQLite message store replace
raw Workspace tool inputs and results with a `_personal_data_omitted` marker;
large Workspace results are never written to the tool-result offload store,
personal API error details are omitted from durable lifecycle telemetry, and a
batch containing a personal tool skips the secondary reflection provider so its
hypotheses cannot retain a result excerpt. The marker preserves the tool name;
its enclosing tool row preserves the call ID so a resumed session can explain
that the operation must be invoked again with consent. Separate rotating
runtime logs do not intentionally copy Workspace result payloads, but may retain
bounded Google API error diagnostics and follow the normal operational-log
retention policy. Text the user types directly, or an assistant summary already
written into ordinary conversation text, still follows GEODE's general
session-retention policy.

Account operations:

- `/login google status` lists non-secret account/bundle status.
- `/login google use <email>` changes `active_account_id` atomically.
- `/login google --new-account --services a,b` connects another identity
  without inheriting the active account's bundles.
- `/login google --services a,b --replace-services` replaces, rather than
  unions, the active account's requested bundle set during reauthorization.
- `/login google logout [email]` revokes the grant first, then removes the
  keyring value and registry row. `--local-only` skips remote revocation.
- Reauthorization preserves the account's original `created_at`, replaces its
  keyring value, and persists only scopes Google actually granted.

## Agent data controls

Google Workspace's July 2026 developer policy explicitly calls out MCP, tool,
skill, and other agentic invocations. Reads that can send personal Workspace
content to the configured LLM require an in-context affirmative confirmation
immediately before every invocation. They cannot be session-wide
always-allowed and are denied in headless and sub-agent sessions. Mutations use
the same non-cacheable per-invocation boundary: HITL level 0, a cached write
approval, and `--dangerously-skip-permissions` cannot bypass it. The raw
`google-calendar` and `caldav` MCP tools remain adapter-only, so model calls go
through the gated native `calendar_*` surface. A read-only Google grant also
cannot capture a write: the composite adapter skips it and tries a writable
legacy Calendar adapter. Neither result data nor credentials may be used to
train a general model.

The API client sends bearer tokens only to an HTTPS hostname on its explicit
Google Workspace allowlist. It refreshes once after a 401, bounds API error
text, and never includes a credential in a tool result.

## Hermes comparison

Hermes solves the same self-hosted distribution problem through its bundled
`google-workspace` Skill and scripts rather than a first-class slash command
and tool registry:

| Concern | Hermes Agent | GEODE |
|---|---|---|
| Entry point | Agent follows `SKILL.md`, then runs `setup.py` / `google_api.py` | User runs `/login google`; tools are registered runtime capabilities |
| OAuth client | User-owned Desktop client | User-owned Desktop client |
| Callback | `localhost:1`, then user copies the failed redirect URL back; useful across remote chat surfaces | Random `127.0.0.1` listener in the local thin CLI; no auth code enters the conversation |
| PKCE/state | PKCE and state, with pending verifier/state persisted for the split flow | PKCE and state held in memory for a one-shot local flow |
| Credentials | `google_client_secret.json` and `google_token.json` under `~/.hermes`; pending auth is another JSON file | Refresh token, client secret, and account label in OS keyring; metadata-only JSON; access token in memory |
| Accounts | Fixed token path; upstream multi-account request remains open | Versioned multi-account registry and active-account switch |
| Scope selection | Skill prose describes `--services`, while the inspected `setup.py` parser and `SCOPES` list still request the broad fixed set; this is a source/docs drift to watch | Executable named bundles, explicit first-login choice, reauth union, actual-grant persistence |
| Operations | Broad script/gws surface, including share/delete flows | Curated 11-tool surface plus existing Calendar tools; no whole-Drive scope |
| Approval | Procedural rules in the Skill tell the agent to confirm writes | Executor-enforced per-invocation personal-data and write gates |

The useful Hermes ideas retained are BYO client ownership, a service-oriented
setup guide, PKCE/state, revocation, and broad Workspace coverage. GEODE changes
the trust boundary: secrets do not live in JSON, a local browser callback does
not pass through the model conversation, account selection is native, and
policy gates are executable rather than prompt-only.

## Primary references

- [OAuth 2.0 for Desktop Apps](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Google Workspace API user data and developer policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)
- [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)
- [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Google Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Calendar authorization](https://developers.google.com/workspace/calendar/api/auth)
- [Docs authorization](https://developers.google.com/workspace/docs/api/auth)
- [Sheets scopes](https://developers.google.com/workspace/sheets/api/scopes)
- [Tasks authorization](https://developers.google.com/workspace/tasks/auth)
- [People API authorization](https://developers.google.com/people/v1/how-tos/authorizing)
- [Hermes Google Workspace Skill](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/google-workspace/SKILL.md)
- [Hermes OAuth setup script](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/google-workspace/scripts/setup.py)
- [Hermes Google API wrapper](https://github.com/NousResearch/hermes-agent/blob/main/skills/productivity/google-workspace/scripts/google_api.py)
- [Hermes multi-account request](https://github.com/NousResearch/hermes-agent/issues/15602)
