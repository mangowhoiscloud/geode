# Skill Transparency And Sensitive-Data Audit

Date: 2026-08-25

Scope: repository development/meta skills, bundled runtime skills, and the
reported `agent-world-benchmark` / `anti-deception-checklist` findings.

## Executive Verdict

The feedback identifies one real security defect and two valid contract gaps.
`agent-world-benchmark` does not implement cryptography: its hash fields are
reproducibility identities for non-secret artifacts. The missing scope boundary
made that distinction hard to audit. Its sensitive-data exclusions were also
too terse. More seriously, `anti-deception-checklist` used recursive `grep`
commands that printed the full matching line, so a check for a credential could
copy that credential into terminal or CI logs.

The repository also had a transparency/provenance gap. Most meta skills were
tracked only under the Claude Code surface while local `.agents` copies were
uncommitted. Several local copies contained stale paths or blind host-name
substitutions. Publishing those bytes unchanged would have made the public
surface less correct.

## Why Skill Text Is A Security Boundary

The open Agent Skills specification defines a skill as instructions plus
optional executable scripts and resources. The full instruction body is loaded
after activation, and scripts may be executed. A skill therefore belongs to the
instruction supply chain, not merely to prose documentation. Repository
visibility, one canonical copy, and explicit data handling make review and
incident response possible.

Primary references:

- [Agent Skills specification](https://agentskills.io/specification) — skill
  structure, progressive disclosure, executable resources, and validation.
- [Agent Skills client guidance](https://agentskills.io/client-implementation/adding-skills-support) — shared `.agents/skills`
  discovery and cross-client visibility.
- [NIST SP 800-57 Part 1 Rev. 5](https://csrc.nist.gov/pubs/sp/800/57/pt1/r5/final) — a real cryptographic service requires explicit security service,
  algorithm/key type, protection, and lifecycle decisions.
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude) — access tokens, passwords,
  sensitive PII, and encryption keys should not be recorded directly in logs.
- [GitHub secret remediation](https://docs.github.com/en/code-security/tutorials/remediate-leaked-secrets/remediating-a-leaked-secret) — removing a line is insufficient; revoke the credential first.

## GAP Audit

| ID | Severity | Observation | Meaning | Resolution |
|---|---:|---|---|---|
| SKILL-SEC-001 | P1 | Secret checks used `grep -rn`, which prints matched lines | Detection could create a second leak in logs | Use filename-only `git grep -Il`; define stop, rotate/revoke, and cleanup order |
| SKILL-SEC-002 | P2 | Benchmark manifests require several `* hash` fields but stated no cryptographic boundary | Reviewers could mistake artifact identity for confidentiality or signature behavior | Explicitly state that no keys/encryption/signing/certificates are owned and forbid ad-hoc primitives |
| SKILL-SEC-003 | P1 | Private prompts, OAuth material, and account identifiers were excluded from publication without an end-to-end handling rule | Source, storage, prompt/log, and incident behavior were ambiguous | Add a data-class table, minimization, private-store, redacted-publication, and no-secret-hashing rules |
| SKILL-TRN-001 | P1 | Meta skills had split tracked/untracked authorities | Host behavior and public review could diverge | Make `.agents/skills` canonical and `.claude/skills` relative aliases |
| SKILL-TRN-002 | P1 | Some untracked drafts contained obsolete package paths and mechanical `Claude`→`Codex` substitutions | Blind publication would activate false instructions | Promote current tracked bytes; replace three unpaired stale drafts with minimal current contracts |
| SKILL-COMPAT-001 | P2 | 18 skills used host-only frontmatter fields rejected by the Agent Skills reference validator | Cross-client discovery depended on lenient parsing | Move invocation guidance into standard description/body fields and validate the whole canonical tree |
| SKILL-SEC-004 | P2 | The newly published Scandinavian design skill bundles browser and screenshot scripts without an explicit data boundary | A visual verification artifact can disclose authenticated page content | Limit navigation to user-approved URLs, isolate output, and forbid private pages, credentials, cookies, and unreviewed publication |

No current evidence shows encryption, decryption, signing, verification,
certificate processing, or key generation in `agent-world-benchmark`. If any of
those behaviors are later introduced, SKILL-SEC-002 becomes a new security
design review rather than a documentation edit.

## Canonical Surfaces

After remediation:

- `.agents/skills/` contains all 34 tracked development and meta skills.
- `.claude/skills/` contains 34 relative aliases and no competing copies.
- `.geode/skills/` contains 11 runtime contracts discovered by `core/skills/`:
  eight immutable wheel payloads and three explicit project-only workflows.
  Package validation requires the eight and rejects the project-only three.
- `docs/scaffold-skills.md` lists both surfaces; the policy test checks that the
  list, canonical directories, aliases, and runtime-overlap rules agree.

The migration used the previously tracked `.claude` bytes as authority. The
only new local-only asset retained in full was `scandinavian-design`, with an
added browser/screenshot safety boundary. The
unpaired `codex-mcp-verify`, `model-onboarding`, and `smoke-green-loop` drafts
were reduced to current, host-safe contracts; obsolete hard-coded auth paths,
model catalogs, PR history, and package paths were intentionally not published.

## Sensitive-Data Contract

1. Credentials enter only through the existing provider/environment/OS
   credential path; a skill does not inspect that path to prove a value exists.
2. Secret, private-key, password, token, PII, account, and private-prompt values
   never enter manifests, CLI arguments, model/reviewer prompts, logs, PRs, or
   public artifacts.
3. Hashes are generated only from canonical non-secret artifacts. A hash is not
   encryption or redaction and is not used to disguise a secret.
4. Private benchmark evidence is minimized and retained only in the configured
   private evidence location. Public evidence is aggregated, opaque, or
   redacted.
5. A suspected real credential stops the workflow. Report only file and secret
   class, revoke or rotate first, then coordinate history/cache cleanup.

## Verification Contract

The change is complete only when:

- every `.agents/skills/*/SKILL.md` has a relative resolving Claude alias;
- every canonical skill passes the Agent Skills frontmatter field contract;
- every development and runtime skill is named in the public inventory;
- overlapping runtime/development skills remain thin routers;
- the two reviewed skills retain their cryptography and sensitive-data
  boundaries;
- no content-echoing secret-search command returns; and
- repository, documentation, and package gates remain green.

This audit does not claim a general-purpose secret scanner. GitHub push
protection and provider-side detection remain complementary controls; the
skill's local check is deliberately a non-echoing tripwire, not a credential
classification engine.
