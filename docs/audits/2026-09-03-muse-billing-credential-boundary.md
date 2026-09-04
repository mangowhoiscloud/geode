# Muse Code Billing And Credential Boundary Audit

Date: 2026-09-03

Scope: Meta Muse Code billing/authentication claims, this host's observable
Muse installation and credential metadata, and GEODE's corresponding
provider-routing and local-secret boundary. No credential value was read,
printed, or sent to a network service.

## Executive Verdict

The billing warning is substantially correct, but two parts need narrower
wording. A Muse Code subscription is a bounded flat-rate plan, not unlimited:
Meta documents tier-specific usage limits. It applies only to the Muse Code
credential automatically connected during CLI onboarding. Any additional Meta
Model API key is pay-as-you-go, and an environment or stored API key takes
priority over a browser subscription session. Meta says the CLI warns when an
environment key masks that session; the public documentation does not establish
that a hidden PAYG toggle is enabled by default.

The claim that Muse stores a plaintext key in macOS Keychain for anyone to
extract was not reproduced. Meta's public Muse documentation says only that the
CLI stores the credential. An independent, version-pinned Muse Code 0.1.0
observation records `~/.config/muse/auth.json`, not Keychain. This host has no
Muse binary, application, package, process, config directory, related
environment-variable name, or Muse/Meta Model API Keychain metadata match.
Apple Keychain also is not plaintext disk storage: access is controlled per
item and may require an explicit user grant. A process running as the same
logged-in user is still an important threat when an item has permissive access
control, so an actual installed version must be audited by item ACL rather than
by extracting its secret.

GEODE does not implement a Muse/Meta provider and cannot silently select one.
Its equivalence routing prefers subscription/OAuth plans over API-key PAYG, and
OpenRouter is an explicitly selected, credit-backed PAYG provider. The audit did
find a separate local defect: `~/.geode/.env` had mode `0644`. The host file was
repaired to `0600`, and the shared dotenv and auth TOML persistence paths now
create and repair credential files as owner-only.

## Primary And Reproduction Evidence

- [Meta Muse Code authentication and billing](https://dev.meta.ai/docs/muse-code/auth)
  defines the credential order as environment API key, stored API key, then
  browser session; it also defines usage-based threshold/monthly charging.
- [Meta Muse Code subscriptions](https://dev.meta.ai/docs/muse-code/subscriptions)
  says the subscription applies only to the automatically connected Muse Code
  credential, while additional API keys are PAYG. It describes bounded
  Everyday, High, and Power usage tiers.
- [Meta Model API authentication](https://dev.meta.ai/docs/authentication)
  recommends unique keys, environment variables or a key manager, no committed
  credentials, monitoring, and immediate revocation on a leak.
- [Meta's public Muse release channel](https://api.meta.ai/muse-code/channels/muse-stable)
  reported `1.0.2-R2040.1` during this audit.
- [Apple Keychain access control](https://support.apple.com/en-euro/guide/mac-help/kychn002/mac)
  documents deny, allow-once, always-allow, and per-application access choices.
- [Independent Muse 0.1.0 verification](https://github.com/kunchenguid/firstmate/blob/main/docs/verification/muse.md)
  is supporting, not authoritative, evidence for the older `auth.json` storage
  path and `META_API_KEY` behavior.

## GAP Audit

| ID | Severity | Observation | Resolution |
|---|---:|---|---|
| MUSE-BILL-001 | P1 | Additional Meta API keys are PAYG even when the account also has a Muse Code subscription | Treat key identity, not account membership, as the billing boundary; never describe arbitrary API keys as subscription credentials |
| MUSE-BILL-002 | P1 | `META_API_KEY` and stored keys outrank browser sign-in | Prefer browser onboarding for subscription use and remove unintended environment keys; rely on the documented masking warning as detection, not prevention |
| MUSE-SEC-001 | P1, unverified product claim | Public docs do not disclose Muse's current on-disk/Keychain storage or ACL | Do not claim plaintext or universal retrieval without an installed-version ACL observation; inspect metadata and access control without revealing the value |
| GEODE-SEC-001 | P1, fixed | The global GEODE dotenv containing PAYG keys was readable by other local accounts (`0644`) | Repair the current file and enforce `0600` in the shared dotenv and auth TOML persistence paths with regression tests |
| GEODE-BILL-001 | Closed | GEODE could have auto-routed a prepaid request to PAYG | Existing plan-kind priority chooses subscription/OAuth before PAYG; explicit model routing remains operator-controlled |

## Safe Operator Check

For Muse Code subscription use, authenticate through the CLI's browser flow and
verify that no unintended `META_API_KEY` export remains in the launching
environment. A separately created dashboard API key must be assumed PAYG. Use
the billing and usage dashboards to confirm the selected account and accrued
charges before a long agent run.

On macOS, inspect a matching Keychain item's Access Control pane if an installed
Muse release creates one. Do not use `security ... -w`, copy the secret, or put
it in a diagnostic log. “Stored in Keychain” is not itself a vulnerability;
the finding would require an overly broad ACL or a same-user process that can
read the item without the intended approval boundary.

## GEODE Residual Boundary

GEODE LLM API keys remain local plaintext in ignored dotenv/auth TOML files,
protected by owner-only file permissions. This prevents access by another local
account but not by a process already executing as the GEODE user. Moving all
LLM credentials to OS keyrings would be a separate compatibility and migration
change; it is not required to close this permission defect and must not be
presented as protection from a fully compromised same-user session.
