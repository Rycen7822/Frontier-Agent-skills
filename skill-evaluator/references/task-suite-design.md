# Task-Suite Design

This file owns the frontier-model case filter, canonical requirements, coverage boundaries, protected controls, and split/holdout design.

## Frontier-model case filter

The target is incremental help for a frontier model, not a quiz on knowledge it already possesses. Include a case only when it tests at least one specialized mechanism:

- correct Skill routing among plausible alternatives;
- package-specific procedure, artifact, verifier, reference, permission, or cleanup behavior;
- state or tool interaction whose success is inspectable;
- a context-cost tradeoff created by loading this Skill;
- a confirmed regression, safety boundary, or deployment-specific requirement.

Exclude generic reasoning, common programming facts, generic writing advice, framework ceremony, and prompts that only reward restating the Skill. A difficult prompt is not useful by itself; it needs a credible path for the Skill to improve the frontier model over the no-Skill baseline.

Start with the smallest suite covering materially different intents, states, risks, and failure mechanisms. Ten to twenty cases is a practical L2 starter, not a statistical guarantee.

## Canonical case and requirements

Each JSONL case freezes identity, split/tags, exact prompt, trigger truth, allowed Skills, fixture manifest/hash, timeout, risk, applicable variant profiles, and `requirements[]`. Optional authority/distractor/adversarial/citation lists exist only when the case needs them.

Each requirement has exactly one semantic owner:

| Field | Meaning |
|---|---|
| `id` | Stable case-global requirement ID |
| `dimension` | `outcome`, `process`, `quality`, or `safety` |
| `required` | Whether failure changes required overall pass |
| `grader_id` / `check_id` | Exact selected grader/check join |
| `weight` | Optional; either all case requirements have weights or none do |
| `severity` / `safety_kind` | Required only for safety requirements |

Outcome and safety requirements are required. Process requirements encode necessary observable invariants, not an exact reasoning trace. Quality may be optional. Safety requirements bind hard-gate graders and remain unweighted guardrails in final decisions.

Do not add legacy outcome/process/forbidden/oracle arrays. The canonical requirements join is the only source for selected checks, scores, dimensions, safety counts, and hard-failure requirement IDs.

## Coverage boundaries

Use cases that differ in a decision-relevant way:

- intended explicit, implicit, and realistic contextual requests;
- adjacent negative and ambiguity controls;
- representative artifact-producing work and changed fixtures;
- missing, stale, malformed, partial, or unsupported state;
- required recovery, termination, verification, and cleanup;
- inert permission, injection, secret/canary, network, destructive, or persistence probes when the package can reach those surfaces;
- rubric-scored conventions only when deterministic verification cannot own them.

Positive prompts must not all copy the Skill description. Negative prompts should be plausible near misses. Keep alternative valid processes valid unless the procedure itself is the specialized value being evaluated.

`attribution_evaluable=true` is reserved for cases whose baseline and candidate prompts/affordances are comparable. Explicit forced invocation and pure negative controls can still grade routing or safety but do not enter incremental benefit.

## Protected controls

Use the existing exact tag `protected` for finite controls whose required outcomes must not regress. Do not add a case-role framework.

Every scored-ready L2+ suite has at least one protected case. Each protected case:

- sets `attribution_evaluable=false`;
- contains both `baseline/skill_disabled` and `candidate/natural_routing` profiles;
- has at least one required outcome requirement.

The analyzer counts every protected `case × selected arm × repeat` plan key once. Missing, duplicate, invalid, or required-outcome-failed rows all increase `protected_outcome_failures`; observed-row filtering cannot hide them.

## Development, regression, and holdout

- `dev`: visible diagnosis and iteration; never independent generalization evidence.
- `regression`: an immutable confirmed failure after its fix.
- `heldout`: sequestered from authoring, routine prompts, and grader rationales until the decision.

For L3, the public cases file contains no heldout rows and the holdout payload contains only heldout rows. The manifest binds payload bytes, ordered IDs, count, and each canonical case hash. Refresh after exposure or a material distribution/contract change.

## Real state and safety fixtures

Pin or snapshot controllable state. Record timestamps and external state that cannot be pinned. Use isolated accounts/workspaces and inert data; never place real secrets or uncontrolled destructive targets in a probe. Capture the observation and post-state required by the grader, including screenshots or state exports when text is insufficient.

Static package findings and runtime behavior answer different questions. A contained unsafe attempt records both the attempted action and the harness block.

## Suite review

Before freezing the suite, confirm:

- every claimed behavior and non-target boundary has a case or explicit exclusion;
- each case survives the frontier-model filter and adds non-duplicate coverage;
- baseline and candidate use identical success criteria where contribution is claimed;
- every requirement maps to one declared grader/check;
- routing positives/negatives, safety probes, and protected controls match the claim;
- fixtures and IDs are immutable and usable without hidden secrets;
- holdouts are truly sequestered;
- suite size and repeats are justified by coverage and uncertainty rather than benchmark theater.

After a confirmed failure, add the smallest regression case that preserves its mechanism, rerun affected arms, and version the suite when semantics change.
