# Review Result Schema 2.0

This file is the single normative owner for review-result fields, types, enumerations, and consistency rules. Review routers, specialist rubrics, prompts, local renderers, and platform renderers consume this contract; they must not redefine it.

`schema_version` appears once on the result envelope. Its value applies to every nested finding, coverage entry, and optional note; findings do not repeat the version field.

Version 2.0 is a breaking freshness repair: it binds the result and every coverage entry to the frozen scope manifest. A 1.0 result lacks that proof and must be re-reviewed against the manifest; do not add the new fields after the fact or silently reinterpret it as 2.0.

## Contents

- [Envelope](#envelope)
- [Finding](#finding)
- [Coverage](#coverage)
- [Result dimensions](#result-dimensions)
- [Consistency rules](#consistency-rules)
- [Optional presentation data](#optional-presentation-data)
- [Validation and failure handling](#validation-and-failure-handling)
- [Example](#example)

## Envelope

Every result is a JSON object with these required fields and no inferred substitutes:

| Field | Type | Contract |
|---|---|---|
| `schema_version` | string | Exactly `2.0`; governs the entire envelope |
| `code_review_verdict` | enum | `pass`, `changes_requested`, or `inconclusive` |
| `verification_status` | enum | `passed`, `failed`, `partial`, or `not_run` |
| `merge_readiness` | enum | `ready`, `blocked`, `unknown`, or `not_applicable` |
| `external_approvals` | enum | `satisfied`, `missing`, `unknown`, or `not_applicable` |
| `coverage` | array | Coverage entries defined below |
| `blocking_reasons` | array of strings | Blocking finding IDs and concise non-finding reasons |
| `reviewed_base_sha` | string | Exact reviewed base revision or `not_applicable` |
| `reviewed_head_sha` | string | Exact reviewed head/snapshot identifier |
| `reviewed_scope_hash` | string | Exact hash of the frozen manifest, including path snapshots |
| `findings` | array | Finding objects defined below |

The revision strings may be commit IDs, immutable artifact digests, or another manifest-defined snapshot identifier. Do not silently substitute the current revision for the revision actually reviewed.

## Finding

Every finding requires:

| Field | Type | Contract |
|---|---|---|
| `id` | string | Unique, stable within the envelope |
| `severity` | enum | `critical`, `high`, `medium`, `low`, or `info` |
| `blocking` | boolean | Independent of severity and category |
| `category` | string | Non-empty, stable lower-snake-case domain label |
| `path` | string | Exact allowlisted manifest path or observable-contract identifier |
| `line` | integer or null | One-based start line; null only when no stable source line exists |
| `evidence` | string | Concrete observed behavior, code, or evidence gap; never an unsupported assertion |
| `impact` | string | Plausible consequence for users, data, security, compatibility, or code health |
| `recommended_fix` | string | Smallest safe correction or next evidence/decision needed |
| `confidence` | enum | `high`, `medium`, or `low` |
| `verification` | string | Proof observed, proof missing, or explicit `not_run` reason |
| `code_fixable` | boolean | Whether a scoped source edit can resolve this finding |
| `source_revision` | string | Must equal `reviewed_head_sha` |

Use a manifest-listed logical identifier such as `contract:service-readiness` when the evidence is an observable contract rather than a file. Such identifiers must be in the same allowlist used by validation. Put an end line or other range detail in `evidence` when needed; `line` remains the start line.

Categories are extensible because specialist domains evolve. Prefer stable labels such as `correctness`, `security`, `data_loss`, `compatibility`, `maintainability`, `testability`, `design`, `evidence`, `ml_ai`, `observability`, `operability`, `product`, `api`, `accessibility`, `privacy`, `testing`, `ci_release`, or `supply_chain`.

An evidence gap, missing specialist judgment, human decision, or external approval normally has `code_fixable=false`. Do not send it to a code fixer merely because it is blocking.

## Coverage

Each coverage entry requires:

```json
{"path": "src/example.py", "status": "full", "snapshot_id": "sha256:..."}
```

`status` is one of:

- `full`: relevant change and owning context were reviewed;
- `sampled`: a declared portion was reviewed and the sampling boundary is recorded in the report;
- `not_reviewed`: the item was unavailable, truncated, excluded after manifest creation, or otherwise unread.

`snapshot_id` is the immutable content, diff/base, deletion, rename, artifact, or equivalent identifier recorded for that path in the frozen manifest. It must match that manifest exactly; the reviewed head alone cannot detect same-HEAD dirty-worktree or untracked-file drift.

Coverage paths use the same manifest identifiers as findings. Every in-scope path appears once. Generated, vendor, binary, deleted, renamed, and untracked items remain visible even when their review depth differs.

Validation receives the frozen manifest allowlist separately from the envelope. Each coverage path must be a unique, non-empty member of that allowlist, and every allowlisted path must have exactly one coverage entry. An empty or sampled scope may support an explicitly limited technical judgment, but it cannot support `merge_readiness=ready`; machine-validated readiness requires non-empty `full` coverage for the entire allowlist.

## Result dimensions

The four result dimensions answer different questions:

- `code_review_verdict` judges the reviewed code and available context.
- `verification_status` reports execution evidence; it does not claim code approval.
- `merge_readiness` combines known technical and process constraints for the requested landing context.
- `external_approvals` reports only authoritative human or platform approval evidence.

A technical `pass` may coexist with missing external approvals or incomplete verification, but that does not make the change ready. Conversely, successful tests do not erase a blocking code finding.

Use `inconclusive` when missing scope, unread content, stale revision, or specialist evidence prevents a safe technical judgment. Use `not_applicable` only when that dimension truly does not apply, not as a substitute for unknown information.

## Consistency rules

Validation must reject these states:

- any required field is absent or has the wrong type;
- any enum value is outside this document's set;
- finding IDs are duplicated;
- coverage paths are empty, duplicated, outside the manifest allowlist, or omit an allowlisted path;
- a coverage `snapshot_id` is empty or differs from the path snapshot in the frozen manifest;
- a finding path is outside the scope allowlist;
- a finding `source_revision` differs from `reviewed_head_sha`;
- the reviewed base, head, or scope hash differs from the frozen manifest;
- the current head or recomputed current scope hash differs from the frozen manifest;
- a blocking finding ID is absent from `blocking_reasons`;
- a blocking finding coexists with `code_review_verdict=pass`;
- a non-empty `blocking_reasons` list coexists with `code_review_verdict=pass`;
- `not_reviewed` coverage coexists with `code_review_verdict=pass`;
- `merge_readiness=ready` with empty, sampled, malformed, or `not_reviewed` coverage;
- `merge_readiness=ready` while the technical verdict is not `pass`, the revision is stale, or a blocking reason remains;
- `merge_readiness=ready` while verification is not passed;
- `merge_readiness=ready` while external approvals are missing or unknown.

For a ready-to-land claim, also require a passing technical verdict, fresh revision, no blocking reasons, sufficient declared coverage, and every approval required by the actual workflow either satisfied or genuinely not applicable.

Severity never determines blocking by itself. A high-severity observation can be non-blocking when outside the current landing decision, and a medium-severity issue can block when it violates a required contract. Renderers must display both fields.

## Optional presentation data

Renderers may add `summary` and `positive_notes` without changing the required contract. A positive note should identify the manifest path or contract, line when available, observed strength, and reviewed revision. It is preservation input for a fixer, not approval evidence.

Do not mutate an immutable review result to record later work. Maintain a separate disposition ledger mapping each finding ID to the accepted fix, re-verification, evidence-backed rejection, accepted residual risk, or explicit deferral.

## Validation and failure handling

The controller validates JSON types, required fields, enums, manifest path snapshots, coverage completeness, consistency, and freshness before using the result. The frozen scope manifest plus a separately re-observed current head and current scope hash are mandatory validator inputs; a structural-only parse without that context must not return a schema-conformant or ready result. The manifest supplies the expected base, expected head, expected scope hash, path statuses, and path snapshot identifiers. Reviewer text, even valid JSON, remains untrusted evidence until factual claims are checked.

If output is invalid, retry once with the same scope and an explicit request to conform to this schema. Do not widen inputs or silently repair a substantive contradiction. If the second output is invalid, report reviewer evidence unavailable and keep the technical result inconclusive.

Platform summaries and inline comments must render from the same validated envelope. Publication is a separate authorized action and must stop when the reviewed revision is stale.

## Example

```json
{
  "schema_version": "2.0",
  "code_review_verdict": "changes_requested",
  "verification_status": "partial",
  "merge_readiness": "blocked",
  "external_approvals": "not_applicable",
  "coverage": [{"path": "src/parser.py", "status": "full", "snapshot_id": "sha256:parser-head"}],
  "blocking_reasons": ["F-001"],
  "reviewed_base_sha": "base-snapshot",
  "reviewed_head_sha": "head-snapshot",
  "reviewed_scope_hash": "sha256:frozen-manifest",
  "findings": [
    {
      "id": "F-001",
      "severity": "high",
      "blocking": true,
      "category": "security",
      "path": "src/parser.py",
      "line": 42,
      "evidence": "The changed parser accepts a parent-traversal segment before normalization.",
      "impact": "An untrusted archive entry can escape the intended extraction root.",
      "recommended_fix": "Reject unsafe segments before extraction and add a focused contract case.",
      "confidence": "high",
      "verification": "Static path trace only; focused negative proof not run.",
      "code_fixable": true,
      "source_revision": "head-snapshot"
    }
  ]
}
```
