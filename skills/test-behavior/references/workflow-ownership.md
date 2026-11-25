# Workflow ownership

Use this reference when a testing decision needs a handoff to the workflow already handling the task. Test Behavior owns check necessity, timing, expectations, execution validity, lifetime and retirement. Continue the surrounding workflow after that decision; load another skill only for a concrete need within the authorized task.

| Workflow | Responsibility that remains with it | Testing boundary |
|---|---|---|
| [Software Quality Workflows](../../software-quality-workflows/SKILL.md) | Implementation scope, quality and completion. | Apply Test Behavior before authoring checks and when a behavior or compatibility obligation ends, even without a planned test edit. |
| [Debugging](../../debugging/SKILL.md) | Causal hypotheses, responsible owner and repair. | Apply Test Behavior before authoring reproductions or diagnostic checks; preserve an explicitly requested regression or BRT delivery. |
| [Runtime Verification](../../runtime-verification/SKILL.md) | Real consumer, installed target, readiness and task-owned resources. | Existing runners can answer the question without new code. Authored installation, smoke or inline probes follow Test Behavior. |
| [Code Simplifier](../../code-simplifier/SKILL.md) | Useful burden reduction and preserved or explicitly changed semantics. | Apply Test Behavior to authored equivalence checks and directly affected protection when behavior is retired. |
| [Codebase Investigation](../../codebase-investigation/SKILL.md) | Source-grounded explanation and historical attribution. | Reading source does not require writing a probe. Authorized authored checks follow Test Behavior. |
| [Software Design](../../software-design/SKILL.md) | Requirements, ownership, migration and compatibility commitments. | Checks around a prototype follow Test Behavior; migration completion separates one-time acceptance from obligations that continue. |
| [Writing Plans](../../writing-plans/SKILL.md) | Executable order, real dependencies and durable handoff. | Identify a needed check's question and lifetime; include affected test review when an obligation ends. Apply Test Behavior before executing a check edit. |
| [Code Review](../../code-review/SKILL.md) | Actionable findings, consumer impact and counterevidence. | Assess changed checks and retirement against Test Behavior; authoring a review reproduction also triggers it. Missing new tests alone does not establish a defect. |
| [Skill Evaluator](../../skill-evaluator/SKILL.md) | Cases, task/judge separation, finite budgets, evidence reuse and supported effectiveness claims. | Authored fixtures, executable verifiers and harness checks follow Test Behavior. A specified evaluation suite remains a delivery requirement. |

Keep domain-specific decisions with their owner: a reference implementation can support equivalence, an installed consumer can establish runtime behavior, and an independent grader can establish an evaluation outcome. Test Behavior determines whether the check and its evidence serve that claim; it does not choose the product design, force a model evaluation or add an approval phase.
