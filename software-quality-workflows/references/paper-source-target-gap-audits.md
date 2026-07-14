# Paper, Source, and Target-System Gap Audits

Use this reference when a software-development task requires reading a research paper, inspecting its released source, comparing both with a target codebase or product, and deriving grounded upgrade recommendations or an implementation roadmap.

Use the relevant document-extraction and paper-reliability skills for their domains. Use [Delegated Development](delegated-development.md) for controller/child mechanics and `writing-plans` only when the result must become an implementation-ready plan.

## Controller-owned evidence chain

1. Locate exact inputs and verify their identities. Quote paths containing spaces or punctuation; a tokenized path failure is not proof that the file is absent.
2. Convert primary documents into reusable text when needed, while retaining the original PDF path, page count, extraction method, and layout caveats such as two-column interleaving.
3. Create a task-owned working note with verified input paths, paper claims, source mechanisms, target capabilities, and open gaps. This note protects the analysis from context compaction; it is not the final report.
4. Inventory the released source and target repository before delegation. Measure relevant size and risk so work is assigned by evidence weight rather than raw file count.
5. Dispatch clean-context audits by evidence type and require each worker to write a unique Markdown report with exact sources, paths/lines or pages, commands, conclusions, risks, and open questions.
6. Read every child report, then independently recheck high-impact claims against the paper text, source code, and target contracts. Subagent reports are evidence inputs, not authoritative conclusions.
7. Draft centrally in a task-owned file. Organize by mechanism and target subsystem rather than by worker or source file.
8. Read the complete draft and check structure, code fences, placeholders, evidence labels, overclaims, and requested output-path coverage.
9. Patch thin or weakly supported sections from primary evidence, then write the final report and verify its beginning, end, key sections, and destination.

## Recommended evidence split

### Paper reader

Extract the method, architecture, algorithms, empirical results, baselines, ablations, limitations, assumptions, and warnings. Cite page, figure, table, or extracted-text ranges, and distinguish stated claims from your interpretation.

### Source control-flow auditor

Inspect idea generation, prompts, patch/diff handling, repair loops, feedback ingestion, external-service assumptions, state models, and brittle control flow. Read implementation files, not only the README.

### Source execution/environment auditor

Inspect run scripts, schedulers, workers, evaluators, metrics, reward-hacking defenses, resource assumptions, reproducibility, artifact schemas, failure classification, and cleanup. Pay special attention to scripts that define success, timeout, or completion semantics.

### Target-system gap auditor

Inspect the target's current architecture, skills, tools/services, hooks/events, CLI, prompts, schemas, packaging/install surface, and verification contracts. Map capabilities already present before proposing additions.

## Analysis lenses for execution-grounded systems

| Lens | Questions |
|---|---|
| Research environment contract | Are problem, baseline, fixed data, metric, protected files, resources, budget, and reward transform explicit and enforceable? |
| Implementer | How does an idea become a patch, sandboxed variant, repaired change, and package? |
| Scheduler | How are queueing, resources, job specs, budgets, idempotency, retries, and backends owned? |
| Worker | How are sandboxing, heartbeat, logs, metrics, artifacts, terminal state, and failures represented? |
| Feedback and trajectory | How are results, failed executions, provenance, rankings, failure taxonomy, and claimability retained? |
| Search | How are exploitation, novelty, diversity, collapse, budgets, and best-of-N comparisons handled? |
| Trust | Are evaluators immutable, protected inputs hashed, top candidates revalidated, and evidence/claim gates independent of self-report? |

## Synthesis rules

Separate three conclusions:

- what the paper demonstrates under its stated experimental conditions;
- what the released code actually implements versus assumes externally;
- what the target should borrow, adapt, defer, or reject.

Borrow architecture only when the evidence supports the target's use case. Execution-grounded loops, patch-failure repair, trajectory learning, fixed-budget proxy evaluation, and failed-run retention are often useful patterns, but their implementation still requires target-specific authority, schemas, and verification.

Do not blindly copy prototype weaknesses such as self-reported logs as truth, evaluator protection by prompt wording, wrappers that swallow failures, fixed sleeps as completion, hard-coded personal/cloud paths, string-only idea records without provenance, or a single scalar reward as the default improvement path.

## Final report shape

1. Thesis and scope.
2. What the paper shows, including limits.
3. What the released source implements versus assumes.
4. What the target already has.
5. Gap table by subsystem.
6. Recommendations across architecture, skills, tools/services, hooks, CLI, prompts, schemas/artifacts, packaging, and verification.
7. Prioritized phases with dependencies and proof gates.
8. Explicit prototype weaknesses and “do not copy” decisions.
9. Residual evidence gaps and source-to-conclusion traceability.

If the user explicitly requests working notes, a draft, full readback, and final adjustment, each is a real controller-owned artifact and gate rather than a sentence claiming those steps happened.
