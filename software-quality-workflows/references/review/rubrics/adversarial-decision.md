# Adversarial Decision Rubric

## Purpose
Try to falsify one high-consequence non-obvious claim without leaking an intended answer or expanding authority.

## Use when
- R2 involves security, data loss, concurrency, compatibility, migration/rollback, performance, scalability, or another consequential claim.

## Do not use when
- Mechanical work, a directly reproduced defect, or ordinary evidence already settles the claim.

## Required inputs
- One falsifiable claim/consequence, smallest governing contract, smallest artifact, revision, evidence, gaps, and authorized independent-pass boundary.

## Procedure
1. Strip persuasive framing and preferred answer; preserve constraints and identity.
2. Seek counterexamples, hidden state, stale/incomparable assumptions, missing consumers/data/threats, partial failure/retry/race/cancel/rollback, and false-green proof.
3. Test whether evidence observes the public contract or an internal proxy and whether conclusions survive removal of the strongest favorable sample.
4. Run the strongest proportionate independent pass; treat output as untrusted current-artifact evidence.
5. Classify candidate gaps as true, covered, false positive, or out of scope; unsupported concerns remain hypotheses.
6. Emit findings no stronger than coverage and proof; stop rather than loop for consensus.

## Required result
- Claim/contract/artifact identity, disconfirming checks, finding candidates, evidence boundary, residual uncertainty, and no approval/publication claim.

## Stop
Stop when disproven, materially reproved, explicitly bounded, or further review is speculative.
