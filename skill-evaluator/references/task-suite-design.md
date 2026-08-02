# Task-Suite Design

This file owns the frontier-model scenario filter, scenario v1 semantics, coverage boundaries, protected controls, split/holdout design, and suite-quality preparation.

## Frontier-model case filter

The target is incremental help for a frontier model, not a quiz on knowledge it already possesses. Include a case only when it tests at least one specialized mechanism:

- correct Skill routing among plausible alternatives;
- package-specific procedure, artifact, verifier, reference, permission, or cleanup behavior;
- state or tool interaction whose success is inspectable;
- a context-cost tradeoff created by loading this Skill;
- a confirmed regression, safety boundary, or deployment-specific requirement.

Exclude generic reasoning, common programming facts, generic writing advice, framework ceremony, and prompts that only reward restating the Skill. A difficult prompt is not useful by itself; it needs a credible path for the Skill to improve the frontier model over the no-Skill baseline.

Start with the smallest suite covering materially different intents, states, risks, and failure mechanisms. Suite size comes from the frozen coverage and uncertainty contract, not a package-wide numeric default.

## Scenario v1 and requirements

Each JSONL row freezes `case_id`, split/tags/risk, applicable treatment profiles, fixture manifest/hash, catalog overlay, execution context, ordered turns, state model, typed faults, `requirements[]`, timeout, and attribution eligibility. Coordination, exact routing/composition, and observation contracts exist only when their module is active. The schema is the field-shape owner; this document defines how to choose evidence.

Each requirement has exactly one semantic owner:

| Field | Meaning |
|---|---|
| `requirement_id` | Stable scenario-global requirement ID |
| `dimension` | One declared outcome, activation, composition, process, state, recovery, quality, safety, reliability, cost, compatibility, or grounding dimension |
| `required` | Whether failure changes required overall pass |
| `owner` | Exactly `deterministic` or `model`, matching the selected grader type |
| `grader_id` / `check_id` | Exact selected grader/check join |
| `checkpoint` | Turn, final, or cleanup evidence boundary |
| `obligation` / `transition_id` | Optional joins to declared state/recovery contracts |
| `safety_severity` / `safety_kind` | Non-null only for safety requirements |

Outcome and safety requirements are required. Process/state/recovery requirements encode observable transitions and obligations, not private reasoning. Optional failures remain visible but do not change required-only `overall_pass`. Safety requirements bind hard gates and remain unweighted guardrails.

Do not add parallel outcome/process/forbidden/oracle arrays. The canonical requirements join is the only source for selected checks, scores, dimensions, safety counts, and hard-failure requirement IDs.

## Turns, state, faults, and observations

The compact form is one user turn, `state_model.scope="none"`, no faults, and requirements due at `final`. It is scenario v1, not a legacy-case compatibility path.

Stateful scenarios declare initial state, stable keys, allowed transitions, terminal states, reset, persisted-state authority, and expected cleanup. Turns declare open and due obligations. The runner verifies observed turn order, checkpoints, transitions, obligations, terminal state, and cleanup; final prose cannot replace state evidence.

Typed fault scripts bind surface, trigger, effect, duration, expected recovery, and a safety limit. Cover the failures the mechanism can actually encounter: structured/malformed results, schema drift, timeout/cancel/drop, quota/auth, missing MCP session, tool-list change, and partial side effects. A fault is evidence only when injection, observation, and recovery locators close.

Observation contracts keep bytes/schema/locator validity separate from temporal validity and grounding. Include fresh supported evidence and the relevant stale, wrong-bytes, or unsupported-source boundary. Retrieval or file existence alone never proves that a source supports a claim.

## Routing, composition, and coordination

Use `routing_contract` only for a declared routing or composition question. It fixes the target, optional pair/sequence shape, required evidence, and the exact declared/discovered/loaded/model-visible/selected/invoked/applied/order/composition expectation for every applicable treatment and turn. A legitimate no-match remains an explicit expected state.

Composition evidence is limited to the declared unordered pair or ordered sequence. Multi-principal coordination additionally freezes topology, decomposability, principal slots, dependency edges, handoff payload/authority/context, join/cancel/partial-result policy, and per-principal tool/policy/budget bounds. Include a single-principal equal-total-budget comparator when claiming topology value. Critique detection, uptake, repair, independence, and final outcome remain separate observations.

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

`attribution_evaluable=true` is reserved for scenarios whose baseline and candidate task text, non-Skill affordances, and success criteria are comparable. A native force-loaded treatment may enter incremental benefit for an explicit-only Skill when selection occurs outside byte-identical task text and baseline contains no Skill signal; it remains ineligible for natural-routing metrics. Pure negative controls do not enter incremental benefit.

## Protected controls

Use the existing exact tag `protected` for finite controls whose required outcomes must not regress. Do not add a case-role framework.

Every scored-ready L2+ suite has at least one protected case. Each protected case:

- sets `attribution_evaluable=false`;
- contains `baseline/skill_disabled` and the primary candidate profile (`candidate/natural_routing` when declared, otherwise `candidate/force_loaded`);
- has at least one required outcome requirement.

The analyzer counts every protected `case × selected treatment × repeat` plan key once. Missing, duplicate, invalid, or required-outcome-failed rows all increase `protected_outcome_failures`; observed-row filtering cannot hide them.

## Development, regression, and holdout

- `dev`: visible diagnosis and iteration; never independent generalization evidence.
- `regression`: an immutable confirmed failure after its fix.
- `heldout`: sequestered from authoring, routine prompts, and grader rationales until the decision.

For L3, the public scenario file contains no heldout rows and the holdout payload contains only heldout rows. Before the decision, `suite.scenarios` equals `public_scenarios`, the holdout status is `sealed`, and `execution.ready=false`. After the candidate is frozen, the custodian changes the copied manifest status to `exposed`, materializes `suite.scenarios` as the exact ordered, disjoint `public + heldout` union, and only then sets `execution.ready=true`. The compiler evaluates that union without copying heldout rows into the public file. The manifest binds payload bytes, ordered IDs, count, and each canonical scenario hash. Refresh before evaluating a later candidate or after a material distribution or contract change.

## Real state and safety fixtures

Pin or snapshot controllable state. Record timestamps and external state that cannot be pinned. Use isolated accounts/workspaces and inert data; never place real secrets or uncontrolled destructive targets in a probe. Capture the observation and post-state required by the grader, including screenshots or state exports when text is insufficient.

Static package findings and runtime behavior answer different questions. A contained unsafe attempt records both the attempted action and the harness block.

## Suite-quality preparation

Before L2–L4 execution, normalize a raw suite-quality proof against the non-ready draft spec. The artifact binds the acyclic quality contract, corpus/fixture/grader/treatment identities, optional calibration, golden/known-bad/mutation evidence, duplicate/provenance review, leakage/custody, coverage, grader sensitivity, authority, and its self-hash. It never reads candidate scored results.

Required preparation closes golden solvability, required mutation detection, duplicate/provenance review, leakage review, required slice/module/treatment/check coverage, and grader sensitivity. Required modules need positive and boundary/failure evidence unless the spec proves the finite set is exhausted. Model-only duplicate, leakage, or semantic observations require the declared reviewer receipt and locator.

The order is fixed: draft non-ready spec → optional selected-model calibration → suite-quality normalization → bind both artifacts and `quality_contract_hash` → set `execution.ready=true` → validate the final contract → compile.

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

After a confirmed failure, add the smallest regression scenario that preserves its mechanism, rerun affected treatments, and version the suite when semantics change.
