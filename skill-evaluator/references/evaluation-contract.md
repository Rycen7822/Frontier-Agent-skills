# Evaluation Contract

This file owns spec schema v3, evaluation levels, canonical variants, fairness, and claim ceilings. Freeze it before collecting runtime evidence.

## Decision and claim ceiling

Record one decision: static audit, diagnosis, scoped incremental usefulness, release/high-risk readiness, or version-cycle monitoring. Also freeze the target Skill, agent/model/harness, task distribution, risk, authority, artifacts root, and maximum claim.

Evaluation permission never grants permission to install dependencies, expose secrets, use networks, mutate persistent state, publish, deploy, or perform destructive, privileged, financial, or sensitive actions. Freeze those permissions separately.

## Spec v3 owner

`schema_version=3` is the only accepted behavioral contract. It binds:

- evaluation identity, level, risk, decision, and claim scope;
- candidate path/inventory hash, revision, source-tree hash, plugin-tree hash, and every declared variant's package, catalog, and treatment hashes;
- agent/model/harness, environment and tool/catalog identities, timeout, reset, seed, and network/credential policy;
- case and optional holdout assets, repeats, ordering, retry policy, graders, metrics, gates, authority, and artifact retention;
- `ready_for_scored_run`, which is `false` for public L1/L2 templates and must be explicitly closed before scored execution.

L0 omits behavioral ceremony. L1 has cases, graders, one diagnostic candidate variant, and `ready_for_scored_run=false`, but no comparative analysis/metrics/gates. L2+ owns comparative analysis and guardrails. L3/high-risk adds holdout and manual-review authority.

Placeholders are valid only in their exact non-ready forms. A public example that validates with warnings is a template, not a run receipt or usefulness result.

## Levels

| Level | Required evidence | Claim ceiling |
|---|---|---|
| L0 | Whole-package inventory, links, code/resource review | Static findings only |
| L1 | Focused explicit/implicit/contextual/negative cases with verified receipts | Diagnosis only |
| L2 | Frozen baseline/candidate plan, required graders, case-level intervals, benefit/context/protected/safety gates | Scoped incremental usefulness |
| L3 | L2 plus sequestered holdout, adversarial controls, environment pinning, and required manual-review receipt | Readiness for the tested scope and environment |
| L4 | Version lineage and repeated frozen evaluation cycles | Version and cycle monitoring only |

L4 is limited to version and cycle monitoring. Without selection, order, and composition receipts, it must not claim library-scale multi-Skill orchestration evidence.

## Canonical variants

| Profile | Purpose |
|---|---|
| `baseline/skill_disabled` | Base-model capability under identical task and controls; required at L2+ |
| `candidate/natural_routing` | Complete retrieval, loading, application, outcome, and context path; one valid L2+ candidate treatment |
| `candidate/force_loaded` | Explicit-invocation contribution without a routing claim; the other valid L2+ candidate treatment |
| `prior/natural_routing` | Optional natural-routing revision comparator |
| `prior/force_loaded` | Optional explicit-invocation revision comparator |

Declare only candidate treatments required by the decision. Natural routing is the default comparison when both candidate modes are present; selecting forced loading requires an explicit analyzer candidate. A force-loaded arm can establish incremental value for an explicit-only Skill only when the task text is byte-identical across arms, the native Skill selection is outside that text, and baseline exposes no Skill name, path, body, catalog hint, or treatment label. It cannot prove natural routing. A prior variant must match the selected candidate treatment and is not a substitute for the no-Skill baseline when the question is incremental value over the frontier model.

## Fair case and repeat design

Run the same frozen case, fixture, agent/model, harness, tools, permissions, timeout, reset, graders, and capture policy in each comparable arm. Keep candidate bytes and cache effects out of baseline context. Counterbalance order when time, service drift, quotas, or caching can favor an arm.

Repeats and cases have different roles:

1. pair `(case_id, repeat)` rows to diagnose missing, invalid, win, loss, and tie behavior;
2. average repeat-level candidate-minus-baseline outcomes inside each distinct case;
3. resample the distinct case means for inference.

Repeats never increase `paired_case_count`. Fewer than two complete independent cases cannot produce an interval. A positive point estimate cannot replace the frozen lower-bound benefit gate.

## Isolation and provenance

Every run index points to one hashed receipt under `spec.artifacts.root`. The analyzer recomputes spec, case, environment, package, fixture set, grader, artifact, and invocation bindings before deriving any result, and matches the receipt to the frozen candidate revision/source/plugin identity. Catalog/treatment IDs and private contract/schedule/controller hashes remain external attestations, not cryptographic proof.

Keep cases, hidden graders, holdout payloads, and evaluation-controller instructions outside the tested executor context unless the deployment contract genuinely supplies them. Preserve invalid apparatus rows, treatment failures, retries, timeouts, and raw artifacts under their declared semantics.

## Holdout and manual authority

L3/generalization evidence uses a separately stored holdout payload and manifest with ordered case IDs, per-case hashes, payload hash, custodian, exposure state, and refresh state. Visible example holdouts must be replaced, access-controlled, and rehashed.

When manual review is required, the sole authority input is one contained, hashed JSON receipt whose role and evidence types exactly match the spec. `approve` completes that authority gate; `hold` or `reject` blocks final-authority eligibility without rewriting empirical usefulness. The signature is an attestation unless an external system separately proves it.

## Contract changes

Changing cases, fixtures, requirements, graders, thresholds, environment, model, harness, catalog, reset, or capture semantics creates a new evidence contract. Record the reason, identify invalidated comparisons, rerun every affected arm, preserve the prior cycle, and disclose the boundary. Never tune acceptance after observing only the candidate.
