# Code Smell Checklist

Use this rubric for a smell-only review, maintainability scan, or refactoring-target audit. It identifies design heuristics; it does not replace correctness, specification, security, or verification review.

Consume the scope and coverage from `references/requesting-code-review.md` and emit any finding through `references/review-result-schema.md` with a maintainability-oriented category.

## Boundary

- Review smells introduced, materially worsened, or made costlier by the scoped change.
- Do not promote unrelated pre-existing debt into the current result unless this change depends on or expands it.
- Repository conventions and an intentional local architecture take precedence over generic heuristics.
- A formatter, linter, type checker, or generator owns mechanical issues it can settle; report only the design concern that remains.
- Every finding needs contextual line evidence, a concrete maintenance impact, and a smaller safe alternative.
- A smell is not automatically blocking. Apply the schema's independent severity and blocking fields based on demonstrated impact.
- Do not disguise taste, product scope, missing specification, performance speculation, or a security concern as a smell.

## Review method

1. Identify changed ownership seams, public surfaces, high-churn functions, and wide call-site impact.
2. Read enough surrounding code to understand data flow and established local patterns.
3. Match candidates against the catalog, then ask whether the change introduced or worsened them.
4. Prefer a local rename, extract, inline, move-to-owner, or deletion of speculative machinery over broad redesign.
5. Report only actionable findings. Record clean important surfaces as positive notes when useful to a later fixer.

## Catalog

| Smell | Evidence to seek | Smallest usual correction |
|---|---|---|
| Mysterious name | A name hides responsibility, unit, state, or domain meaning | Rename it; if no honest name exists, clarify responsibility first |
| Duplicated code | Validation, mapping, query, control flow, or test setup can drift across sites | Centralize the shared rule while keeping call sites direct |
| Feature envy | Code reaches through another owner more than it uses its own data | Move behavior to the data owner or expose a narrow operation |
| Data clump | The same fields, parameters, or environment values repeatedly travel together | Use the existing owner or introduce one small cohesive value object |
| Primitive obsession | Strings, flags, dictionaries, or magic values stand in for a domain concept | Parse once at the boundary into a named type or value |
| Repeated dispatch | Equivalent conditional or status routing recurs across the change | Establish one decision owner or dispatch table |
| Shotgun surgery | One rule change requires scattered edits across layers | Gather the volatile rule into its owning seam |
| Divergent responsibility | One module changes for unrelated reasons | Separate responsibilities at an existing stable boundary |
| Speculative generality | A mode, hook, fallback, adapter, or abstraction has no current consumer | Delete or inline it until a demonstrated second use exists |
| Message chain | Callers traverse foreign internals or nested schema layout | Hide the traversal behind the appropriate owner |
| Middle man | A wrapper delegates without adding policy, validation, or ownership | Remove the pass-through and call the actual owner |
| Refused contract | An implementation ignores material inherited/interface assumptions | Narrow the contract or use composition |

Object-oriented names translate to modules, services, scripts, plugins, schemas, and test helpers. In tests, report smells only when they obscure behavior, duplicate production logic, couple fixtures to internals, preserve project residue, or make later change risky.

If no material smell is found, say so and name the important changed surfaces reviewed. Do not manufacture a finding to fill the result.
