# Skill Evaluator contract schemas

These Draft 2020-12 schemas are the machine owners for the Skill Evaluator 3.1
contracts. Runner status is a read-only control surface; scored wires remain:

- [Evaluation spec v5](eval-spec-v5.schema.json)
- [Scenario v1](scenario-v1.schema.json)
- [Execution plan v1](execution-plan-v1.schema.json)
- [Host manifest and protocol v1](host-manifest-v1.schema.json)
- [Run-index row v2](run-index-row-v2.schema.json)
- [Runner status v1](runner-status-v1.schema.json)
- [Receipt v4](receipt-v4.schema.json)
- [Grader calibration v2](grader-calibration-v2.schema.json)
- [Suite quality v1](suite-quality-v1.schema.json)
- [Analysis summary v4](analysis-summary-v4.schema.json)
- [Failure index v1](failure-index-v1.schema.json)

The opt-in offline comparison path adds:

- [Comparison plan v1](comparison-plan-v1.schema.json)
- [Comparison observations v1](comparison-observations-v1.schema.json)
- [Comparison report v1](comparison-report-v1.schema.json)
- [Comparison diagnostic index v1](comparison-diagnostic-index-v1.schema.json)

Resolve relative `$ref` values from the referring schema file. JSON Schema owns
shape and local types; the validator, compiler, runner, and analyzer own the
cross-record semantics named by their public contracts.
