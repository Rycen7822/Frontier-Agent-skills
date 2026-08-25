from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "evaluation" / "model-evolution" / "sentinel_sources"))

from _model_evolution_contract import (  # noqa: E402
    ContractError,
    evaluator_evidence_status,
    validate_document,
)
import _model_evolution_contract as model_contract  # noqa: E402
from _model_evolution_campaign import (  # noqa: E402
    qualification_request_ceilings,
    require_qualification_request_ceilings,
)
from _model_evolution_qualification import _apparatus_artifact  # noqa: E402
from _model_evolution_materialization import (  # noqa: E402
    HOST_ARTIFACT_AUTHORITY_VERSION,
    MaterializationError,
    _host_artifact_inventory,
    _host_artifact_source,
    host_artifact_authority_document,
    observed_host_artifact_authority_document,
    validate_materialization_inputs,
)
from _model_evolution_ops import _minimal_schema_fixture  # noqa: E402
from _model_evolution_reporting import (  # noqa: E402
    _analysis_output_root,
    _canonical_analysis_paths,
    _recorded_current_analysis_paths,
    _registered_plan as analysis_plan,
    validate_confirmatory_revision_policy,
)
from _model_evolution_state import (  # noqa: E402
    StateError,
    refresh_current_evidence,
    rebind_product,
    register_plan,
)
from model_evolution import _registered_plan as record_plan  # noqa: E402
from skill_evaluator_verifier import _fixed_checks as evaluator_checks  # noqa: E402
from writing_plans_verifier import (  # noqa: E402
    DESCRIPTION_VALUE,
    _fixed_case_checks,
)


ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
SKILLS = {
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
}


def run_script(relative: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / relative), *arguments],
        cwd=ROOT,
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


class ExtendedRelease(unittest.TestCase):
    def test_d29_layered_host_authority_is_declared_and_fail_closed(self) -> None:
        relative = "evaluation/model-evolution/confirmatory-v3/sentinels/skill-evaluator/grader-output.schema.json"
        payload = (ROOT / relative).read_bytes()
        digest = "sha256:" + sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory(prefix="layered-host-authority-") as raw:
            campaign = Path(raw)
            duplicate = campaign / relative
            duplicate.parent.mkdir(parents=True)
            duplicate.write_bytes(payload)
            repository_binding = {
                "root": "repository",
                "path": relative,
                "digest": digest,
                "encoding": "utf-8",
            }
            self.assertEqual(
                ROOT / relative,
                _host_artifact_source(
                    repository_binding,
                    repository_root=ROOT,
                    campaign_root=campaign,
                    authority_version=HOST_ARTIFACT_AUTHORITY_VERSION,
                ),
            )
            campaign_path = campaign / "probes" / "probe.json"
            campaign_path.parent.mkdir()
            campaign_path.write_bytes(b"{}\n")
            campaign_binding = {
                "root": "campaign",
                "path": "probes/probe.json",
                "digest": "sha256:" + sha256(b"{}\n").hexdigest(),
                "encoding": "utf-8",
            }
            self.assertEqual(
                campaign_path,
                _host_artifact_source(
                    campaign_binding,
                    repository_root=ROOT,
                    campaign_root=campaign,
                    authority_version=HOST_ARTIFACT_AUTHORITY_VERSION,
                ),
            )
            for bad in (
                {**repository_binding, "root": "external"},
                {**repository_binding, "path": "../grader-output.schema.json"},
                {**repository_binding, "digest": "sha256:" + "0" * 64},
            ):
                with self.assertRaises(MaterializationError):
                    _host_artifact_source(
                        bad,
                        repository_root=ROOT,
                        campaign_root=campaign,
                        authority_version=HOST_ARTIFACT_AUTHORITY_VERSION,
                    )

    def test_d29_authority_lineage_maps_generated_probe_without_fallback(self) -> None:
        static_relative = "evaluation/model-evolution/confirmatory-v3/sentinels/skill-evaluator/grader-output.schema.json"
        static_payload = (ROOT / static_relative).read_bytes()
        with tempfile.TemporaryDirectory(prefix="layered-host-lineage-") as raw:
            campaign = Path(raw)
            probe_path = campaign / "probes" / "request.json"
            probe_path.parent.mkdir()
            probe_path.write_bytes(b'{"status":"pass"}\n')
            static_digest = "sha256:" + sha256(static_payload).hexdigest()
            host = {
                "capabilities": [
                    {
                        "probe": {
                            "artifact": {
                                "path": "probes/request.json",
                                "digest": "sha256:" + sha256(probe_path.read_bytes()).hexdigest(),
                                "encoding": "utf-8",
                            },
                            "locator": {"artifact": "probes/request.json"},
                        }
                    },
                    {
                        "probe": {
                            "artifact": {
                                "path": static_relative,
                                "digest": static_digest,
                                "encoding": "utf-8",
                            },
                            "locator": {"artifact": static_relative},
                        }
                    },
                ],
                "reset": {
                    "probe": {
                        "artifact": {
                            "path": static_relative,
                            "digest": static_digest,
                            "encoding": "utf-8",
                        },
                        "locator": {"artifact": static_relative},
                    }
                },
            }
            previous = {
                "schema_version": HOST_ARTIFACT_AUTHORITY_VERSION,
                "bindings": [
                    {
                        "index": 0,
                        "path": static_relative,
                        "root": "repository",
                        "digest": static_digest,
                        "encoding": "utf-8",
                    },
                    {
                        "index": 1,
                        "path": static_relative,
                        "root": "repository",
                        "digest": static_digest,
                        "encoding": "utf-8",
                    },
                    {
                        "index": 2,
                        "path": static_relative,
                        "root": "repository",
                        "digest": static_digest,
                        "encoding": "utf-8",
                    },
                ],
            }
            observed = observed_host_artifact_authority_document(
                host,
                previous,
                [
                    {
                        "path": "probes/request.json",
                        "digest": host["capabilities"][0]["probe"]["artifact"]["digest"],
                    }
                ],
            )
            self.assertEqual("campaign", observed["bindings"][0]["root"])
            self.assertEqual("repository", observed["bindings"][1]["root"])
            self.assertEqual("repository", observed["bindings"][2]["root"])

    def test_d29_explicit_inventory_consumes_authority_rows_without_fallback(self) -> None:
        static_relative = "evaluation/model-evolution/confirmatory-v3/sentinels/skill-evaluator/grader-output.schema.json"
        static_payload = (ROOT / static_relative).read_bytes()
        with tempfile.TemporaryDirectory(prefix="layered-host-inventory-") as raw:
            campaign = Path(raw)
            probe_path = campaign / "probes" / "request.json"
            probe_path.parent.mkdir()
            probe_path.write_bytes(b'{"status":"pass"}\n')
            static_digest = "sha256:" + sha256(static_payload).hexdigest()
            probe_digest = "sha256:" + sha256(probe_path.read_bytes()).hexdigest()
            host = {
                "capabilities": [
                    {
                        "probe": {
                            "artifact": {
                                "path": static_relative,
                                "digest": static_digest,
                                "encoding": "utf-8",
                            },
                            "locator": {"artifact": static_relative},
                        }
                    },
                    {
                        "probe": {
                            "artifact": {
                                "path": "probes/request.json",
                                "digest": probe_digest,
                                "encoding": "utf-8",
                            },
                            "locator": {"artifact": "probes/request.json"},
                        }
                    },
                ],
                "reset": {
                    "probe": {
                        "artifact": {
                            "path": static_relative,
                            "digest": static_digest,
                            "encoding": "utf-8",
                        },
                        "locator": {"artifact": static_relative},
                    }
                },
            }
            authority = {
                "schema_version": HOST_ARTIFACT_AUTHORITY_VERSION,
                "bindings": [
                    {
                        "index": 0,
                        "path": static_relative,
                        "root": "repository",
                        "digest": static_digest,
                        "encoding": "utf-8",
                    },
                    {
                        "index": 1,
                        "path": "probes/request.json",
                        "root": "campaign",
                        "digest": probe_digest,
                        "encoding": "utf-8",
                    },
                    {
                        "index": 2,
                        "path": static_relative,
                        "root": "repository",
                        "digest": static_digest,
                        "encoding": "utf-8",
                    },
                ],
            }
            rows = _host_artifact_inventory(
                host,
                repository_root=ROOT,
                campaign_root=campaign,
                authority=authority,
                require_explicit=True,
            )
            self.assertEqual(["repository", "campaign", "repository"], [row["root"] for row in rows])
            self.assertEqual(probe_path, Path(rows[1]["source"]))
            with self.assertRaisesRegex(MaterializationError, "count differs"):
                _host_artifact_inventory(
                    host,
                    repository_root=ROOT,
                    campaign_root=campaign,
                    authority={**authority, "bindings": authority["bindings"][:-1]},
                    require_explicit=True,
                )
    def test_host_artifact_uses_repository_authority_when_campaign_copy_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="host-artifact-authority-") as raw:
            root = Path(raw)
            repository = root / "repository"
            campaign = root / "campaign"
            relative = Path("evaluation/model-evolution/confirmatory-v3/grader-output.schema.json")
            repository_path = repository / relative
            campaign_path = campaign / relative
            repository_path.parent.mkdir(parents=True)
            campaign_path.parent.mkdir(parents=True)
            payload = b'{"schema_version":"test"}\n'
            repository_path.write_bytes(payload)
            campaign_path.write_bytes(payload)
            binding = {
                "path": relative.as_posix(),
                "digest": "sha256:" + sha256(payload).hexdigest(),
            }
            self.assertEqual(
                repository_path,
                _host_artifact_source(
                    binding,
                    repository_root=repository,
                    campaign_root=campaign,
                ),
            )
            repository_path.unlink()
            with self.assertRaisesRegex(MaterializationError, "authority is repository"):
                _host_artifact_source(
                    binding,
                    repository_root=repository,
                    campaign_root=campaign,
                )

    def test_preflight_v2_schema_fixtures_ignore_live_sentinel_binding(self) -> None:
        expected_binding = {
            "root": "repository",
            "path": "evaluation/model-evolution/probe-fixture.json",
        }
        live_bindings = (
            {
                "root": "repository",
                "path": "evaluation/model-evolution/sentinel-index-v2.json",
            },
            {
                "root": "campaign",
                "path": "evaluation/model-evolution/confirmatory-v1/sentinel-index-v3.json",
                "schema_version": "model-evolution-sentinel-index/3",
            },
        )
        normalized: list[tuple[dict[str, object], dict[str, object]]] = []
        for live_binding in live_bindings:
            campaign = {"sentinel_index": deepcopy(live_binding)}
            original = deepcopy(campaign)
            original_bytes = json.dumps(campaign, sort_keys=True).encode("utf-8")
            probes = _minimal_schema_fixture("interaction_probes", campaign)
            sentinel = _minimal_schema_fixture("sentinel_index", campaign)
            validate_document(probes, "interaction_probes")
            validate_document(sentinel, "sentinel_index")
            self.assertEqual(original, campaign)
            self.assertEqual(
                original_bytes, json.dumps(campaign, sort_keys=True).encode("utf-8")
            )
            probe_binding = probes["probes"][0]["fixture"]
            self.assertEqual(expected_binding, probe_binding)
            self.assertNotIn("schema_version", probe_binding)

            bindings: list[dict[str, str]] = []
            for skill in sentinel["skills"].values():
                for field in ("spec_template", "public_scenarios", "calibration_gold"):
                    self.assertEqual(expected_binding, skill[field])
                    bindings.append(skill[field])
                for field in ("fixture_roots", "verifier_roots"):
                    self.assertEqual([expected_binding], skill[field])
                    bindings.append(skill[field][0])
            self.assertEqual(len(bindings), len({id(binding) for binding in bindings}))
            self.assertNotIn(id(probe_binding), {id(binding) for binding in bindings})
            normalized.append((probes, sentinel))
        self.assertEqual(normalized[0], normalized[1])

    def test_confirmatory_v3_suite_identity_and_budget_are_frozen(self) -> None:
        index_path = (
            ROOT / "evaluation/model-evolution/confirmatory-v3/sentinel-index-v3.json"
        )
        index = json.loads(index_path.read_text(encoding="utf-8"))
        validate_document(index, "sentinel_index")
        catalog = {ROOT / binding["path"] for binding in index["catalog_files"]}
        actual_catalog = {
            path
            for path in index_path.parent.rglob("*")
            if path.is_file() and path != index_path
        }
        self.assertEqual(actual_catalog, catalog)
        self.assertFalse(any(path.is_symlink() for path in actual_catalog))
        policy, policy_digest = validate_confirmatory_revision_policy(
            ROOT / index["revision_policy"]["path"]
        )
        self.assertEqual("frontier-bundle-revision-policy/2", policy["schema_version"])
        self.assertTrue(policy_digest.startswith("sha256:"))
        ceilings = qualification_request_ceilings(
            index,
            repository_root=ROOT,
            campaign_root=ROOT,
            probe_count=6,
            apparatus_policy=json.loads((
                ROOT
                / "evaluation/model-evolution/confirmatory-v2/apparatus-retry-policy-v1.json"
            ).read_text()),
        )
        self.assertEqual(
            {
                "provider_requests": 2204,
                "execute": 1032,
                "model_grade": 1160,
                "calibration": 64,
                "calibration_attempts": 128,
                "valid_statistical_samples": 876,
                "apparatus_attempt_reserve": 156,
                "max_attempts_per_entry": 5,
            },
            ceilings,
        )
        supplied = {field: ceilings[field] for field in ("provider_requests", "execute", "model_grade")}
        require_qualification_request_ceilings(supplied, ceilings)
        for field in supplied:
            for offset in (-1, 1):
                changed = dict(supplied)
                changed[field] += offset
                with self.assertRaises(ContractError):
                    require_qualification_request_ceilings(changed, ceilings)

        scenarios_path = ROOT / index["skills"]["skill-evaluator"]["public_scenarios"]["path"]
        rows = [json.loads(line) for line in scenarios_path.read_text().splitlines()]
        ids = [row["case_id"] for row in rows]
        old_ids = {
            "skill-evaluator-level-owner-selection",
            "skill-evaluator-deterministic-first",
            "skill-evaluator-analyzer-exit-contract",
            "skill-evaluator-cli-schema-diagnosis",
            "skill-evaluator-transition-vs-revision",
            "skill-evaluator-protected-no-reviewer",
        }
        self.assertEqual(48, len(ids))
        self.assertEqual(48, len(set(ids)))
        self.assertFalse(set(ids) & old_ids)
        self.assertEqual(48, len({json.dumps(row, sort_keys=True) for row in rows}))
        spec_path = ROOT / index["skills"]["skill-evaluator"]["spec_template"]["path"]
        spec = json.loads(spec_path.read_text())
        self.assertEqual(3, spec["suite"]["repeats"])
        self.assertEqual(2, len(spec["treatments"]))
        self.assertTrue(all(set(treatment["scenario_ids"]) == set(ids) for treatment in spec["treatments"]))

        lineage_path = ROOT / index["case_lineage"]["path"]
        lineage = json.loads(lineage_path.read_text())
        self.assertEqual(48, lineage["case_count"])
        strata = {row["stratum"] for row in lineage["cases"]}
        self.assertEqual(6, len(strata))
        self.assertTrue(all(sum(row["stratum"] == stratum for row in lineage["cases"]) == 8 for stratum in strata))
        for row in lineage["cases"]:
            source = row["normative_source"].split("#", 1)[0]
            self.assertTrue((ROOT / source).is_file())
            self.assertTrue((scenarios_path.parent / row["fixture"]).is_file())

    def test_revision_report_consumer_dispatches_v3_and_v4_explicitly(self) -> None:
        v3 = {
            "schema_version": 3,
            "authority_eligibility": "eligible",
            "result": {"kind": "revision", "status": "closed"},
        }
        v4 = {
            "schema_version": 4,
            "authority_eligibility": "eligible",
            "result": {"kind": "revision", "status": "closed"},
            "metrics": [{
                "evidence_completeness": "complete",
                "revision_decision": "pass",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with patch.object(model_contract, "_validate_external_schema"):
                path.write_text(json.dumps(v3), encoding="utf-8")
                self.assertEqual("pass", evaluator_evidence_status(path, kind="revision_report"))
                path.write_text(json.dumps(v4), encoding="utf-8")
                self.assertEqual("pass", evaluator_evidence_status(path, kind="revision_report"))
                v4["metrics"][0]["revision_decision"] = "fail"
                path.write_text(json.dumps(v4), encoding="utf-8")
                self.assertEqual("blocked", evaluator_evidence_status(path, kind="revision_report"))
                v4["schema_version"] = 99
                path.write_text(json.dumps(v4), encoding="utf-8")
                with self.assertRaises(ContractError):
                    evaluator_evidence_status(path, kind="revision_report")

    def test_skill_evaluator_comparison_separator_is_fail_closed(self) -> None:
        answer = """- Comparison A — model-transition comparison: M1 to M2, Skill v3 frozen.
- Comparison B — controlled Skill-revision comparison: v3 to v4, model M2 frozen.
Host, tasks, grader, and policy remain frozen in both comparisons.
"""

        def passes(candidate: str) -> bool:
            return all(
                passed
                for passed, _ in evaluator_checks(
                    "transition-vs-revision", candidate
                ).values()
            )

        self.assertTrue(passes(answer))
        self.assertFalse(passes(answer.replace("Skill-revision", "model-revision")))
        self.assertFalse(passes(answer.replace("policy", "permissions")))

    def test_revision_uses_recorded_current_analysis_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign_root = Path(temp) / "campaign"
            repository_root = Path(temp) / "repository"
            repository_root.mkdir()
            analysis_root = (
                campaign_root / "analysis" / "target_current" / "skill-evaluator"
            )

            def write_pair(relative: str, marker: str) -> tuple[Path, Path]:
                summary = analysis_root / relative
                summary.parent.mkdir(parents=True, exist_ok=True)
                summary.write_text(
                    json.dumps({"schema_version": 6, "marker": marker}),
                    encoding="utf-8",
                )
                failures = summary.parent / "failure-index.json"
                failures.write_text(
                    json.dumps({"schema_version": 2, "marker": marker}),
                    encoding="utf-8",
                )
                return summary.resolve(), failures.resolve()

            canonical = write_pair("summary.json", "canonical")
            sidecars = {
                name: write_pair(f"{name}/summary.json", name)
                for name in ("d2-regrade", "d4-rebind")
            }
            campaign = {"skill_evidence": {"skill-evaluator": {}}}

            def select(relative: str) -> tuple[Path, Path]:
                campaign["skill_evidence"]["skill-evaluator"]["current_summary"] = {
                    "root": "campaign",
                    "path": (
                        "analysis/target_current/skill-evaluator/" + relative
                    ),
                    "schema_version": "6",
                }
                return _recorded_current_analysis_paths(
                    campaign=campaign,
                    repository_root=repository_root,
                    campaign_root=campaign_root,
                    skill_id="skill-evaluator",
                )

            self.assertEqual(canonical, select("summary.json"))
            for name, expected in sidecars.items():
                with self.subTest(sidecar=name):
                    self.assertEqual(expected, select(f"{name}/summary.json"))
                    self.assertNotEqual(canonical[0], expected[0])

    def test_revision_analysis_paths_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign_root = Path(temp) / "campaign"
            repository_root = Path(temp) / "repository"
            repository_root.mkdir()
            current_root = (
                campaign_root / "analysis" / "target_current" / "skill-evaluator"
            )
            prior_root = (
                campaign_root / "analysis" / "target_prior" / "skill-evaluator"
            )

            def write_json(path: Path, version: int) -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({"schema_version": version}), encoding="utf-8"
                )

            write_json(current_root / "summary.json", 6)
            write_json(current_root / "failure-index.json", 2)
            write_json(prior_root / "summary.json", 6)
            write_json(prior_root / "failure-index.json", 2)
            write_json(prior_root / "sidecar" / "summary.json", 6)
            write_json(prior_root / "sidecar" / "failure-index.json", 2)
            self.assertEqual(
                (prior_root / "summary.json", prior_root / "failure-index.json"),
                _canonical_analysis_paths(
                    campaign_root=campaign_root,
                    role="target_prior",
                    skill_id="skill-evaluator",
                ),
            )

            def binding(path: str, root: str = "campaign") -> dict[str, str]:
                return {"root": root, "path": path, "schema_version": "6"}

            rejected = [
                binding("analysis/target_current/skill-evaluator/summary.json", "repository"),
                binding("analysis/target_current/skill-evaluator/summary.json", "external"),
                binding("analysis/target_current/writing-plans/summary.json"),
                binding("analysis/target_current/skill-evaluator/a/b/summary.json"),
                binding("analysis/target_current/skill-evaluator/sidecar/report.json"),
                binding("analysis/target_current/skill-evaluator/bad$id/summary.json"),
            ]
            for candidate in rejected:
                campaign = {
                    "skill_evidence": {
                        "skill-evaluator": {"current_summary": candidate}
                    }
                }
                with self.subTest(binding=candidate), self.assertRaises(
                    MaterializationError
                ):
                    _recorded_current_analysis_paths(
                        campaign=campaign,
                        repository_root=repository_root,
                        campaign_root=campaign_root,
                        skill_id="skill-evaluator",
                    )

            missing = current_root / "missing" / "summary.json"
            write_json(missing, 6)
            symlinked = current_root / "symlinked" / "summary.json"
            write_json(symlinked, 6)
            (symlinked.parent / "failure-index.json").symlink_to(
                current_root / "failure-index.json"
            )
            for relative in ("missing/summary.json", "symlinked/summary.json"):
                campaign = {
                    "skill_evidence": {"skill-evaluator": {"current_summary": binding(
                        f"analysis/target_current/skill-evaluator/{relative}"
                    )}}
                }
                with self.subTest(relative=relative), self.assertRaises(
                    MaterializationError
                ):
                    _recorded_current_analysis_paths(
                        campaign=campaign,
                        repository_root=repository_root,
                        campaign_root=campaign_root,
                        skill_id="skill-evaluator",
                    )

            (prior_root / "summary.json").unlink()
            with self.assertRaises(MaterializationError):
                _canonical_analysis_paths(
                    campaign_root=campaign_root,
                    role="target_prior",
                    skill_id="skill-evaluator",
                )

    def test_prepare_analysis_variant_path_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            campaign = Path(temp) / "campaign"
            current_parent = campaign / "analysis" / "target_current"
            campaign.mkdir()
            canonical = _analysis_output_root(
                campaign,
                role="target_current",
                skill_id="skill-evaluator",
                analysis_variant=None,
            )
            self.assertEqual(current_parent / "skill-evaluator", canonical)

            canonical.mkdir(parents=True)
            variant = _analysis_output_root(
                campaign,
                role="target_current",
                skill_id="skill-evaluator",
                analysis_variant="d8-product-align",
            )
            self.assertEqual(canonical / "d8-product-align", variant)
            variant.mkdir()
            with self.assertRaises(MaterializationError):
                _analysis_output_root(
                    campaign,
                    role="target_current",
                    skill_id="skill-evaluator",
                    analysis_variant="d8-product-align",
                )

            for role in ("target_prior", "target_holdout"):
                with self.subTest(role=role), self.assertRaises(MaterializationError):
                    _analysis_output_root(
                        campaign,
                        role=role,
                        skill_id="skill-evaluator",
                        analysis_variant="sidecar",
                    )
            for unsafe in ("../sidecar", "a/b", "a..b", "/absolute", "bad$id"):
                with self.subTest(variant=unsafe), self.assertRaises(
                    MaterializationError
                ):
                    _analysis_output_root(
                        campaign,
                        role="target_current",
                        skill_id="writing-plans",
                        analysis_variant=unsafe,
                    )

            escaped = current_parent / "writing-plans"
            escaped.symlink_to(Path(temp) / "outside", target_is_directory=True)
            with self.assertRaises(MaterializationError):
                _analysis_output_root(
                    campaign,
                    role="target_current",
                    skill_id="writing-plans",
                    analysis_variant="sidecar",
                )

    def test_plan_replacement_is_strict_and_consumable(self) -> None:
        old = {
            "role": "target_current",
            "skill_id": "skill-evaluator",
            "plan": {"root": "campaign", "path": "old/plan.json"},
            "plan_digest": f"sha256:{'1' * 64}",
            "host_id": "host",
            "host_version": "1",
            "execute_ceiling": 72,
            "model_grade_ceiling": 48,
            "runner_status": {"completed": 0, "total": 36, "failed": 0},
        }
        new = {
            **old,
            "plan": {"root": "campaign", "path": "new/plan.json"},
            "plan_digest": f"sha256:{'2' * 64}",
        }
        state = {
            "state_revision": 10,
            "phase": "calibration_ready",
            "plans": [old],
            "candidate": None,
            "profiles": {"predecessor": None},
            "budgets": {
                "ceiling": {"execute": 200, "model_grade": 200,
                            "provider_requests": 400},
                "reserved": {"execute": 72, "model_grade": 48,
                             "provider_requests": 120},
            },
            "skill_evidence": {
                "skill-evaluator": {"grader_calibration": {"root": "campaign"}},
                "writing-plans": {"grader_calibration": {"root": "campaign"}},
            },
        }
        stopped = {
            "active_attempts": [],
            "recoverable_attempts": [],
            "indexed_attempts": 7,
        }
        empty = {
            "active_attempts": [],
            "recoverable_attempts": [],
            "indexed_attempts": 0,
            "completed_entries": 0,
            "invalid_attempts": 0,
        }

        def replace(
            candidate: dict[str, object] = new,
            *,
            old_status: dict[str, object] = stopped,
            new_status: dict[str, object] = empty,
            runner_stopped: bool = True,
        ) -> dict[str, object]:
            target = deepcopy(state)
            register_plan(
                target,
                deepcopy(candidate),
                replace_existing=True,
                old_runner_stopped=runner_stopped,
                old_runner_status=old_status,
                new_runner_status=new_status,
            )
            return target

        rejected = (
            {"runner_stopped": False},
            {"old_status": {**stopped, "active_attempts": ["attempt.1"]}},
            {"old_status": {**stopped, "recoverable_attempts": ["attempt.1"]}},
            {"new_status": {**empty, "indexed_attempts": 1}},
            {"candidate": {**new, "execute_ceiling": 73}},
            {"candidate": {**new, "skill_id": "writing-plans"}},
        )
        for arguments in rejected:
            with self.subTest(arguments=arguments), self.assertRaises(StateError):
                replace(**arguments)

        updated = replace()
        self.assertEqual(state["budgets"]["reserved"], updated["budgets"]["reserved"])
        self.assertEqual([new], updated["plans"])
        self.assertEqual(old["plan_digest"], updated["plan_replacement_lineage"][0]["plan_digest"])
        self.assertEqual(new, record_plan(updated, "target_current", "skill-evaluator"))
        self.assertEqual(new, analysis_plan(updated, "target_current", "skill-evaluator"))

    def test_product_rebind_is_strict_and_atomic(self) -> None:
        binding = {"root": "campaign", "path": "evidence.json"}
        skills = {
            "long-document-segmented-writing": {
                "version": "2.0.0", "root_hash": f"sha256:{'1' * 64}",
                "allow_implicit_invocation": True,
            },
            "skill-evaluator": {
                "version": "5.0.0", "root_hash": f"sha256:{'2' * 64}",
                "allow_implicit_invocation": False,
            },
            "software-quality-workflows": {
                "version": "11.0.1", "root_hash": f"sha256:{'3' * 64}",
                "allow_implicit_invocation": False,
            },
            "writing-plans": {
                "version": "8.4.0",
                "root_hash": "sha256:911e5913108029d3e95db6c111f304467896b607de8222615be4120670f7b516",
                "allow_implicit_invocation": True,
            },
        }
        product = {
            "bundle_id": "frontier-engineering/8.0.1",
            "bundle_version": "8.0.1",
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "dirty": False,
            "plugin_tree": f"sha256:{'4' * 64}",
            "plugin_build": binding,
            "plugin_root": "old-plugin",
            "calibration_requests": 64,
            "bundle_manifest": {"root": "repository", "path": "bundle-manifest.json"},
            "bundle_build": {"root": "repository", "path": "frontier-engineering.bundle.json"},
            "static_gate": {"schema_version": "static-contract-diagnostic/1.0", "status": "pass"},
            "skills": skills,
        }
        state = {
            "state_revision": 17,
            "phase": "decision_ready",
            "product": product,
            "apparatus_report": binding,
            "profiles": {"target_provisional": binding, "target_observed": binding},
            "plans": [{"skill_id": skill_id} for skill_id in sorted(SKILLS)],
            "skill_evidence": {
                skill_id: {"current_summary": binding} for skill_id in SKILLS
            },
        }
        rebound = deepcopy(product)
        rebound.update({
            "bundle_id": "frontier-engineering/8.0.2",
            "bundle_version": "8.0.2",
            "source_commit": "3" * 40,
            "source_tree": "4" * 40,
            "plugin_tree": f"sha256:{'5' * 64}",
            "plugin_build": {"root": "campaign", "path": "new-build.json"},
            "plugin_root": "new-plugin",
        })
        rebound["skills"] = deepcopy(skills)
        rebound["skills"]["writing-plans"].update({
            "version": "8.4.1",
            "root_hash": "sha256:1d5861c02e453cb7caab59c5b8a3c02f9971c5569bb5ee23a8308367acdaf51f",
        })
        idle = [{"active_attempts": [], "recoverable_attempts": []} for _ in SKILLS]

        def apply(candidate: dict[str, object] = rebound, **overrides: object) -> dict[str, object]:
            target = deepcopy(state)
            rebind_product(
                target,
                product=deepcopy(candidate),
                apparatus_report={"root": "campaign", "path": "new-report.json"},
                target_provisional={"root": "campaign", "path": "new-host.json"},
                target_observed={"root": "campaign", "path": "new-observed.json"},
                direct_descendant=bool(overrides.get("direct_descendant", True)),
                runner_statuses=overrides.get("runner_statuses", idle),
            )
            return target

        rejected: list[tuple[str, dict[str, object], dict[str, object]]] = []
        unchanged_wp = deepcopy(rebound)
        unchanged_wp["skills"]["writing-plans"] = deepcopy(skills["writing-plans"])
        rejected.append(("writing plans unchanged", unchanged_wp, {}))
        lane_drift = deepcopy(rebound)
        lane_drift["skills"]["skill-evaluator"]["root_hash"] = f"sha256:{'6' * 64}"
        rejected.append(("unaffected digest drift", lane_drift, {}))
        multi_drift = deepcopy(rebound)
        multi_drift["skills"]["skill-evaluator"]["version"] = "5.0.1"
        multi_drift["skills"]["software-quality-workflows"]["version"] = "11.0.2"
        rejected.append(("multiple Skill drift", multi_drift, {}))
        rejected.append(("non-descendant", rebound, {"direct_descendant": False}))
        active = deepcopy(idle)
        active[0]["active_attempts"] = ["attempt-0001"]
        rejected.append(("active attempt", rebound, {"runner_statuses": active}))
        recoverable = deepcopy(idle)
        recoverable[0]["recoverable_attempts"] = ["attempt-0001"]
        rejected.append(("recoverable attempt", rebound, {"runner_statuses": recoverable}))
        for label, candidate, overrides in rejected:
            with self.subTest(label=label), self.assertRaises(StateError):
                apply(candidate, **overrides)
            self.assertNotIn("product_rebind_lineage", state)

        updated = apply()
        self.assertEqual("calibration_ready", updated["phase"])
        self.assertIsNone(updated["skill_evidence"]["writing-plans"]["current_summary"])
        for skill_id in SKILLS - {"writing-plans"}:
            self.assertEqual(binding, updated["skill_evidence"][skill_id]["current_summary"])
        self.assertEqual(product, updated["product_rebind_lineage"][0]["old_product"])
        self.assertEqual(rebound, updated["product_rebind_lineage"][0]["new_product"])

    def test_d8_current_evidence_refresh_is_exact_and_single_use(self) -> None:
        def binding(path: str, schema: str = "6") -> dict[str, str]:
            return {
                "root": "campaign", "path": path, "schema_version": schema,
            }

        skill_ids = (
            "long-document-segmented-writing",
            "skill-evaluator",
            "software-quality-workflows",
            "writing-plans",
        )
        old_skills = {
            skill_id: {
                "version": version,
                "root_hash": f"sha256:{str(ordinal) * 64}",
                "allow_implicit_invocation": skill_id in {
                    "long-document-segmented-writing", "writing-plans",
                },
            }
            for ordinal, (skill_id, version) in enumerate(zip(
                skill_ids, ("2.0.0", "5.0.0", "11.0.1", "8.4.0"), strict=True
            ), start=1)
        }
        new_skills = deepcopy(old_skills)
        new_skills["writing-plans"].update({
            "version": "8.4.1", "root_hash": f"sha256:{'5' * 64}",
        })

        def product(version: str, source: str, skills: dict[str, object]) -> dict[str, object]:
            return {
                "bundle_id": f"frontier-engineering/{version}",
                "bundle_version": version,
                "source_commit": source,
                "source_tree": "6" * 40,
                "dirty": False,
                "plugin_tree": f"sha256:{'7' * 64}",
                "plugin_build": binding(f"build-{version}.json", "4.0"),
                "plugin_root": f"plugin-{version}",
                "calibration_requests": 64,
                "bundle_manifest": {"root": "repository", "path": "bundle-manifest.json"},
                "bundle_build": {"root": "repository", "path": "frontier-engineering.bundle.json"},
                "static_gate": {
                    "schema_version": "static-contract-diagnostic/1.0",
                    "status": "pass",
                },
                "skills": skills,
            }

        old_product = product("8.0.1", "8" * 40, old_skills)
        new_product = product("8.0.2", "9" * 40, new_skills)
        plans = [
            {
                "role": "target_current",
                "skill_id": skill_id,
                "plan": binding(f"current-plans/{skill_id}/plan.json", "3"),
                "plan_digest": f"sha256:{str(index) * 64}",
            }
            for index, skill_id in enumerate(skill_ids, start=1)
        ]
        prior = {"role": "target_prior", "skill_id": "skill-evaluator"}
        summaries = {
            skill_id: binding(f"analysis/target_current/{skill_id}/summary.json")
            for skill_id in skill_ids
        }
        state = {
            "state_revision": 26,
            "phase": "decision_ready",
            "candidate": None,
            "profiles": {"predecessor": None},
            "product": new_product,
            "plans": [*plans, prior],
            "budgets": {"reserved": {"provider_requests": 1292}},
            "skill_evidence": {
                skill_id: {"current_summary": summaries[skill_id], "revision_report": None}
                for skill_id in skill_ids
            },
            "product_rebind_lineage": [{
                "old_product": old_product,
                "new_product": new_product,
                "unchanged_skill_digests": {
                    skill_id: old_skills[skill_id]["root_hash"]
                    for skill_id in skill_ids[:-1]
                },
                "rebound_state_revision": 18,
            }],
        }
        refreshed = {
            skill_id: {
                "old_current_summary": summaries[skill_id],
                "old_current_summary_digest": f"sha256:{'a' * 64}",
                "old_plan": plans[index]["plan"],
                "old_plan_digest": plans[index]["plan_digest"],
                "unchanged_skill_digest": old_skills[skill_id]["root_hash"],
                "old_plugin_build": old_product["plugin_build"],
                "old_plugin_build_digest": f"sha256:{'b' * 64}",
            }
            for index, skill_id in enumerate(skill_ids[:-1])
        }
        proof = {
            "reason": "bundle_revision_full_product_alignment",
            "product_rebind_state_revision": 18,
            "refresh_before_state_revision": 26,
            "refresh_after_state_revision": 27,
            "old_product": old_product,
            "new_product": new_product,
            "refresh_set": list(skill_ids[:-1]),
            "refreshed_skills": refreshed,
            "retained_writing_plans": {
                "current_summary": summaries["writing-plans"],
                "current_summary_digest": f"sha256:{'c' * 64}",
                "plan": plans[3]["plan"],
                "plan_digest": plans[3]["plan_digest"],
                "plugin_build": new_product["plugin_build"],
                "plugin_build_digest": f"sha256:{'d' * 64}",
                "source_commit": new_product["source_commit"],
                "skill_digest": new_skills["writing-plans"]["root_hash"],
                "catalog_digest": f"sha256:{'e' * 64}",
            },
        }
        idle = {
            skill_id: {"active_attempts": [], "recoverable_attempts": []}
            for skill_id in skill_ids
        }
        stopped = {skill_id: True for skill_id in skill_ids}

        def rejected(
            *, state_value: dict[str, object] = state,
            proof_value: dict[str, object] = proof,
            status_value: dict[str, object] = idle,
            stopped_value: dict[str, bool] = stopped,
        ) -> None:
            with self.assertRaises(StateError):
                refresh_current_evidence(
                    deepcopy(state_value),
                    evidence=deepcopy(proof_value),
                    runner_statuses=deepcopy(status_value),
                    runners_stopped=deepcopy(stopped_value),
                )

        for field, value in (("phase", "current_evidence_ready"), ("state_revision", 25)):
            rejected(state_value={**state, field: value})
        for refresh_set in (
            list(skill_ids[:2]),
            [*skill_ids[:-1], "writing-plans"],
            list(skill_ids),
        ):
            rejected(proof_value={**proof, "refresh_set": refresh_set})
        bad_rebind = deepcopy(state)
        bad_rebind["product_rebind_lineage"][0]["new_product"]["source_tree"] = "0" * 40
        rejected(state_value=bad_rebind)
        for field in ("old_current_summary", "old_plan", "old_plugin_build"):
            bad_proof = deepcopy(proof)
            bad_proof["refreshed_skills"]["skill-evaluator"][field] = binding("wrong.json")
            rejected(proof_value=bad_proof)
        bad_wp = deepcopy(proof)
        bad_wp["retained_writing_plans"]["skill_digest"] = f"sha256:{'0' * 64}"
        rejected(proof_value=bad_wp)
        active = deepcopy(idle)
        active["skill-evaluator"]["active_attempts"] = ["attempt-0001"]
        rejected(status_value=active)
        not_stopped = {**stopped, "software-quality-workflows": False}
        rejected(stopped_value=not_stopped)

        updated = deepcopy(state)
        refresh_current_evidence(
            updated,
            evidence=deepcopy(proof),
            runner_statuses=idle,
            runners_stopped=stopped,
        )
        self.assertEqual("calibration_ready", updated["phase"])
        for skill_id in skill_ids[:-1]:
            self.assertIsNone(updated["skill_evidence"][skill_id]["current_summary"])
        self.assertEqual(
            summaries["writing-plans"],
            updated["skill_evidence"]["writing-plans"]["current_summary"],
        )
        self.assertEqual(state["product"], updated["product"])
        self.assertEqual(state["budgets"], updated["budgets"])
        self.assertEqual(prior, updated["plans"][-1])
        rejected(state_value=updated)

        schema = json.loads((
            ROOT / "evaluation/model-evolution/schemas/campaign-v3.schema.json"
        ).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        errors = list(validator.descend(
            updated["current_evidence_refresh_lineage"],
            schema["properties"]["current_evidence_refresh_lineage"],
        ))
        self.assertEqual([], errors)

    def test_writing_plans_parsed_description_proof_is_fail_closed(self) -> None:
        proof = f'''Plan `fixtures/agents/openai.yaml` from 8.2.0 to 8.2.1.
```python
from pathlib import Path
lines = Path("fixtures/agents/openai.yaml").read_text().splitlines()
values = dict(line.split(": ", 1) for line in lines)
assert values["version"] == "8.2.1"
assert values["description"] == "{DESCRIPTION_VALUE}"
```
'''

        def passes(answer: str) -> bool:
            checks = _fixed_case_checks("protected-description", answer)
            return all(passed for passed, _ in checks.values())

        self.assertTrue(passes(proof))
        self.assertFalse(passes(proof.replace(DESCRIPTION_VALUE, "EXPECTED_DESCRIPTION")))
        self.assertFalse(passes(
            proof.replace(
                f'assert values["description"] == "{DESCRIPTION_VALUE}"',
                f'correct = "{DESCRIPTION_VALUE}"\nassert values["description"] == "wrong"',
            )
        ))

    def test_apparatus_operation_uses_producer_verdict(self) -> None:
        operation = {
            "operation_id": "fake-candidate-analyze",
            "status": "pass",
            "duration_ms": 1,
            "state_revision": 0,
            "exit_code": 3,
            "diagnostic": None,
        }
        report = {
            "schema_version": "model-evolution-apparatus-report/2",
            "campaign_id": "campaign-test",
            "state_revision": 0,
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "status": "pass",
            "operations": [operation],
        }
        campaign = {
            "campaign_id": report["campaign_id"],
            "state_revision": 0,
            "product": {
                "source_commit": report["source_commit"],
                "source_tree": report["source_tree"],
            },
            "apparatus_report": {
                "root": "campaign",
                "path": "apparatus-report.json",
                "schema_version": "model-evolution-apparatus-report/2",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "apparatus-report.json"

            def validate(candidate: dict[str, object]) -> None:
                report["operations"] = [candidate]
                report_path.write_text(json.dumps(report), encoding="utf-8")
                _apparatus_artifact(campaign, ROOT, root)

            validate(operation)
            for exit_code in (True, "3", -1):
                with self.subTest(exit_code=exit_code):
                    with self.assertRaises(ContractError):
                        validate({**operation, "exit_code": exit_code})
            with self.assertRaises(ContractError):
                validate({**operation, "status": "fail"})

    def test_plugin_build_and_static_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            plugin = work / "frontier-engineering-plugin"
            evidence = work / "build.json"
            built = run_script(
                "scripts/build_codex_plugin.py",
                "--source-root",
                str(ROOT),
                "--output",
                str(plugin),
                "--evidence-output",
                str(evidence),
            )
            self.assertEqual(0, built.returncode, built.stdout + built.stderr)
            self.assertEqual(SKILLS, {path.name for path in (plugin / "skills").iterdir()})

            smoke_path = work / "smoke.json"
            smoked = run_script(
                "scripts/smoke_codex_plugin.py",
                "--plugin-root",
                str(plugin),
                "--build-evidence",
                str(evidence),
                "--output",
                str(smoke_path),
            )
            self.assertEqual(0, smoked.returncode, smoked.stdout + smoked.stderr)
            smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
            self.assertEqual("frontier-engineering/8.0.2", smoke["bundle_id"])
            self.assertFalse(smoke["actual_codex_cli_install"])

    def test_source_archives_are_clean_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            bundle_bytes = []
            for ordinal in range(2):
                archive = work / f"bundle-{ordinal}.zip"
                evidence = work / f"bundle-{ordinal}.json"
                result = run_script(
                    "scripts/build_source_archive.py",
                    "--source-root",
                    str(ROOT),
                    "--output",
                    str(archive),
                    "--evidence-output",
                    str(evidence),
                    "--layout",
                    "bundle",
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                bundle_bytes.append(archive.read_bytes())
                with zipfile.ZipFile(archive) as source:
                    names = source.namelist()
                self.assertTrue(all(name.startswith("frontier-engineering-bundle/") for name in names))
                self.assertFalse(
                    any(
                        part in {".git", ".work", ".worktrees", "reference", "__pycache__"}
                        for name in names
                        for part in Path(name).parts
                    )
                )
            self.assertEqual(bundle_bytes[0], bundle_bytes[1])

            skills_archive = work / "skills.zip"
            skills_evidence = work / "skills.json"
            result = run_script(
                "scripts/build_source_archive.py",
                "--source-root",
                str(ROOT),
                "--output",
                str(skills_archive),
                "--evidence-output",
                str(skills_evidence),
                "--layout",
                "skills_only",
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            with zipfile.ZipFile(skills_archive) as source:
                roots = {Path(name).parts[0] for name in source.namelist()}
            self.assertEqual(SKILLS, roots)


if __name__ == "__main__":
    unittest.main()
