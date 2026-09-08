---
name: skill-evaluator
description: "Assess historical agent trajectories or regression-test an Agent Skill. Use when the user requests evidence-based Skill improvements or investigation of behavior, routing, outcome or cost; ordinary editorial maintenance usually needs no model evaluation."
metadata:
  version: 5.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [evaluation, testing, benchmarking]
    category: software-development
    related_skills: [software-quality-workflows]
---

# Skill Evaluator

Use this skill explicitly for a requested diagnosis or evaluation decision. Resolve bundled resources through `$SKILL_EVALUATOR_DIR`, the directory containing this file.

For a change that preserves behavior, judge editorial equivalence once from the diff and stop after relevant local checks. This needs no historical evaluation and no model call. Version, hash, timestamp and unrelated documentation changes do not justify another evaluation. Optional local routing:

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/evaluate.py" check --base <revision> --impact editorial
```

For historical trajectory assessment or diagnosis, use the [history guide](references/history.md) to inspect selected episodes, attribute findings to the relevant Skill and propose the smallest justified edit. It includes a bounded reader for an explicit Codex rollout. A diagnosis may finish with no edit or new evaluation. History review is not a prerequisite for ordinary maintenance.

When behavior needs execution evidence, name the affected cases and use a real oracle. Reuse task evidence before scheduling work; changed grading normally needs only grading. Begin with explicit task and judge budgets. Missing budget returns the exact gap before creating a run or probing the Host.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/evaluate.py" run \
  --suite author-suite.json --host host.json --output run-2 \
  --previous-report run-1/summary.json --case relevant-case \
  --task-attempt-budget 1 --judge-invocation-budget 0
```

The [maintenance guide](references/maintenance.md) defines inputs, reuse, execution, grading and recovery. The [compact example](templates/author-suite.example.json) needs task-specific cases and an actual verifier. The existing Host controls model execution, isolation and credentials; task model/effort and judge model/effort are separate identities.

Report material findings with source references and the smallest justified follow-up, including why no edit is needed when appropriate. For executed evaluations, include selected scope, case failures, missing evidence and actual task/judge usage. `diagnostic_only` is a completed maintenance evaluation, not a claim of general usefulness or release qualification. A cost field that is unavailable remains unknown. An attempt is not an API request. Pair comparisons by independent case; repeats do not create independent samples. A saturated baseline or an inconclusive interval does not authorize more tasks.

Maintenance results describe the selected cases and do not grant deployment authority. No automatic retries or sample expansion.
