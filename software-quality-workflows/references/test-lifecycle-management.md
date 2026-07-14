# Test Lifecycle Management

Use this reference when adding, changing, merging, quarantining, promoting, superseding, or retiring tests, or when reorganizing suite boundaries. It is the single owner for test purpose, layer, lifecycle, provenance, and retention decisions.

## Contents

- [Ownership boundary](#ownership-boundary)
- [Classification model](#classification-model)
- [Minimal provenance](#minimal-provenance)
- [Lifecycle decisions](#lifecycle-decisions)
- [Requirement changes](#requirement-changes)
- [Flaky tests and quarantine](#flaky-tests-and-quarantine)
- [Suite-boundary refactors](#suite-boundary-refactors)
- [Audit and closeout](#audit-and-closeout)

## Ownership boundary

[Safe Test-Driven Development](test-driven-development.md) owns how a behavior test is created. [Verification Discipline](verification-discipline.md) owns gate selection and completion claims. [Authority and Scope](authority-and-scope.md) owns whether edits or deletions are allowed.

This file decides what a test means and how long it should remain.

## Classification model

Classify each durable test independently on three axes.

### Purpose

| Value | Protected intent |
|---|---|
| Requirement | A current user, product, safety, or compatibility requirement. |
| Regression | A previously observed defect or incident. |
| Characterization | Existing behavior captured to make a change safer without declaring every detail desirable. |
| Migration | Temporary or durable proof across old and new contracts or implementations. |
| Adversarial | A misuse, hostile input, boundary, or fail-closed property. |
| Smoke | A narrow proof that a public or deployed surface starts and performs a representative action. |

### Layer

| Value | Boundary under test |
|---|---|
| Unit | One pure or narrowly isolated computation. |
| Component | One cohesive subsystem with real internal collaborators. |
| Integration | Multiple owned components, persistence, process, or protocol boundaries. |
| End-to-end | A representative user path across the product. |
| Installed-surface | Packaged, copied, registered, or installed behavior outside the source-tree shortcut. |
| External-system | A real third-party or separately operated service. |

Purpose and layer are orthogonal. An integration regression, installed-surface smoke, and unit adversarial test are all valid combinations.

### Lifecycle

| Value | Meaning |
|---|---|
| Active | Runs in its declared gate and protects a current risk. |
| Quarantined | Known unreliable or environment-blocked; tracked with an owner and exit criteria. |
| Superseded | Replaced by equal or stronger evidence, retained only until the replacement is confirmed. |
| Retired | No longer part of an active gate because the underlying requirement or risk was removed or deliberately replaced. |

## Minimal provenance

Use the project’s existing metadata style. Do not force a global directory layout. A durable test should make these fields discoverable:

| Field | Meaning |
|---|---|
| requirement_anchor | Requirement, issue, bug, design row, contract, incident, or risk being protected. |
| purpose | One purpose from the model above. |
| layer | One layer from the model above. |
| lifecycle | Current lifecycle state. |
| owner | Person, team, component, or maintenance boundary responsible for the decision. |
| canonical_gate | Project command or CI gate expected to execute the test. |
| replacement_anchor | For `Superseded`, and for replacement-based `Retired`, the exact test, fixture, or gate that assumes the protection. |
| transition_evidence | For a non-`Active` state, the failure evidence, replacement confirmation gate/window, or approved requirement decision supporting the transition. |
| review_trigger | For `Quarantined` or `Superseded`, the exit criterion plus date, event, or owner action that forces reconsideration. |

A concise test name, comment, marker, fixture record, or nearby manifest is enough when it remains searchable. Do not invent a heavyweight registry for a small project.

## Lifecycle decisions

For every touched test, choose deliberately:

| Decision | Use when |
|---|---|
| Keep | It uniquely protects a current requirement or risk at an appropriate layer. |
| Merge | Another test can preserve the same oracle and failure localization with less duplication. |
| Update | The requirement remains but its valid input, output, or public contract changed. |
| Promote | A characterization or scaffold became durable contract or regression evidence. |
| Quarantine | The requirement remains but the test is temporarily unreliable or unavailable. |
| Supersede | Stronger replacement evidence exists but needs a confirmation window. |
| Retire | The requirement/risk was removed or an approved replacement makes the test irrelevant. |

Age, file length, runtime, duplication appearance, or failure under a new implementation is not enough by itself to retire a test. Compare protected behavior and oracle strength.

A superseded test remains auditable until its replacement passes the recorded confirmation gate or window. Record the replacement anchor, the exact confirmation evidence, and the event that either retires the old test or restores it to `Active`; do not let `Superseded` become an indefinite hidden quarantine.

## Requirement changes

When a requirement is removed, replaced, or materially changed:

1. search its anchor and nearby behavior terms across tests, fixtures, scripts, and gate configuration;
2. classify every relevant hit by purpose, layer, and lifecycle;
3. record keep, merge, update, promote, quarantine, supersede, or retire;
4. prove replacement coverage before removing old evidence;
5. update gate and documentation references together.

An obsolete assertion may be updated; a still-valid contract must not be rewritten merely to make a new implementation pass.

## Flaky tests and quarantine

Quarantine is a visible lifecycle state, not a silent pass. Record:

- failure signature and reproducibility evidence;
- requirement anchor and owner;
- environments or conditions affected;
- current gate treatment;
- repair or revalidation criterion;
- review date or event that triggers reconsideration.

Restore the test to active after the exit criterion is proven. Supersede or retire it only through the normal requirement decision. Report gate implications through the verification owner.

## Suite-boundary refactors

Use layer classification to make failures identify the risk boundary:

- keep pure calculations and shaping at unit or component level;
- keep orchestration, persistence, and state transitions at integration level;
- keep representative public workflows at end-to-end or installed-surface level;
- retain policy, security, and historical regression evidence at the cheapest layer that still proves the property.

Weaken brittle implementation assertions toward observable properties: determinism and shape instead of exact internal hashes, ordering guarantees instead of full private call sequences, and accepted/rejected behavior instead of prose snapshots.

If the default test command or suite partition changes, preserve an explicit project gate for the displaced coverage and update its documentation. Do not silently make a familiar command prove less. The verification owner determines the landing evidence.

## Audit and closeout

For a health audit, use the request mode set by the authority owner. In report mode, return:

- coverage by purpose, layer, and lifecycle;
- duplicate or brittle oracles;
- quarantined tests without owners or exit criteria;
- anchors whose requirements appear removed or ambiguous;
- gate configuration that omits active tests;
- proposed decisions that require product authority.

For an authorized change, close with the changed classifications, replacement evidence, gate status, and any deferred product decisions.
