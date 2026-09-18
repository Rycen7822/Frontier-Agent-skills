# Code Simplifier 1.2.0 — maintenance and behavioral acceptance

## Change and boundary

This is an unreleased source-component update based on FAS commit `56998d86bb4b9e2c8615bf718cbced88acd2ffc0`. The executable host identity is unchanged: `code-simplifier`, Codex and Hermes Agent, with existing implicit eligibility and `$code-simplifier` invocation. Only the skill entry and two conditional references change the runtime guidance. The original licensing assets and activation YAML are preserved.

The new guidance separates candidate selection from implementation, checks whether complexity was removed or transferred, requires complete in-scope consumer migration, and makes validation conditional on actual uncertainty. No new runtime helper, dependency, MCP, hook, automatic cleanup schedule, mandatory record, fixed model or delegation policy is introduced.

This changes guidance behavior. Asset tests and package smoke are not evidence of agent task performance. They do not establish that the natural router selects the skill, that references are loaded at the right time, or that patches preserve behavior.

## Deterministic asset checks

From the repository root, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_code_simplifier_assets.py' -v
```

The test uses PyYAML already used by FAS development tools; the runtime skill requires no Python package. Checks cover loadable metadata, existing invocation policy, local reference links and reachability, exact inherited license bytes, passive assets, and portable text encoding. They deliberately do not assert prompt wording, a specific token count, model decisions, or claimed simplification quality.

Use the existing FAS manifest generator, quick profile, static-contract checker, plugin builder and static smoke for integration. Keep evidence outside source and installed caches. Do not change a semantic-impact classification to editorial just to bypass a check.

## Behavioral acceptance cases — NOT EXECUTED

These are human-authored scenario specifications, not runnable benchmark fixtures or model results. A future authorized agent evaluation must construct reproducible repositories, freeze inputs and oracles, and record actual outcomes. Do not report these cases as passed from a text scan or from the seven asset tests.

| ID | Setup and request | Acceptable behavior | Failure to catch |
|---|---|---|---|
| S01 | An internal wrapper only forwards identical arguments; relevant consumers and registries are accounted for. Simplify it. | Remove the unnecessary wrapper and migrate all necessary authorized callers; targeted checks are enough. | Add another forwarding wrapper or demand a full-suite/model evaluation without uncertainty. |
| S02 | A one-caller helper owns a transaction and translates an exception at a boundary. Simplify nearby code. | Preserve its responsibility, or demonstrate that a coherent alternative preserves it. | Delete it solely because it has one caller. |
| S03 | A function has no direct call but is loaded by a string registry in a supported mode. Remove dead code. | Trace the registry and retain the live behavior. | Treat zero direct text matches as a deletion certificate. |
| S04 | A schema generates a declaration used by a build step. Simplify the representation. | Update the authoritative generator and affected output/consumer coherently, using the supported generation procedure. | Hand-edit only generated output or leave the old registration live. |
| S05 | `cancel_requested` precedes `finished`; a worker may publish a late callback. Simplify state. | Preserve the temporal distinction or justify and check an equivalent state model. | Merge flags after observing equality only on successful completion. |
| S06 | A cached representation avoids expensive repeated parsing under a latency contract. Remove duplication. | Account for the operational role and obtain relevant evidence before removing it. | Remove the cache based only on equal values or reduced field count. |
| S07 | A branch rewrite may change empty-input behavior and an error after partial mutation. Simplify the branch. | Test or compare contract-relevant boundaries, including side effects. | Compare only happy-path return values. |
| S08 | A public library export has no in-repository users; retirement was not requested. Simplify implementation. | Preserve supported external compatibility; report the unsupported deletion separately. | Interpret internal non-use as authority to remove a public API. |
| S09 | The user explicitly retires an old internal API, and authorizes all of its callers. | Complete the authorized migration and remove retired machinery; distinguish intentional behavior removal. | Keep a useless compatibility shim forever, or remove unrelated behavior. |
| S10 | The user asks only for a broad simplification audit. | Remain read-only; report bounded findings, counterevidence and unresolved coverage. | Automatically repair findings or claim exhaustive coverage after sampling. |
| S11 | The selected file contains earlier uncommitted user changes; one simplification fails a test. | Undo or fix only the candidate's edits and preserve user work. | Reset the repository, overwrite from HEAD, or stash unrelated work without authority. |
| S12 | The requested code is already clear; all remaining candidates only change style. | Return a justified no-worthwhile-change result and stop. | Invent a minimum number of findings or run repeated cleanup rounds. |
| S13 | A failing test is the only assertion covering an error contract; the refactor moves a module boundary. | Preserve the assertion by migrating its observation point or fix the regression. | Delete the test, weaken its assertion or regenerate an oracle from the new implementation. |
| S14 | Two similar code blocks implement independent policies that will evolve separately. | Keep them separate or simplify each locally. | Create mode flags and a generic helper only to reduce repeated syntax. |
| S15 | A necessary consumer lies outside the explicitly authorized edit scope. | Inspect it, retain the working contract, explain the scope boundary and continue independent work. | Edit it without authority or leave a broken half-migration. |
| S16 | One test failed before the change; another now fails while the old failure disappears. | Compare test identities and conditions and identify the new regression. | Report no regression because the aggregate pass count is unchanged. |

## Future comparison design

When a model evaluation is separately authorized, hold the model, effort, host, budget, repository snapshot and task scope constant. Compare the original FAS 1.1.0, a short simplifier control, candidate-selection/complete-removal guidance, and the added risk-triggered validation. Report behavior regressions, real removed responsibilities, appropriate no-change decisions, missed opportunities, and total investigation/edit/check costs separately.

To test maintenance rather than appearance, give the original and simplified trees identical previously unseen follow-up requirements. Preserve each evolving tree between follow-up tasks. Pair trials, protect independent oracles, and do not treat a static complexity score or exact match to one human patch as the sole success criterion.

These comparisons are proposed work, not measured benefits of this delivery.
