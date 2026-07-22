# Source Map and Method Provenance

This Skill combines three sources with a small local executable contract. Source guidance explains why a method exists; the current schema, receipts, analyzer, and report owners define what this package actually verifies.

## 1. OpenAI: Testing Agent Skills Systematically with Evals

- URL: https://developers.openai.com/blog/eval-skills
- Contribution: define measurable success, exercise explicit/implicit/contextual/negative cases, capture traces and artifacts, prefer deterministic checks, constrain rubric graders, and measure outcome/process/quality/efficiency separately.

Local adaptation: the v3 suite binds canonical requirements, receipts, artifacts, and grader evidence instead of trusting host self-report. Codex event names remain examples rather than portable requirements.

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
| M-01 | Freeze the decision, measured dimensions, and gates before execution | OpenAI guidance on defining success and measurable eval criteria | Direct + adaptation | `evaluation-contract.md` → `Decision and claim ceiling`; `evaluation-contract.md` → `Spec v4 owner` | `schema_version=4`; `ready_for_scored_run`; `analysis.primary_benefit`; `hard_gates[]`; `validate_eval_suite.py::check_spec` |
| M-02 | Separate retrieval, selection, loading, incorporation, application, and negative routing | OpenAI activation coverage; Anthropic progressive disclosure; Ding et al. skill relevance and use | Direct + adaptation | `task-suite-design.md` → `Coverage boundaries`; `execution-and-grading.md` → `Routing and usage` | case `should_trigger`; receipt routing; `routing_evaluable`; `analyze_runs.py::routing_summary` |
| M-03 | Derive required outcomes from canonical requirements and bind deterministic/qualitative grader receipts | OpenAI deterministic checks and constrained rubric grading | Direct + adaptation | `task-suite-design.md` → `Canonical case and requirements`; `execution-and-grading.md` → `Deterministic grader receipt`; `execution-and-grading.md` → `Grader semantic owner` | `requirements[]`; declared graders; receipt v3 grader outputs; `validate_eval_suite.py::check_cases`; `analyze_runs.py::derive_run_fields` |
| M-04 | Audit package anatomy, metadata routing, progressive disclosure, and reachable resources | Anthropic package anatomy and progressive loading | Direct + adaptation | `security-and-package-audit.md` → `2. Establish provenance and trust`; `security-and-package-audit.md` → `3. Audit the package boundary` | `audit_skill_package.py::audit`; reachable-support graph; `text_scan_complete` |
| M-05 | Treat instructions, scripts, dependencies, files, and network behavior as executable surfaces | Anthropic security treatment of package resources and executable code | Direct + adaptation | `security-and-package-audit.md` → `4. Review instructions as executable policy`; `security-and-package-audit.md` → `8. Controlled runtime probes` | `audit_skill_package.py::PATTERNS`; structural and scan-completeness gates |
| M-06 | Bind relevance, execution, termination, reuse, and treatment identity | Ding et al. relevance, execution policy, termination, and reuse dimensions | Direct + adaptation | `evaluation-contract.md` → `Canonical variants`; `evaluation-contract.md` → `Isolation and provenance` | `variant_profile_requirements`; `package_hash`; `catalog_hash`; `treatment_hash`; receipt provenance |
| M-07 | Scope cases to useful non-generic capability gaps and declared risk slices | Ding et al. skill task construction and capability dimensions | Direct + adaptation | `task-suite-design.md` → `Frontier-model case filter`; `task-suite-design.md` → `Suite review` | case split/tags; frontier filter; `analyze_runs.py::summarize_variant` |
| M-08 | Compare immutable versions while protecting regression and holdout boundaries | Ding et al. evolution, robustness, and regression evaluation | Direct + adaptation | `longitudinal-evaluation.md` → `Freeze each cycle`; `longitudinal-evaluation.md` → `Protected behavior` | `analyze_runs.py::derive_protected_outcome_failures`; holdout `payload_sha256`; cycle ledger |
| M-09 | Probe poisoning, injection, privacy, permission, sensitive-action, and persistence risks | Ding et al. safety evaluation; Anthropic package security boundaries | Direct + adaptation | `security-and-package-audit.md` → `1. Threat model`; `security-and-package-audit.md` → `7. Permissions and side-effect map` | safety cases/graders; candidate-wide safety and protected guardrails |
| M-10 | Infer contribution over independent cases, enforce context burden, and keep evidence/usefulness/authority separate | Combined M-01–M-09 | Local synthesis | `rubric-and-metrics.md` → `Independent-case intervals`; `rubric-and-metrics.md` → `Target-Skill context guardrail`; `reporting-and-decisions.md` → `Status model` | `analyze_runs.py::summarize_case_differences`; `analyze_runs.py::summarize_skill_context`; `analyze_runs.py::derive_usefulness_status`; manual-review receipt |

### Reverse coverage: local owner to source method

| Local field / function / heading | Method IDs | Source basis |
|---|---|---|
| `schema_version=4`, `ready_for_scored_run`, `analysis.primary_benefit`, `hard_gates[]` | M-01 | OpenAI measurable-success and eval-contract guidance |
| `should_trigger`, receipt routing, `routing_evaluable`, `routing_summary` | M-02 | OpenAI activation coverage; Anthropic progressive disclosure |
| `requirements[]`, exact declared graders, receipt v3 grader outputs, `derive_run_fields` | M-03 | OpenAI deterministic and qualitative grader guidance |
| `audit_skill_package.py::audit`, reachable support, scan completeness | M-04, M-05 | Anthropic package anatomy and security surfaces |
| `package_hash`, `catalog_hash`, `treatment_hash`, receipt provenance | M-06 | Ding et al. relevance, execution, termination, and reuse dimensions |
| split/tags, frontier filter, `summarize_variant` | M-07 | Ding et al. task and capability coverage |
| holdout manifest `payload_sha256`, protected cases, `derive_protected_outcome_failures` | M-08 | Ding et al. evolution, robustness, and regression coverage |
| safety cases, hard grader evidence, material-harm blocking | M-09 | Ding et al. safety coverage; Anthropic package security boundaries |
| `summarize_case_differences`, `resampling_unit=case_id`, keyed `case_count` | M-01, M-10 | local experimental discipline applied to M-01–M-09 |
| `summarize_skill_context`, measurement source, attribution and p95 gates | M-02, M-04, M-10 | progressive-disclosure adaptation of M-02/M-04 |
| `derive_usefulness_status`, receipt verification, manual-review receipt | M-03, M-09, M-10 | local synthesis over M-01–M-09 |

## 5. Local synthesis introduced here

The following are explicit product choices, not universal standards:

- L0–L4 levels and their claim ceilings;
- schema v4 and canonical `requirements[]`;
- receipt index v1 and receipt v3 as the only runtime evidence input;
- exact path/hash/provenance/invocation/grader binding before result derivation;
- independent-case bootstrap intervals with repeat-level descriptive diagnostics;
- benefit, noninferiority, safety, protected-outcome, and context gates;
- separate evidence, empirical usefulness, and final-authority statuses;
- a manual-review authority receipt whose signature text is retained but not cryptographically verified;
- L4 version/cycle monitoring without unverified library orchestration claims.

## 6. Source limitations

- The OpenAI article is a practical evaluation example, not a comprehensive statistical standard.
- The Anthropic article explains Skill architecture and authoring practice; it does not provide a comparative benchmark protocol.
- The survey synthesizes heterogeneous work and does not establish universal thresholds across frontier models and tasks.
- Static review cannot establish runtime safety, and a finite runtime suite cannot certify permanent safety.

Report only what the locally verified receipts and frozen evaluation establish.
