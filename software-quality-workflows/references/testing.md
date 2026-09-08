# YAGNI testing

Use when deciding whether a test adds real protection, or when maintaining a costly suite.

Keep a test when it distinguishes changed behavior, a stable contract, a known regression or a material risk at reasonable cost. Prefer extending existing coverage. Simple equivalent edits, documentation and temporary experiments usually need no new permanent test. Test-first is useful when the oracle is clear and cheap, not a universal gate.

Derive expectations from requirements, an independent reference, a worked example or a meaningful property. Identify a plausible defect the check would reject. Round trips can hide a shared defect on both sides; add an independent expectation when needed. Mocking, negative assertions and properties can be valid. Judge protection by behavior, not the assertion function's name.

Keep one-off reproductions and diagnostic probes temporary. Remove or merge duplicate protection and retire tests for intentionally removed behavior. Rewrite implementation mirrors when a stable behavior deserves protection; do not lock incidental prompt wording, private call order or file layout. A test's accidental inconvenience is not reason to delete its unique protection.

For migration-only checks, note the concrete removal condition beside the check when it will otherwise outlive its purpose. Do not build retention registries, per-test classification reports or exhaustive matrices. Review the affected scope unless broader cleanup is requested.

Run the nearest meaningful check after the coherent change. Broaden only for failure, cross-cutting impact or remaining uncertainty. A pre-change setup failure is not a regression demonstration, and changing expected values merely to pass does not repair the product.
