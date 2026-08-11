# Skill Evaluator contract schemas

These Draft 2020-12 schemas are the machine owners for the Skill Evaluator 4.0
contracts. Runner status is a read-only control surface; scored wires remain:

- [Evaluation spec v6](eval-spec-v6.schema.json)
- [Scenario v1](scenario-v1.schema.json)
- [Execution plan v2](execution-plan-v2.schema.json)
- [Host manifest and protocol v2](host-manifest-v2.schema.json)
- [Run index v3](run-index-v3.schema.json)
- [Runner status v2](runner-status-v2.schema.json)
- [Receipt v5](receipt-v5.schema.json)
- [Grader calibration v3](grader-calibration-v3.schema.json)
- [Suite quality v2](suite-quality-v2.schema.json)
- [Analysis summary v5](analysis-summary-v5.schema.json)
- [Failure index v2](failure-index-v2.schema.json)

The opt-in offline comparison path adds:

- [Comparison cycle capsule v2](comparison-cycle-capsule-v2.schema.json)
- [Comparison plan v2](comparison-plan-v2.schema.json)
- [Comparison observations v2](comparison-observations-v2.schema.json)
- [Comparison report v2](comparison-report-v2.schema.json)
- [Comparison diagnostic index v2](comparison-diagnostic-index-v2.schema.json)

Resolve relative `$ref` values from the referring schema file. JSON Schema owns
shape and local types; the validator, compiler, runner, and analyzer own the
cross-record semantics named by their public contracts.
