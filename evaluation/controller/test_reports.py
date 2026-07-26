from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from . import artifacts, campaign, reports, specs, studies
from .controller_testkit import (
    initialize,
    p4_identity,
    p4_steps,
    planner_source,
    release_studies,
    receipt,
    request_entry,
    reserve,
)


EXPECTED_CALLS = {
    "d0-sqw": (20, 12, 0),
    "d0-writing-plans": (16, 16, 0),
    "d0-writing-plans-transfer": (12, 0, 4),
    "formal-sqw": (96, 64, 0),
    "formal-writing-plans": (56, 48, 0),
    "formal-writing-plans-transfer": (32, 0, 0),
}


def design(profile: str) -> specs.StudyDesign:
    if profile.startswith("formal-"):
        return specs.fixed_design(
            profile,
            sqw=specs.sqw_cases(),
            plans=specs.writing_plan_cases(),
        )
    return specs.fixed_design(profile)


@pytest.mark.parametrize(("profile", "expected"), EXPECTED_CALLS.items())
def test_fixed_profiles_close_frozen_call_partitions(
    profile: str,
    expected: tuple[int, int, int],
) -> None:
    study = design(profile)
    assert specs.EXECUTION_TIMEOUT_SECONDS == 660
    assert (
        study.expected_execute,
        study.expected_model_grade,
        study.expected_mechanism,
    ) == expected
    assert study.expected_execute == sum(
        len(case.applicable_profiles) * study.repeats
        for case in study.cases
    )
    assert study.expected_model_grade == sum(
        len(case.applicable_profiles) * study.repeats
        for case in study.cases
        if case.model_grading
    )


@pytest.mark.parametrize("profile", EXPECTED_CALLS)
def test_case_identity_and_treatment_profiles_are_unambiguous(
    profile: str,
) -> None:
    study = design(profile)
    case_ids = [case.case_id for case in study.cases]
    assert len(case_ids) == len(set(case_ids))
    assert all(case.applicable_profiles for case in study.cases)
    assert all(
        len(case.applicable_profiles) == len(set(case.applicable_profiles))
        for case in study.cases
    )


@pytest.mark.parametrize(
    "skill_id",
    ["software-quality-workflows", "writing-plans"],
)
def test_model_check_inventory_is_closed(skill_id: str) -> None:
    checks = specs.model_checks(skill_id)
    assert len(checks) == 10
    assert len({check_id for check_id, _, _ in checks}) == 10
    assert all(category in {"outcome", "process", "quality", "safety"} for _, category, _ in checks)


def test_unknown_or_unbound_formal_profile_fails_closed() -> None:
    with pytest.raises(specs.SpecificationError):
        specs.fixed_design("unknown")
    with pytest.raises(specs.SpecificationError):
        specs.fixed_design("formal-sqw")


@pytest.mark.parametrize(
    "skill_id",
    ["software-quality-workflows", "writing-plans"],
)
def test_calibration_partition_is_eight_blinded_provider_requests(
    skill_id: str,
) -> None:
    pack = studies.calibration_pack(skill_id)
    batches = studies.batch_schedule(pack)
    assert len(pack) == 16
    assert {
        class_name: sum(
            item["calibration_class"] == class_name
            for item in pack
        )
        for class_name in ("known_good", "known_bad", "boundary", "abstain")
    } == {
        "known_good": 4,
        "known_bad": 4,
        "boundary": 4,
        "abstain": 4,
    }
    assert [len(batch) for batch in batches] == [4, 4, 4, 4]
    assert {item["artifact_id"] for item in pack} == {
        item_id for batch in batches for item_id in batch
    }


@pytest.mark.parametrize(
    "skill_id",
    ["software-quality-workflows", "writing-plans"],
)
def test_reviewer_projection_is_lossless_and_positional(skill_id: str) -> None:
    arguments = {
        "campaign_id": "campaign-01",
        "study_id": "study-01",
        "study_profile": "profile-01",
        "skill_id": skill_id,
        "controller_content_hash": "sha256:" + "1" * 64,
        "output_schema": studies.reviewer_output_schema(),
    }
    projection = studies.semantic_projection(**arguments)
    assert studies.semantic_projection(**arguments) == projection
    assert len(projection["packet"]["examples"]) == 160
    packet = projection["packet"]
    compact = studies.compact_packet(packet)
    assert studies.expand_packet(compact) == packet
    response = {
        "schema_version": studies.RATINGS_SCHEMA,
        "ratings": [
            {"label": "pass", "severity": index / 2}
            for index, _ in enumerate(packet["examples"])
        ],
    }
    response["ratings"][-1]["label"] = "abstain"
    parsed = studies.positional_ratings(response, packet["examples"])
    assert [row["opaque_example_id"] for row in parsed] == [
        row["opaque_example_id"] for row in packet["examples"]
    ]
    assert all(set(row) == {"opaque_example_id", "label", "severity"} for row in parsed)
    assert parsed[-1]["label"] == "abstain"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda response: response.update({"reviewer_id": "forbidden"}),
        lambda response: response["ratings"].append({"label": "pass", "severity": 0}),
        lambda response: response["ratings"][0].update({"severity": True}),
        lambda response: response["ratings"][0].update({"severity": float("inf")}),
        lambda response: response["ratings"][0].update({"opaque_example_id": "forbidden"}),
    ],
)
def test_positional_reviewer_output_fails_closed(mutate) -> None:
    examples = [{"opaque_example_id": "opaque-1"}]
    response = {
        "schema_version": studies.RATINGS_SCHEMA,
        "ratings": [{"label": "pass", "severity": 0.5}],
    }
    mutate(response)
    with pytest.raises(ValueError):
        studies.positional_ratings(response, examples)


def test_planner_receipts_bind_transfer_design(tmp_path: Path) -> None:
    base = specs.fixed_design("d0-writing-plans-transfer")
    plan_hash = planner_source(tmp_path, [case.case_id for case in base.cases])
    deliverables = studies.verified_planner_deliverables(
        tmp_path,
        case_ids={case.case_id for case in base.cases},
        repeats=1,
    )
    assert {key[2] for key in deliverables} == {"baseline", "candidate"}
    assert {item["planner_plan_hash"] for item in deliverables.values()} == {
        plan_hash,
    }
    transfer = studies.transfer_design(
        "d0-writing-plans-transfer",
        tmp_path,
    )
    assert (
        transfer.expected_execute,
        transfer.expected_model_grade,
        transfer.expected_mechanism,
        transfer.repeats,
        len(transfer.cases),
    ) == (12, 0, 4, 1, 4)
    assert all(len(case.transfer_source["bindings"]) == 2 for case in transfer.cases)


def test_controller_passes_three_bound_studies_to_public_projection(
    tmp_path: Path,
) -> None:
    roots, join = release_studies(tmp_path)
    analyzer = mock.Mock()
    analyzer.project_release_estimands.return_value = {"status": "complete"}
    projection, summaries = reports.project_release(
        analyzer=analyzer,
        roots=roots,
        manual_receipts={
            "software-quality-workflows": "manual/sqw.json",
            "writing-plans-planner": "manual/planner.json",
            "writing-plans-transfer": None,
        },
        join_path=join,
        seed=2735,
    )
    assert projection["status"] == "complete"
    assert set(summaries) == set(reports.STUDIES)
    bindings = analyzer.project_release_estimands.call_args.args[0]
    assert [item["study_id"] for item in bindings] == list(reports.STUDIES)
    assert set(bindings[0]) == {
        "study_id",
        "spec",
        "plan",
        "index",
        "summary",
        "failure_index",
        "manual_receipt_locator",
    }


def test_evaluator_has_no_private_or_legacy_native_reader() -> None:
    source = Path(reports.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "_load_release_study",
        "_collect_v5_evidence",
        "_verify_v5",
        "eval-spec.json",
        "runs.jsonl",
        "receipt-v3",
        "run-index-v1",
    ):
        assert forbidden not in source


def test_gate_inventory_and_threshold_owner_are_exact() -> None:
    assert {
        phase: tuple(
            len(contract[arm])
            for arm in ("software-quality-workflows", "writing-plans")
        )
        for phase in ("d0", "formal")
        for contract in (specs.gate_contract(phase),)
    } == {"d0": (11, 21), "formal": (18, 22)}
    gates = [
        specs.gate("point", "arm", "point_metric", "ge", 0.25, selector="point"),
        {
            **specs.gate("relative", "arm", "candidate", "le", 0.5),
            "threshold": {
                "kind": "relative_metric",
                "scalar": 0.5,
                "numerator": None,
                "denominator": None,
                "comparator_metric_id": (
                    "/projection/arm/release_metrics/baseline"
                ),
            },
        },
    ]
    passed, failed = reports.evaluate_gates(gates, {
        "projection": {
            "arm": {
                "release_metrics": {
                    "point_metric": {"point": 0.5},
                    "candidate": 2,
                    "baseline": 4,
                },
            },
        },
    })
    assert [item["gate_id"] for item in passed] == ["point", "relative"]
    assert failed == []


def test_count_pair_gate_compares_both_values() -> None:
    gate = specs.gate(
        "pair",
        "writing_plans",
        "transfer_preflight",
        "eq",
        8,
        selector="numerator",
        threshold_kind="count_pair",
        denominator=8,
    )
    passed, failed = reports.evaluate_gates([gate], {
        "projection": {
            "writing_plans": {
                "release_metrics": {
                    "transfer_preflight": {"numerator": 8, "denominator": 7},
                },
            },
        },
    })
    assert passed == []
    assert [item["gate_id"] for item in failed] == ["pair"]


@pytest.mark.parametrize(
    ("phase", "counts"),
    [("d0", (76, 8, 4)), ("formal", (296, 8, 4))],
)
def test_provider_budget_contract_is_exact(
    tmp_path: Path,
    phase: str,
    counts: tuple[int, int, int],
) -> None:
    required = []
    for family, count, kind in (
        ("scored", counts[0], "execute"),
        ("grader_calibration", counts[1], "grader_calibration"),
        ("reviewer_calibration", counts[2], "context_isolated_review"),
    ):
        required.extend(
            request_entry(
                f"{family}-{index}",
                family=family,
                request_kind=kind,
            )
            for index in range(count)
        )
    path = tmp_path / "manifest.json"
    campaign.write_request_manifest(
        path,
        campaign_id=f"{phase}-campaign",
        required_requests=required,
        conditional_requests=[],
    )
    contract = reports.budget_contract(phase, path)
    assert tuple(
        contract[field]
        for field in (
            "scored_call_hard_cap",
            "grader_calibration_call_hard_cap",
            "reviewer_calibration_call_hard_cap",
            "provider_call_hard_cap",
        )
    ) == (*counts, sum(counts))


def test_usage_closure_uses_manifest_ledger_and_receipts(tmp_path: Path) -> None:
    definitions = [
        ("sqw-execute", "frontier-formal-software-quality-workflows", "scored", "execute"),
        ("sqw-grade", "frontier-formal-software-quality-workflows", "scored", "model_grade"),
        ("sqw-calibrate", "frontier-formal-software-quality-workflows", "grader_calibration", "grader_calibration"),
        ("sqw-review", "frontier-formal-software-quality-workflows", "reviewer_calibration", "context_isolated_review"),
        ("plan-execute", "frontier-formal-writing-plans-planner", "scored", "execute"),
        ("transfer-execute", "frontier-formal-writing-plans-transfer", "scored", "execute"),
    ]
    entries = [
        request_entry(
            request_id,
            study=study,
            family=family,
            request_kind=kind,
        )
        for request_id, study, family, kind in definitions
    ]
    attempt = tmp_path / "attempt"
    initialize(attempt, required=entries)
    receipts = []
    for entry in entries:
        reserve(attempt, entry["request_id"])
        receipts.append(receipt(attempt, entry["request_id"]))
    sqw = reports.usage_closure(
        ("software-quality-workflows",),
        attempt,
        receipts,
    )
    plans = reports.usage_closure(
        ("writing-plans-planner", "writing-plans-transfer"),
        attempt,
        receipts,
    )
    assert (
        sqw["scored_provider_calls"],
        sqw["grader_calibration_provider_calls"],
        sqw["reviewer_calibration_provider_calls"],
        sqw["provider_calls"],
    ) == (2, 1, 1, 4)
    assert (
        plans["scored_provider_calls"],
        plans["provider_calls"],
    ) == (2, 2)


def test_git_preflight_fails_before_contract_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def dirty(repo: Path, *arguments: str) -> str:
        calls.append((repo, arguments))
        return "dirty"

    monkeypatch.setattr(artifacts, "git_read", dirty)
    output = tmp_path / "decision.json"
    with pytest.raises(artifacts.StateError, match="must be clean"):
        reports.create_decision_contract(
            phase="d0",
            repo=tmp_path,
            candidate_plugin_root=tmp_path,
            controller_manifest_path=tmp_path / "absent-controller.json",
            request_manifest_path=tmp_path / "absent-requests.json",
            output=output,
        )
    assert calls == [(
        tmp_path,
        ("status", "--porcelain=v2", "--untracked-files=all"),
    )]
    assert not output.exists()


def test_calibration_requires_pair_and_accepts_numeric_severity() -> None:
    bound_hash = "sha256:" + "1" * 64
    pack = [{
        "artifact_id": "cal-1",
        "expected_checks": {"check-1": True},
        "expected_overall": True,
        "calibration_class": "known_good",
        "grader_view": {"answer": "ok"},
    }]
    outputs = {
        "cal-1": {
            "checks": [{"id": "check-1", "pass": True, "uncertainty": "low"}],
        },
    }
    spec = {
        "graders": [{
            "grader_id": "blind-rubric",
            "model": "gpt-5.6-luna",
            "prompt": {"sha256": bound_hash},
            "output_schema": {"sha256": bound_hash},
            "checks": [{
                "check_id": "check-1",
                "dimension": "outcome",
                "pass_condition": "works",
            }],
        }],
        "host": {"manifest": {"sha256": bound_hash}},
        "risk_tier": "standard",
    }
    host_manifest = {
        "identity": {
            "adapter": {"sha256": bound_hash},
            "host_id": "host-1",
        },
    }
    mapping = {"opaque-1": {"dimension": "outcome", "check_id": "check-1"}}
    reviews = [
        {
            "example_id": "opaque-1",
            "reviewer_id": f"reviewer-{index}",
            "principal_id": f"principal-{index}",
            "label": "pass",
            "severity": 0.5 if index == 1 else 0,
        }
        for index in (1, 2)
    ]
    kwargs = {
        "pack": pack,
        "outputs": outputs,
        "spec": spec,
        "host_manifest": host_manifest,
        "reviewer_mapping": mapping,
    }
    with pytest.raises(reports.ReportError, match="two complete"):
        reports.calibration_rows(reviewer_reviews=reviews[:1], **kwargs)
    _, ratings = reports.calibration_rows(reviewer_reviews=reviews, **kwargs)
    assert 0.5 in [row["severity"] for row in ratings]


def test_p4_recomputes_all_gates_and_writes_schema_valid_report(
    tmp_path: Path,
) -> None:
    metrics = reports.compute_p4_metrics(
        p4_steps(),
        selected_provider_calls=78,
        retry_provider_calls=0,
    )
    schema = Path(__file__).resolve().parents[2] / (
        "packaging/schemas/frontier-longitudinal-report-v1.schema.json"
    )
    result = reports.write_p4_report(
        identity=p4_identity(),
        decision_contract_hash="sha256:" + "6" * 64,
        campaign_contract_hash="sha256:" + "7" * 64,
        selected_receipts=[],
        step_hashes={
            f"step-{index:02d}": "sha256:" + "8" * 64
            for index, _ in enumerate(p4_steps(), start=1)
        },
        metrics=metrics,
        report_schema_path=schema,
        report_schema_hash=artifacts.file_hash(schema),
        output_root=tmp_path / "output",
    )
    report = artifacts.load_json(
        tmp_path / "output/frontier-longitudinal-report.json",
    )
    assert result == {"status": "passed", "provider_requests": 0}
    assert len(report["gate_results"]) == 17
    assert all(gate["passed"] for gate in report["gate_results"])


def test_p4_product_failure_writes_only_a_diagnostic(tmp_path: Path) -> None:
    metrics = reports.compute_p4_metrics(
        p4_steps(candidate_runtime=106),
        selected_provider_calls=78,
        retry_provider_calls=0,
    )
    output = tmp_path / "output"
    result = reports.write_p4_report(
        identity=p4_identity(),
        decision_contract_hash="sha256:" + "6" * 64,
        campaign_contract_hash="sha256:" + "7" * 64,
        selected_receipts=[],
        step_hashes={},
        metrics=metrics,
        report_schema_path=tmp_path / "unused.json",
        report_schema_hash="sha256:" + "8" * 64,
        output_root=output,
    )
    assert result["status"] == "failed"
    assert (output / "attempt-diagnostic.json").is_file()
    assert not (output / "frontier-longitudinal-report.json").exists()
