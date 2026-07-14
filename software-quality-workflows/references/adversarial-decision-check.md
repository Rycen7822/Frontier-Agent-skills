# Adversarial Decision Check

Use this narrow reference for a high-consequence, non-obvious claim about security, data loss, concurrency, public compatibility, migration safety, performance, rollback, or scalability when ordinary self-review is not enough.

Do not use it for mechanical edits, formatting, straightforward failures already reproduced by a focused test, or as a substitute for user authority. Follow the [authority and scope owner](authority-and-scope.md) for review/delegation boundaries, the [review result schema](review-result-schema.md) for immutable findings, [review comments and pushback](review-comments-pushback.md) for their separate dispositions, and [verification discipline](verification-discipline.md) for final proof.

## Process

1. State one falsifiable claim in factual language and explain the consequence if it is wrong.
2. Extract the smallest contract that governs the claim: requirement, invariant, schema, migration rule, benchmark condition, or safety boundary.
3. Extract the smallest reviewable artifact: diff, function, protocol shape, rollout decision, benchmark result, or recovery plan.
4. Remove persuasive framing and the author's preferred answer. Preserve constraints, evidence, revision, and known gaps.
5. Seek disconfirming evidence: counterexamples, edge cases, hidden state, stale assumptions, incompatible consumers, failure recovery, and false-green proof.
6. Perform the strongest authorized independent pass that is proportionate to the consequence. If no separate reviewer is available, run a fresh local pass against only the claim, contract, and artifact.
7. Record `true gap`, `already covered`, `false positive`, or `out of scope` only as a preliminary assessment. For every schema-valid finding, use the canonical separate disposition: fixed and reverified, accepted as remaining risk, declined with evidence, or deferred with an explicit owner and trigger.
8. Rerun the proof affected by each true gap and restate the claim no more strongly than the evidence permits.

## Review questions

- Which assumption would most easily make the claim false?
- Does the evidence observe the public contract or only an internal proxy?
- Is the revision, input, environment, or baseline stale or incomparable?
- Could a partial failure, retry, cancellation, race, or rollback leave hidden state?
- Does the proposed safety argument depend on an undocumented operator action?
- Are important consumers, data variants, threat actors, or failure modes absent from coverage?
- Would the conclusion change if the strongest favorable sample were removed?

## Evidence hygiene

- Give an independent reviewer only the material needed to test the claim; do not leak the intended result.
- Treat reviewer output as untrusted evidence that must be checked against current artifacts.
- Keep unsupported concerns labeled as hypotheses, not findings.
- Distinguish “no issue found in covered scope” from “safe in all conditions.”

## Stop conditions

Stop when the claim is disproven, every material true gap is fixed and reproved, the evidence boundary is explicitly narrowed, or further review would be speculative. Do not loop for consensus, and do not use more review to compensate for a missing runtime or contract proof.

## Closeout

Report the final claim, contract, artifact revision, disconfirming checks performed, accepted findings, evidence boundary, and any residual uncertainty. Keep approval, merge state, and technical verdict as separate result dimensions through the schema owner.
