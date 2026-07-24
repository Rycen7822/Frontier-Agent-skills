# Evaluation Contract

This file owns eval-spec v5 semantics, evaluation levels, applicability, treatments, preparation, fairness, and claim ceilings. JSON Schema owns shape; `validate_eval_suite.py` owns cross-field and cross-file semantics. Freeze both before compiling a plan.

## Decision and claim ceiling

Record one decision: static audit, diagnosis, scoped incremental usefulness, release/high-risk readiness, or version-cycle monitoring. Also freeze the target Skill, agent/model/harness, task distribution, risk, authority, artifacts root, and maximum claim.

Evaluation permission never grants permission to install dependencies, expose secrets, use networks, mutate persistent state, publish, deploy, or perform destructive, privileged, financial, or sensitive actions. Freeze those permissions separately.

## Spec v5 owner

`schema_version=5` is the only accepted contract. It binds:

- immutable evaluation, decision, subject, risk, claim, package, source, plugin, model, harness, host, catalog, policy, and authority identities;
- one decision for every applicability module, with evidence and approver;
- `execution.mode`, owner-supplied `as_of`, readiness, timeout, reset, retry, order, network, credential, and parallelism boundaries;
- scenario, holdout, fixture, grader, treatment, calibration, suite-quality, analysis, gate, artifact, retention, redaction, and cleanup contracts.

L0 permits only the static subset and keeps `execution.ready=false`. L1–L4 add the behavioral fields. `execution.ready=true` means preparation is closed enough to compile; it does not mean every host capability is supported or that an evaluation passed. Public L1/L2 templates intentionally keep `execution.ready=false`. The deleted `ready_for_scored_run` field has no v5 reader.

Each spec declares exactly one decision for every module: `core_outcome`, `natural_routing`, `catalog_routing`, `declared_composition`, `multi_principal_coordination`, `multi_turn_state`, `tool_faults`, `host_conformance`, `dynamic_security`, and `longitudinal`. A `not_applicable` decision requires a reason, evidence, and approval and never means that the candidate passed. Subject shape and mechanisms determine which modules must be required.

Selected model graders require a bound, unexpired blinded calibration artifact. L2–L4 require a bound suite-quality artifact; L1 may bind one. `quality_contract_hash` excludes the quality artifact path/hash, readiness, outputs, timestamps, and candidate results, so the spec-to-quality binding is acyclic. Validator-produced calibration and quality artifacts are preparation evidence, never candidate score evidence.

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

## Treatment registry

| Profile | Purpose |
|---|---|
| `baseline/skill_disabled` | Base-model capability under identical task and controls; required at L2+ |
| `candidate/natural_routing` | Complete retrieval, loading, application, outcome, and context path; one valid L2+ candidate treatment |
| `candidate/force_loaded` | Explicit-invocation contribution without a routing claim; the other valid L2+ candidate treatment |
| `prior/natural_routing` | Optional natural-routing revision comparator |
| `prior/force_loaded` | Optional explicit-invocation revision comparator |
| `comparator/raw_instructions` | Equivalent instruction content without Skill packaging/routing |
| `comparator/alternative_intervention` | Immutable script, CLI, hook, linter, or host-native comparator |
| `comparator/raw_model_upgrade` | Different model without the Skill; a separate, non-causal stratum |

Declare only treatments required by the decision. L2+ has `baseline/skill_disabled` and exactly one primary candidate for each causal estimand. Natural routing and forced loading are different claims and are never merged. A force-loaded treatment can establish incremental value for an explicit-only Skill only when the task text is byte-identical across treatments, selection is outside that text, and baseline exposes no Skill name, path, body, catalog hint, or treatment label. It cannot prove natural routing. A prior treatment matches the selected candidate mode and does not replace the no-Skill baseline for an incremental-value question.

Every treatment freezes `treatment_id`, profile, causal role, prompt group, intervention axes, model/harness/host, implementation, catalog, delivery, tool, permission, network, context, scenario coverage, capabilities, and exclusions. A causal pair changes exactly one declared intervention axis; a different model, harness, or host cannot enter the same-model causal interval.

## Fair case and repeat design

Run the same frozen scenario, fixture, agent/model, harness, host, tools, permissions, timeout, reset, graders, and capture policy in each comparable treatment. Keep candidate bytes and cache effects out of baseline context. Counterbalance order when time, service drift, quotas, or caching can favor a treatment.

Repeats and cases have different roles:

1. pair `(case_id, repeat)` rows to diagnose missing, invalid, win, loss, and tie behavior;
2. normalize the declared metric, convert it to the frozen candidate-benefit direction, and average comparator/candidate repeat values inside each distinct case;
3. resample the keyed case benefits for inference.

Repeats never increase `case_count`. Fewer than two complete independent cases cannot produce an interval. A positive point estimate cannot replace the frozen primary-benefit lower bound.

## Isolation and provenance

The compiler consumes the exact spec v5, scenario corpus, host manifest, and any bound calibration/quality artifacts and emits one deterministic execution plan v1. Each plan entry fixes its disposition (`execute`, `unsupported`, or `not_evaluable`) from verified capability probes. Unsupported or unknown capability evidence is feasibility evidence and produces no attempt.

Every run-index row v2 joins one execute attempt to the plan/entry/case/treatment/repeat and a hashed receipt v4 under `spec.artifacts.root`. The analyzer recompiles the plan, verifies index and receipt identities, and recomputes spec, scenario, host, package, catalog, treatment, fixture, grader, artifact, invocation, calibration, and quality bindings before deriving a result. Index rows contain no pass, score, routing, usage, grader, or provenance claims.

Keep cases, hidden graders, holdout payloads, and evaluation-controller instructions outside the tested executor context unless the deployment contract genuinely supplies them. Preserve invalid apparatus rows, treatment failures, retries, timeouts, and raw artifacts under their declared semantics.

## Holdout and manual authority

L3/generalization evidence uses a separately stored holdout payload and manifest with ordered case IDs, per-case hashes, payload hash, custodian, exposure state, and refresh state. Visible example holdouts must be replaced, access-controlled, and rehashed.

When manual review is required, the sole authority input is one contained, hashed JSON receipt whose role and evidence types exactly match the spec. `approve` completes that authority gate; `hold` or `reject` blocks final-authority eligibility without rewriting empirical usefulness. The signature is an attestation unless an external system separately proves it.

## Contract changes

Changing scenarios, fixtures, requirements, graders, thresholds, environment, model, harness, catalog, reset, or capture semantics creates a new evidence contract. Record the reason, identify invalidated comparisons, rerun every affected treatment, preserve the prior cycle, and disclose the boundary. Never tune acceptance after observing only the candidate.
