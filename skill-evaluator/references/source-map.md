# Source Map and Method Provenance

This Skill combines three public sources, the evidence synthesis from Pattern source commit `62a12b12a1bdfb44bf397e73035fa85f3ff03106`, and a small local executable contract. Source guidance explains why a method exists; current schemas, producers, receipts, analyzer, and tests define what this package verifies.

## 1. OpenAI: Testing Agent Skills Systematically with Evals

- URL: https://developers.openai.com/blog/eval-skills
- Contribution: define measurable success, exercise explicit/implicit/contextual/negative cases, capture traces and artifacts, prefer deterministic checks, constrain rubric graders, and measure outcome/process/quality/efficiency separately.

Local adaptation: spec v6 and scenario v1 bind requirements, readable execution profiles, preparation, receipts, artifacts, and grader evidence instead of trusting host self-report. Codex event names remain examples rather than portable requirements.

## 2. Anthropic: Equipping agents for the real world with Agent Skills

- URL: https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Contribution: treat a Skill as a package, test metadata-driven activation and progressive loading, audit scripts/resources as security surfaces, and refine from observed behavior.

Local adaptation: package review, routing stages, verified loaded components, and Target-Skill context burden remain distinct measurements.

## 3. Ding et al.: Agent Skill Evaluation and Evolution

- URL: https://arxiv.org/pdf/2606.11435
- Contribution: evaluate relevance, execution policy, termination, reuse, safety, contribution against a no-Skill baseline, protected behavior, and versioned evidence.

Local adaptation: this package implements bounded local validation and summary logic. It does not reproduce surveyed benchmarks, generate Skill revisions, or orchestrate Skill libraries.

## 4. Method traceability matrix

Each `Owner heading` is the normative product section. `Source basis` identifies the public source concept without depending on unbundled snapshots or unstable line ranges. Concrete fields/functions are the current machine-checkable realization.

| ID | Method | Source basis | Relation | Owner heading | Concrete field/function |
|---|---|---|---|---|---|
| M-01 | Freeze decision, applicability, estimands, gates, authority, and preparation before execution | OpenAI measurable-success guidance; Pattern plan-before-action lifecycle | Direct + adaptation | `evaluation-contract.md` → `Decision and claim ceiling`; `evaluation-contract.md` → `Spec v6 owner` | `schema_version=6`; `execution.ready`; `analysis.estimands[]`; `hard_gates[]`; `validate_eval_suite.py::validate_v6_contract_semantics`; `tests/test_extended_eval_spec.py` |
| M-02 | Separate exact routing stages, no-match, catalog order, and declared composition | OpenAI activation coverage; Anthropic progressive disclosure; Pattern crowded-catalog routing | Direct + adaptation | `task-suite-design.md` → `Routing, composition, and coordination`; `execution-and-grading.md` → `Routing, composition, and usage` | scenario `routing_contract`; receipt v5 routing; `run_eval_plan.py::_validate_routing_contract`; `tests/test_extended_module_e2e.py` |
| M-03 | Bind scenario v1 requirements to deterministic and blinded model graders | OpenAI deterministic checks and constrained rubric grading; Pattern verification boundaries | Direct + adaptation | `task-suite-design.md` → `Scenario v1 and requirements`; `execution-and-grading.md` → `Deterministic grader receipt`; `execution-and-grading.md` → `Grader semantic owner` | scenario v1 `requirements[]`; `grader_semantics.py::semantic_payload`; calibration v3 `check_metrics[]`; receipt v5 grader outputs; `analyze_runs.py::validate_grader_output`; `tests/test_extended_eval_quality.py` |
| M-04 | Audit complete package anatomy, progressive disclosure, schemas, and reachability | Anthropic package anatomy and progressive loading | Direct + adaptation | `security-and-package-audit.md` → `2. Establish provenance and trust`; `security-and-package-audit.md` → `3. Audit the package boundary` | `audit_skill_package.py::audit`; reachable formal-support graph; `text_scan_complete`; `tests/test_extended_package_audit.py` |
| M-05 | Treat instructions, code, dependencies, permissions, tools, and side effects as security surfaces | Anthropic package security; Ding et al. safety; Pattern authority/action stages | Direct + adaptation | `security-and-package-audit.md` → `Evidence ladder`; `security-and-package-audit.md` → `8. Controlled runtime probes` | S0–S5; receipt v5 actions/observations/cleanup; `run_eval_plan.py::_validate_action_lifecycle`; `tests/test_extended_eval_execution.py` |
| M-06 | Freeze execution identity and one intervention axis before causal attribution | Ding et al. relevance/execution/reuse; Pattern scope/control/authority freezing | Direct + adaptation | `evaluation-contract.md` → `Treatment registry`; `evaluation-contract.md` → `Isolation and provenance`; `execution-and-grading.md` → `Compiler and dispositions` | `treatment_id`; `intervention_axes`; execution plan v2; `compile_eval_plan.py::compile_plan`; `tests/test_extended_eval_execution.py` |
| M-07 | Select non-generic frontier-model scenarios and prove suite quality before scoring | Ding et al. task construction; OpenAI eval criteria; Pattern boundary/failure coverage | Direct + adaptation | `task-suite-design.md` → `Frontier-model case filter`; `task-suite-design.md` → `Suite-quality preparation`; `task-suite-design.md` → `Suite review` | split/tags/modules; suite-quality v2; `validate_eval_suite.py::_derive_quality_coverage`; `tests/test_extended_eval_quality.py` |
| M-08 | Compare immutable versions while protecting holdout, regression, host, and rollback boundaries | Ding et al. evolution/robustness; Pattern durable-state recovery | Direct + adaptation | `longitudinal-evaluation.md` → `Freeze each cycle`; `longitudinal-evaluation.md` → `Protected behavior`; `longitudinal-evaluation.md` → `Monitoring and rollback` | holdout `payload_sha256`; plan/host/module identity; `analyze_runs.py::derive_protected_outcome_failures`; `tests/test_extended_reporting.py` |
| M-09 | Separate attempted, authorized, blocked, executed, delivered, rendered, and confirmed effects | Ding et al. safety; Anthropic security; Pattern tool/action lifecycle | Direct + adaptation | `execution-and-grading.md` → `Actions, authorization, observations, and faults`; `security-and-package-audit.md` → `Evidence ladder` | receipt v5 actions; authorization fusion; `action_summary`; `run_eval_plan.py::_validate_action_lifecycle`; `tests/test_extended_module_e2e.py` |
| M-10 | Infer over case clusters and keep five axes, context burden, independence, critique, and grounding non-compensating | Combined M-01–M-09 plus Pattern evidence/authority separation | Local synthesis | `rubric-and-metrics.md` → `Five independent axes`; `rubric-and-metrics.md` → `Independent-case intervals`; `reporting-and-decisions.md` → `Status model` | `analyze_runs.py::summarize_case_differences`; `analyze_runs.py::summarize_skill_context`; `analyze_runs.py::derive_usefulness_status`; `independence_summary`; `grounding_summary`; `tests/test_extended_reporting.py` |
| M-11 | Close one controlled revision hypothesis or classify direct/bridge/combined model drift without granting release authority | Ding et al. evolution/robustness; Pattern frozen scope and evidence/authority separation | Direct + local synthesis | `longitudinal-evaluation.md` → `Offline comparison owner`; `reporting-and-decisions.md` → `Offline comparison report v2` | comparison plan/observations/report/index v2 and cycle capsule v2; `compare_cycles.py`; `comparison_revision.py`; `comparison_transition.py`; `tests/test_extended_eval_revision.py`; `tests/test_extended_eval_transition.py` |

M-11 implementation owners are the [capsule contract](../scripts/comparison_contract.py), [revision contract](../scripts/comparison_revision_contract.py), [revision evaluator](../scripts/comparison_revision.py), [transition evaluator](../scripts/comparison_transition.py), and [transition metrics](../scripts/comparison_transition_metrics.py).

### Reverse coverage: local owner to source method

| Local field / function / heading | Method IDs | Source basis |
|---|---|---|
| `schema_version=6`, `execution.ready`, `analysis.estimands[]`, `hard_gates[]` | M-01 | OpenAI measurable success; Pattern plan-before-action |
| scenario `routing_contract`, receipt routing, stage summaries | M-02 | OpenAI activation; Anthropic progressive loading; Pattern catalog routing |
| scenario v1 `requirements[]`, exact graders, receipt v5 grader outputs | M-03 | OpenAI deterministic and qualitative grading |
| `audit_skill_package.py::audit`, reachable schemas/support, scan completeness | M-04, M-05 | Anthropic package anatomy/security |
| `treatment_id`, readable execution profile, `compile_plan`, plan/entry IDs and index plan binding | M-06 | Ding et al. relevance/execution/reuse; Pattern frozen scope |
| split/tags, module coverage, suite-quality gates | M-07 | Ding et al. task coverage; Pattern positive/boundary mechanisms |
| holdout manifest `payload_sha256`, protected scenarios, host/module cycle identity | M-08 | Ding et al. evolution/robustness; Pattern durable recovery |
| action lifecycle, authorization fusion, effect confirmation, S0–S5 | M-05, M-09 | Ding et al. safety; Anthropic security; Pattern action stages |
| `summarize_case_differences`, `resampling_unit=case`, keyed `case_count` | M-01, M-10 | Local experimental discipline |
| `summarize_skill_context`, attribution, controlled/core bytes, per-call cost | M-02, M-04, M-10 | Progressive-disclosure cost adaptation |
| `independence_summary`, critique uptake, `grounding_summary` | M-03, M-10 | Pattern judge dependence, repair uptake, and source support |
| `derive_usefulness_status`, five axes, failure index, manual-review receipt | M-03, M-09, M-10 | Local synthesis over all source methods |
| revision closure and model-transition classification with authority ceiling | M-08, M-11 | Ding et al. evolution/robustness; Pattern frozen scope and authority separation |

## 5. Pattern evidence traceability

Pattern was analyzed as a whole-project corpus, not as one universal workflow: 1,252 non-generated text files and 157,501 lines at source commit `62a12b12a1bdfb44bf397e73035fa85f3ff03106`, including all 105 files and 14,976 lines under `pattern/workflows/`. The synthesis below records bounded facts; local schema versions, thresholds, and status names remain Skill Evaluator product decisions.

| Pattern evidence synthesis | Plan requirement | Current field/function owner | Acceptance test |
|---|---|---|---|
| Workflows route on facts instead of one universal sequence | C-06, M-01 conditional modules | spec `applicability`; compiler module projection | `tests/test_extended_module_e2e.py::test_seven_minimal_plans_close_required_and_inactive_modules` |
| Plans freeze scope, controls, authority, and stop conditions before action | P-01–P-10 deterministic plan | `compile_eval_plan.py::compile_plan` | `tests/test_extended_eval_execution.py::test_compiler_emits_byte_identical_schema_valid_plan` |
| Stateful work needs obligations, transitions, terminal, and cleanup facts | M-05, R-14 | scenario turns/state; receipt v5 state | `tests/test_extended_eval_execution.py::test_runner_closes_state_principal_and_handoff_contracts` |
| Recovery verifies durable state rather than narrative | R-12, E-04 | attempt custody/status/budget; marker/index/receipt; runner `--resume` | `tests/test_extended_runner_lifecycle.py`; `tests/test_extended_eval_execution.py::test_resume_seals_marker_only_attempt_without_inventing_outcome` |
| Crowded catalogs expose overlap, no-match, order, and context cost | M-02 | scenario `routing_contract`; runner routing validator | `tests/test_extended_module_e2e.py::test_seven_minimal_plans_close_required_and_inactive_modules` |
| Composition requires exact participants, order, and handoff evidence | M-03, M-04 | routing composition; typed handoffs | `tests/test_extended_module_e2e.py::test_declared_pair_and_sequence_keep_distinct_order_semantics` |
| Topology claims need decomposability and equal-budget single-principal control | C-16, M-18 | scenario coordination; plan/receipt principals | `tests/test_extended_module_e2e.py::test_critique_consensus_and_cache_evidence_cannot_self_promote` |
| Handoffs lose provenance unless payload, authority, raw result, and transforms are typed | R-17, E-10 | host `$defs`; receipt v5 handoffs | `tests/test_extended_eval_execution.py::test_async_delivery_preserves_forward_causal_ancestry` |
| Tool availability, authorization, delivery, rendering, and effects are distinct stages | R-18, R-19, M-21, M-23 | receipt actions; runner action validator; `action_summary` | `tests/test_extended_eval_execution.py::test_action_changes_denial_and_unauthorized_execution_fail_closed` |
| Causal attribution requires fixed execution identity and one intervention axis | C-15 | spec treatments; plan identity | `tests/test_extended_eval_execution.py::test_hash_profile_module_and_capability_drift_fail_closed` |
| Suite validity and blinded judge calibration precede scoring | C-10–C-12, R-08 | validator calibration/suite-quality producers | `tests/test_extended_eval_quality.py::test_model_and_deterministic_preparation_chains_reach_contract` |
| Shared lineage/context is dependent; critique must be taken up and repaired | M-19, M-20, E-09 | independence/critique summaries | `tests/test_extended_eval_quality.py::test_independence_is_derived_from_identity_context_and_sources` |
| Missing/tampered evidence and unsupported capability are not candidate failures | C-18, M-11, M-22 | disposition, feasibility, evidence axes | `tests/test_extended_reporting.py::test_v5_nonexecute_probe_results_are_complete_without_attempts` |
| Safety needs static review plus contained runtime evidence, per host | M-14, M-15, M-17 | S0–S4; action/observation/cleanup receipts | `tests/test_extended_module_e2e.py::test_two_host_security_gates_remain_independent` |
| Correct bytes may be stale; an existing source may not support a claim | C-17 | observation contracts; `grounding_summary` | `tests/test_extended_eval_quality.py::test_grounding_calibration_requires_support_and_attribution_boundaries` |
| Wall time, token classes, cache, retries, rework, and residue need distinct denominators | R-20, A-19 | receipt usage; summary `context_cost` | `tests/test_extended_reporting.py::test_v5_active_surface_summaries_are_evidence_bound` |
| Default views must be compact while drill-down stays exact; external authority stays separate | A-01–A-17 | summary v5, failure index v2, output manifest, manual authority | `tests/test_extended_reporting.py::test_v5_analyzer_writes_compact_bound_views` |

### Pattern reverse coverage: local surface to evidence fact

| Local surface | Pattern fact | Requirement/test owner |
|---|---|---|
| Applicability modules and zero inactive work | Fact-routed lifecycle | C-06/M-01; module E2E |
| Plan/entry/compiler identity | Freeze controls before action | P-01–P-10; execution golden |
| Turns/state/faults/resume | Explicit durable state and verified recovery | M-05/M-06/R-12/R-14; execution E2E |
| `routing_contract`, composition, principals, handoffs | Catalog ambiguity and context-preserving coordination | M-02–M-04/M-18; module E2E |
| Action/authorization/observation stages | Tool visibility and effect are distinct | R-18/R-19/M-21/M-23; security E2E |
| Calibration, independence, critique uptake, grounding | Judge dependence and source support need direct evidence | C-11/C-17/M-19/M-20; quality/reporting E2E |
| Feasibility/evidence/usefulness/authority axes | Unsupported, missing, empirical, and human decisions differ | C-18/M-11/M-22/A-10–A-17; reporting E2E |
| Context/cost classes and failure recovery overhead | Resource measures use different denominators | R-20/A-19; reporting E2E |
| Compact summary → failure index → receipt → artifact | Compression must preserve exact drill-down | A-01–A-08; transaction/failure tests |

## 6. Local synthesis introduced here

The following are explicit product choices, not universal standards:

- L0–L4 levels and their claim ceilings;
- spec v6, scenario v1 `requirements[]`, and applicability registry;
- execution plan v2, run index v3, and receipt v5 as the only runtime evidence path;
- exact semantic identity plus minimal path/digest custody binding before result derivation;
- independent-case bootstrap intervals with repeat-level descriptive diagnostics;
- benefit, noninferiority, safety, protected-outcome, and context gates;
- five separate applicability, feasibility, evidence, empirical-usefulness, and final-authority axes;
- a manual-review authority receipt whose signature text is retained but not cryptographically verified;
- L4 version/cycle monitoring without unverified library orchestration claims.
- opt-in revision/model-transition comparison with canonical diagnostics and no candidate, run, or release side effects.

## 7. Source limitations

- The OpenAI article is a practical evaluation example, not a comprehensive statistical standard.
- The Anthropic article explains Skill architecture and authoring practice; it does not provide a comparative benchmark protocol.
- The survey synthesizes heterogeneous work and does not establish universal thresholds across frontier models and tasks.
- Pattern contains diverse workflow families and does not establish one mandatory lifecycle, local schema version, or universal threshold.
- Static review cannot establish runtime safety, and a finite runtime suite cannot certify permanent safety.

Report only what the locally verified receipts and frozen evaluation establish.
