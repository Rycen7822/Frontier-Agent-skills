from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_skill_contracts.py"
SPEC = importlib.util.spec_from_file_location("validate_skill_contracts", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def make_minimal_skill(root: Path) -> None:
    (root / "references").mkdir()
    (root / "tests" / "fixtures").mkdir(parents=True)
    resources = ["references/synthetic-core.md"]
    links = "\n".join(f"- [{Path(item).stem}]({item})" for item in resources)
    (root / "SKILL.md").write_text(
        "---\n"
        "name: software-quality-workflows\n"
        "description: Synthetic contract fixture for validator tests.\n"
        "license: MIT\n"
        "metadata:\n"
        "  version: 2.0.0\n"
        "  author: Hermes Agent\n"
        "  hosts: [codex, hermes-agent]\n"
        "  hermes:\n"
        "    tags: [development, testing, verification]\n"
        "    category: software-development\n"
        "    related_skills: [writing-plans]\n"
        "---\n\n"
        "# Fixture Skill\n\n"
        "## Owner contract\n\n"
        "Each policy has one owner.\n\n"
        "## Active resources\n\n"
        f"{links}\n",
        encoding="utf-8",
    )
    for resource in resources:
        path = root / resource
        path.parent.mkdir(parents=True, exist_ok=True)
        title = Path(resource).stem.replace("-", " ").title()
        body = f"# {title}\n\nSynthetic owner.\n"
        path.write_text(body, encoding="utf-8")
    fixture_source = ROOT / "tests" / "fixtures" / "decision-cases.json"
    (root / "tests" / "fixtures" / "decision-cases.json").write_text(
        fixture_source.read_text(encoding="utf-8"), encoding="utf-8"
    )


def valid_manifest() -> dict:
    return {
        "base_revision": "base-1",
        "head_revision": "head-2",
        "scope_hash": "scope-hash-2",
        "paths": [
            {
                "path": "src/core.py",
                "status": "modified",
                "snapshot_id": "sha256:core-2",
            }
        ],
    }


def valid_result() -> dict:
    return {
        "schema_version": "3.0",
        "code_review_verdict": "pass",
        "verification_status": "passed",
        "spec_traceability": {
            "status": "complete",
            "evidence_refs": ["traceability:matrix#TRACE-001"],
        },
        "coverage": [
            {"path": "src/core.py", "status": "full", "snapshot_id": "sha256:core-2"}
        ],
        "blocking_reasons": [],
        "reviewed_base_sha": "base-1",
        "reviewed_head_sha": "head-2",
        "reviewed_scope_hash": "scope-hash-2",
        "findings": [
            {
                "id": "F-001",
                "severity": "low",
                "blocking": False,
                "category": "maintainability",
                "path": "src/core.py",
                "line": 12,
                "evidence": "The branch duplicates an existing guard.",
                "impact": "Two paths can drift.",
                "recommended_fix": "Reuse the existing guard.",
                "confidence": "high",
                "verification": "Focused test passed.",
                "code_fixable": True,
                "source_revision": "head-2"
            }
        ]
    }


def valid_context() -> dict:
    return {
        "scope_manifest": valid_manifest(),
        "current_head": "head-2",
        "current_scope_hash": "scope-hash-2",
    }


class SkillContractTests(unittest.TestCase):
    def test_active_skill_satisfies_contracts(self) -> None:
        violations = validator.validate_skill(ROOT)
        if violations:
            self.fail(validator.compact_violations(violations))

    def test_decision_fixture_contract(self) -> None:
        path = ROOT / "tests" / "fixtures" / "decision-cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([], validator.validate_decision_cases(cases))
        ids = {case["id"] for case in cases}
        self.assertTrue(
            {
                "review_only",
                "diagnose_only",
                "complex_bugfix",
                "existing_patch",
                "debug_existing_pid",
                "pr_review",
                "docs_only",
                "public_api_change",
                "long_output_failure",
                "requirements_traceability_review",
                "module_boundary_refactor",
                "flaky_reproducer_minimization",
                "merge_conflict_resolution",
                "independent_oracle_change",
                "wide_api_migration",
                "prototype_experiment",
            }
            <= ids
        )

    def test_engineering_absorption_contracts(self) -> None:
        conflict_resource = "references/recovery/conflict-recovery.md"
        traceability_resource = "references/review/execution-and-requirements.md"
        architecture_resource = "references/domain/architecture/boundaries-and-alternatives.md"
        manifest = json.loads((ROOT / "registries" / "reference-cards.manifest.json").read_text(encoding="utf-8"))
        card_paths = {item["path"] for item in manifest["cards"]}
        self.assertTrue({conflict_resource, traceability_resource, architecture_resource, "references/workspace/prototype-lifecycle.md"}.issubset(card_paths))

        architecture = (ROOT / architecture_resource).read_text(encoding="utf-8").lower()
        alternatives = architecture
        self.assertIn("caller knowledge", architecture)
        self.assertIn("deletion, and distribution", architecture)
        self.assertIn("smallest supported design", architecture)
        self.assertIn("materially different", alternatives)
        self.assertIn("reversibility", alternatives)

        traceability = (ROOT / traceability_resource).read_text(encoding="utf-8").lower()
        self.assertIn("requirement→implementation→proof matrix", traceability)
        for status in ("full", "partial", "missing", "not-applicable"):
            self.assertIn(status, traceability)
        self.assertIn("trace stable requirements to implementation and proof", traceability)
        self.assertIn("never invent acceptance criteria", traceability)

        conflict = (ROOT / conflict_resource).read_text(encoding="utf-8").lower()
        self.assertIn("base", conflict)
        self.assertIn("ours", conflict)
        self.assertIn("theirs", conflict)
        self.assertIn("allowlist", conflict)
        self.assertIn("abort", conflict)
        self.assertIn("generated", conflict)

        diagnose = (ROOT / "references" / "entry" / "diagnose-failure.md").read_text(encoding="utf-8").lower()
        reproduce = (ROOT / "references" / "diagnosis" / "evidence-and-hypothesis.md").read_text(encoding="utf-8").lower()
        hypothesis = reproduce
        transition = reproduce
        debugger = reproduce
        self.assertIn("implementation remains blocked", diagnose)
        self.assertIn("original reproduction", reproduce)
        self.assertIn("time/attempt budget", reproduce)
        self.assertIn("rank a small set", hypothesis)
        self.assertIn("one factor at a time", hypothesis)
        self.assertIn("existing patch", transition)
        self.assertIn("predicted causal boundary", transition)
        self.assertIn("task-owned", debugger)

        red = (ROOT / "references" / "test" / "behavior-cycle.md").read_text(encoding="utf-8").lower()
        green = red
        oracle = (ROOT / "references" / "test" / "oracle-and-lifecycle.md").read_text(encoding="utf-8").lower()
        self.assertIn("independent", red)
        self.assertIn("plausible wrong implementation", red)
        self.assertIn("vertical slice", red)
        self.assertIn("smallest general implementation", green)
        self.assertIn("production helper", oracle)

        delegation_root = ROOT / "references" / "delegation"
        admission = (delegation_root / "admission-and-contract.md").read_text(encoding="utf-8").lower()
        worker = admission
        fan_in = (delegation_root / "fan-in-and-integration.md").read_text(encoding="utf-8").lower()
        self.assertIn("reliability, latency, and separation value", admission)
        self.assertIn("overlapping writes/resources", admission)
        self.assertIn("self-approving", worker)
        self.assertIn("worker summaries and reported tests are evidence proposals", fan_in)
        self.assertIn("return control to router", fan_in)

        api = (ROOT / "references" / "domain" / "api" / "contract-and-migration.md").read_text(encoding="utf-8").lower()
        self.assertIn("expand", api)
        self.assertIn("migrate", api)
        self.assertIn("contract", api)
        self.assertIn("old readers", api)

        prototype = (ROOT / "references" / "workspace" / "prototype-lifecycle.md").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn("one decision question", prototype)
        self.assertIn("falsifiable", prototype)
        self.assertIn("expiry/disposition", prototype)
        self.assertIn("production readiness", prototype)

        review = (ROOT / "references" / "review" / "execution-and-requirements.md").read_text(encoding="utf-8").lower()
        prompt = (
            ROOT
            / "templates"
            / "requesting-code-review"
            / "independent-reviewer-prompt.md"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("requirement→implementation→proof matrix", review)
        self.assertIn("no reviewer traverses siblings", review)
        self.assertIn("reviewer/fixer separation is mandatory", review)
        self.assertIn("requirements traceability", prompt)
        self.assertIn("do not invent requirements", prompt)

    def test_design_discovery_absorption_contracts(self) -> None:
        owner_path = "references/entry/intent-discovery.md"
        manifest = json.loads((ROOT / "registries" / "reference-cards.manifest.json").read_text(encoding="utf-8"))
        self.assertIn(owner_path, {item["path"] for item in manifest["cards"]})
        self.assertIn("materially underdefined intent requires one focused decision", (ROOT / "SKILL.md").read_text(encoding="utf-8").lower())

        owner = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8").lower()
            for relative in (
                owner_path,
                "references/intent/discovery-and-freeze.md",
            )
        )
        for phrase in (
            "one material question at a time",
            "materially different outcomes",
            "project convention",
            "decompose if one plan",
            "required external approval",
            "visual probe is allowed only",
            "authoritative spec",
        ):
            self.assertIn(phrase, owner)

        visual = (ROOT / "operator" / "design-discovery" / "visual-runtime.md").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn("startup match: server-started", visual)
        self.assertNotIn("terminal(background=true", visual)
        self.assertIn("process", visual)
        self.assertNotIn("claude code", visual)
        self.assertNotIn("gemini cli", visual)

        template = ROOT / "templates" / "design-discovery-spec-reviewer-prompt.md"
        self.assertTrue(template.is_file())
        for relative in (
            "operator/design-discovery/frame-template.html",
            "operator/design-discovery/helper.js",
            "operator/design-discovery/server.cjs",
            "operator/design-discovery/start-server.sh",
            "operator/design-discovery/stop-server.sh",
            "operator/design-discovery/design-discovery-upstream-license.txt",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

        start_script = (
            ROOT / "operator" / "design-discovery" / "start-server.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(".agent-design-discovery", start_script)
        self.assertNotIn(".hermes-design-discovery", start_script)
        self.assertNotIn("CODEX_CI", start_script)
        self.assertNotIn(".superpowers", start_script)

    def test_primary_development_entry_contract(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        skill_lower = skill.lower()

        self.assertIn("routine low-risk same-session edits use the direct path", skill_lower)
        self.assertIn("## safety kernel", skill_lower)
        self.assertNotIn("default umbrella for all software development work", skill_lower)
        self.assertNotIn("all software development tasks enter through this skill", skill_lower)
        for mode in ("m0 direct", "m1 trace", "m2 sparse", "m3 full"):
            self.assertIn(mode, skill_lower)
        self.assertIn(
            "](references/test/behavior-cycle.md)",
            skill,
        )
        self.assertNotIn("external tdd skill", skill_lower)
        self.assertIn("## Owner contract", skill)
        self.assertIn("Codex and Hermes Agent", skill)
        self.assertIn("Resolve paths from this skill root", skill)
        agent_metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: true", agent_metadata)
        self.assertIn("default_prompt:", agent_metadata)
        self.assertIn("$software-quality-workflows", agent_metadata)
        self.assertNotIn("remote_writes_default", agent_metadata)
        self.assertIn("Optional host features are not prerequisites", skill)
        self.assertIn("live agents, remote/destructive work, release, and publication require explicit authority", skill)
        for retired_host_detail in ("skill_view", "delegate_task", "runtime/session-dependent", "status=dispatched"):
            self.assertNotIn(retired_host_detail, skill_lower)

        shared_references = {
            "references/delegation/admission-and-contract.md": ("delegate_task", "hermes-swarm-coordination"),
            "operator/delegation/shared-ledger-runtime.md": ("delegate_task", "skill_view(", "skill_manage"),
            "operator/design-discovery/visual-runtime.md": ("Start under Hermes", "terminal(", "process(action=", "browser_navigate", "write_file", "read_file", ".hermes-design-discovery"),
        }
        for relative, markers in shared_references.items():
            text = (ROOT / relative).read_text(encoding="utf-8")
            for marker in markers:
                self.assertNotIn(marker, text, f"{relative} contains host-specific default {marker!r}")

    def test_decision_fixture_validator_is_total_for_malformed_json(self) -> None:
        malformed = [
            {
                "id": [],
                "prompt": 7,
                "mode": [],
                "max_risk": {},
                "required_gates": [["focused"]],
                "forbidden_actions": ["", ""],
            }
        ]
        errors = validator.validate_decision_cases(malformed)
        self.assertGreaterEqual(len(errors), 6)

    def test_synthetic_clean_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_minimal_skill(root)
            self.assertEqual([], validator.validate_skill(root))

    def test_generated_manifest_does_not_require_card_catalog_in_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skill"
            shutil.copytree(ROOT, root)
            violations = validator.validate_skill(root)
            self.assertEqual([], violations, validator.compact_violations(violations))

    def test_synthetic_tree_rejects_orphan_and_missing_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_minimal_skill(root)
            (root / "references" / "orphan.md").write_text("# Orphan\n", encoding="utf-8")
            (root / "references" / "synthetic-core.md").unlink()
            codes = {item.code for item in validator.validate_skill(root)}
            self.assertIn("active.orphan", codes)
            self.assertIn("active.missing", codes)

    def test_synthetic_tree_resolves_links_from_the_containing_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_minimal_skill(root)
            path = root / "references" / "synthetic-core.md"
            path.write_text(
                "# Debugging\n\n[broken sibling](references/authority-and-scope.md)\n",
                encoding="utf-8",
            )
            violations = validator.validate_skill(root)
            self.assertTrue(
                any(item.code == "link.missing" and item.path == "references/synthetic-core.md" for item in violations),
                validator.compact_violations(violations),
            )

    def test_synthetic_tree_rejects_masked_gate_and_foreign_host_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_minimal_skill(root)
            path = root / "references" / "synthetic-core.md"
            path.write_text(
                "# Debugging\n\nUse $software-quality-workflows.\n\ntest command | tail\n",
                encoding="utf-8",
            )
            codes = {item.code for item in validator.validate_skill(root)}
            self.assertIn("portability.stale", codes)
            self.assertIn("gate.masked-exit", codes)

    def test_synthetic_tree_accepts_capability_first_tool_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_minimal_skill(root)
            path = root / "references" / "synthetic-core.md"
            path.write_text(
                "# Debugging\n\nUse the active host's read, search, edit, command, and session-history capabilities.\n",
                encoding="utf-8",
            )
            violations = validator.validate_skill(root)
            self.assertFalse(
                any(item.code == "portability.stale" for item in violations),
                validator.compact_violations(violations),
            )

    def test_synthetic_tree_requires_complete_dual_host_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_minimal_skill(root)
            path = root / "SKILL.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace("  version: 2.0.0\n", ""),
                encoding="utf-8",
            )
            codes = {item.code for item in validator.validate_skill(root)}
            self.assertIn("entry.frontmatter", codes)

    def test_semantic_version_contract(self) -> None:
        valid_versions = (
            "0.0.0",
            "1.2.3-alpha",
            "1.2.3-alpha.1",
            "1.2.3-0.3.7",
            "1.2.3-x.7.z.92",
            "1.2.3+001",
            "1.2.3-alpha+001",
            "1.2.3-x-y-z.--",
        )
        invalid_versions = (
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "1.2.3-01",
            "1.2.3-foo..bar",
            "1.2.3+foo..bar",
            "1.2.3-",
            "1.2.3+",
            "1.2.3-alpha_beta",
            "١.2.3",
        )
        for version in valid_versions:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                make_minimal_skill(root)
                path = root / "SKILL.md"
                text = path.read_text(encoding="utf-8")
                path.write_text(
                    text.replace("  version: 2.0.0", f"  version: {version}", 1),
                    encoding="utf-8",
                )
                violations = validator.validate_skill(root)
                self.assertFalse(
                    any(item.code in {"entry.frontmatter", "entry.version"} for item in violations),
                    validator.compact_violations(violations),
                )
        for version in invalid_versions:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                make_minimal_skill(root)
                path = root / "SKILL.md"
                text = path.read_text(encoding="utf-8")
                path.write_text(
                    text.replace("  version: 2.0.0", f"  version: {version}", 1),
                    encoding="utf-8",
                )
                codes = {item.code for item in validator.validate_skill(root)}
                self.assertTrue({"entry.frontmatter", "entry.version"} & codes)

    def test_synthetic_tree_rejects_malformed_hermes_frontmatter_shapes(self) -> None:
        mutations = {
            "malformed_tags_list": (
                "tags: [development, testing, verification]",
                "tags: [development,, verification]",
            ),
            "scalar_tags": (
                "tags: [development, testing, verification]",
                "tags: development",
            ),
            "scalar_related_skills": (
                "related_skills: [writing-plans]",
                "related_skills: writing-plans",
            ),
            "non_mapping_metadata": (
                "metadata:\n  version:",
                "metadata: invalid\n  version:",
            ),
            "non_mapping_hermes": (
                "  hermes:\n    tags:",
                "  hermes: invalid\n    tags:",
            ),
            "empty_tags_list": (
                "tags: [development, testing, verification]",
                "tags: []",
            ),
            "invalid_related_skill_entry": (
                "related_skills: [writing-plans]",
                "related_skills: [writing-plans, bad entry]",
            ),
            "missing_metadata_separator_space": (
                "  version: 2.0.0",
                "  version:2.0.0",
            ),
            "malformed_hosts_list": (
                "  hosts: [codex, hermes-agent]",
                "  hosts: [codex,, hermes-agent]",
            ),
            "missing_nested_separator_space": (
                "tags: [development, testing, verification]",
                "tags:[development, testing, verification]",
            ),
            "plain_scalar_comment": (
                "  author: Hermes Agent",
                "  author: # comment",
            ),
            "plain_scalar_sequence_indicator": (
                "  author: Hermes Agent",
                "  author: - item",
            ),
            "plain_scalar_mapping_indicator": (
                "  author: Hermes Agent",
                "  author: foo:",
            ),
            "malformed_single_quoted_scalar": (
                "  author: Hermes Agent",
                "  author: 'foo'bar'",
            ),
            "implicit_boolean_scalar": (
                "  author: Hermes Agent",
                "  author: yes",
            ),
            "implicit_boolean_list_entry": (
                "tags: [development, testing, verification]",
                "tags: [development, true]",
            ),
            "numeric_list_entry": (
                "tags: [development, testing, verification]",
                "tags: [development, 123]",
            ),
        }
        for name, (old, new) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                make_minimal_skill(root)
                path = root / "SKILL.md"
                text = path.read_text(encoding="utf-8")
                self.assertIn(old, text)
                path.write_text(text.replace(old, new, 1), encoding="utf-8")
                codes = {item.code for item in validator.validate_skill(root)}
                self.assertIn("entry.frontmatter", codes)

    def test_synthetic_tree_accepts_bounded_openai_metadata_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_minimal_skill(root)
            path = root / "agents" / "openai.yaml"
            path.parent.mkdir()
            path.write_text(
                "interface:\n"
                "  display_name: Fixture\n"
                "  short_description: Synthetic agent metadata\n"
                "  default_prompt: Use $software-quality-workflows for this fixture.\n"
                "policy:\n"
                "  allow_implicit_invocation: true\n"
                "  remote_writes_default: false\n",
                encoding="utf-8",
            )
            self.assertEqual([], validator.validate_skill(root))

    def test_active_tree_rejects_legacy_recipe_aggregator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skill"
            shutil.copytree(ROOT, root)
            path = root / "references" / "version-sensitive-recipes.md"
            path.write_text("# Retired recipe aggregator\n", encoding="utf-8")
            codes = {item.code for item in validator.validate_skill(root)}
            self.assertIn("recipe.compatibility", codes)

    def test_review_result_accepts_valid_envelope(self) -> None:
        errors = validator.validate_review_result(valid_result(), **valid_context())
        self.assertEqual([], errors)

    def test_review_result_accepts_explicitly_bounded_sampled_local_verdict(self) -> None:
        result = valid_result()
        result["coverage"][0]["status"] = "sampled"
        result["coverage"][0]["sampling_note"] = "Reviewed the changed branch and its owning caller."
        self.assertEqual([], validator.validate_review_result(result, **valid_context()))
        del result["coverage"][0]["sampling_note"]
        self.assertIn(
            "coverage[0].sampling_note is required for sampled coverage",
            validator.validate_review_result(result, **valid_context()),
        )

    def test_scope_manifest_validator_is_total_for_malformed_json(self) -> None:
        errors, context = validator.validate_scope_manifest(
            {
                "base_revision": [],
                "head_revision": {},
                "scope_hash": 3,
                "paths": [
                    {"path": [], "status": [], "snapshot_id": {}},
                    {"path": "dup", "status": "modified", "snapshot_id": "one"},
                    {"path": "dup", "status": "modified", "snapshot_id": "two"},
                ],
            }
        )
        self.assertIsNotNone(context)
        self.assertGreaterEqual(len(errors), 7)

    def test_review_result_rejects_version_1_without_silent_upgrade(self) -> None:
        result = valid_result()
        result["schema_version"] = "2.0"
        errors = validator.validate_review_result(result, **valid_context())
        self.assertIn(
            "schema_version must be '3.0'; earlier results require re-review",
            errors,
        )

        historical_shape = valid_result()
        historical_shape["schema_version"] = "1.0"
        historical_shape.pop("reviewed_scope_hash")
        historical_shape.pop("spec_traceability")
        for item in historical_shape["coverage"]:
            item.pop("snapshot_id")
        historical_errors = validator.validate_review_result(
            historical_shape, **valid_context()
        )
        self.assertIn(
            "pre-3.0 results require re-review against a frozen manifest",
            historical_errors,
        )

    def test_review_result_rejects_blocking_pass(self) -> None:
        result = valid_result()
        result["findings"][0]["blocking"] = True
        errors = validator.validate_review_result(result, **valid_context())
        self.assertIn("blocking finding conflicts with code_review_verdict=pass", errors)

    def test_review_result_separates_local_verdict_from_publication_fields(self) -> None:
        result = valid_result()
        result["coverage"][0]["status"] = "not_reviewed"
        result["verification_status"] = "partial"
        result["merge_readiness"] = "ready"
        result["external_approvals"] = "missing"
        errors = validator.validate_review_result(result, **valid_context())
        self.assertIn("not_reviewed coverage conflicts with code_review_verdict=pass", errors)
        self.assertIn("unexpected result fields: ['external_approvals', 'merge_readiness']", errors)

    def test_review_result_rejects_stale_revision_and_out_of_scope_finding(self) -> None:
        manifest = valid_manifest()
        manifest["paths"][0]["path"] = "src/other.py"
        errors = validator.validate_review_result(
            valid_result(),
            scope_manifest=manifest,
            current_head="head-3",
            current_scope_hash="scope-hash-2",
        )
        self.assertIn("review result is stale for the current head revision", errors)
        self.assertIn("findings[0].path is outside the scope allowlist", errors)

    def test_review_result_rejects_blocking_local_pass_without_claiming_readiness(self) -> None:
        result = valid_result()
        result["code_review_verdict"] = "changes_requested"
        result["coverage"] = []
        result["blocking_reasons"] = ["unresolved required decision"]
        errors = validator.validate_review_result(result, **valid_context())
        self.assertIn("coverage is missing allowlisted paths: ['src/core.py']", errors)
        self.assertNotIn("merge_readiness", "\n".join(errors))

    def test_review_result_is_total_and_rejects_malformed_fields(self) -> None:
        result = valid_result()
        result["code_review_verdict"] = []
        result["reviewed_head_sha"] = 7
        result["coverage"][0] = {"path": 9, "status": [], "snapshot_id": []}
        result["blocking_reasons"] = [3, ""]
        result["findings"][0].update(
            {
                "id": 4,
                "category": "",
                "line": True,
                "evidence": 5,
                "impact": None,
                "recommended_fix": [],
                "verification": {},
                "source_revision": 7,
            }
        )
        errors = validator.validate_review_result(result, **valid_context())
        expected_fragments = {
            "code_review_verdict must be one of",
            "reviewed_head_sha must be a non-empty string",
            "coverage[0].path must be a non-empty string",
            "coverage[0].status must be one of",
            "coverage[0].snapshot_id must be a non-empty string",
            "blocking_reasons[0] must be a non-empty string",
            "findings[0].id must be a non-empty string",
            "findings[0].category must be a non-empty string",
            "findings[0].line must be null or a positive integer",
            "findings[0].evidence must be a non-empty string",
            "findings[0].impact must be a non-empty string",
            "findings[0].recommended_fix must be a non-empty string",
            "findings[0].verification must be a non-empty string",
        }
        for fragment in expected_fragments:
            self.assertTrue(any(fragment in error for error in errors), (fragment, errors))

    def test_review_result_enforces_coverage_manifest_and_uniqueness(self) -> None:
        result = valid_result()
        result["coverage"] = [
            {"path": "src/core.py", "status": "full", "snapshot_id": "sha256:core-2"},
            {"path": "src/core.py", "status": "full", "snapshot_id": "sha256:core-2"},
            {"path": "src/outside.py", "status": "sampled", "snapshot_id": "sha256:outside"},
        ]
        manifest = valid_manifest()
        manifest["paths"].append(
            {"path": "docs/old.md", "status": "deleted", "snapshot_id": "sha256:old-base"}
        )
        errors = validator.validate_review_result(
            result,
            scope_manifest=manifest,
            current_head="head-2",
            current_scope_hash="scope-hash-2",
        )
        self.assertIn("duplicate coverage paths: ['src/core.py']", errors)
        self.assertIn("coverage[2].path is outside the scope allowlist", errors)
        self.assertIn("coverage is missing allowlisted paths: ['docs/old.md']", errors)

    def test_review_result_requires_frozen_manifest_and_freshness_context(self) -> None:
        errors = validator.validate_review_result(valid_result())
        self.assertIn("scope_manifest context is required", errors)
        self.assertIn("current_head context is required", errors)
        self.assertIn("current_scope_hash context is required", errors)

    def test_review_result_rejects_reviewer_revision_substitution_and_scope_drift(self) -> None:
        result = valid_result()
        result["reviewed_head_sha"] = "head-3"
        result["reviewed_scope_hash"] = "scope-hash-3"
        result["coverage"][0]["snapshot_id"] = "sha256:core-3"
        result["findings"][0]["source_revision"] = "head-3"
        substituted = validator.validate_review_result(
            result,
            scope_manifest=valid_manifest(),
            current_head="head-3",
            current_scope_hash="scope-hash-3",
        )
        self.assertIn("reviewed_head_sha does not match the frozen scope manifest", substituted)
        self.assertIn("reviewed_scope_hash does not match the frozen scope manifest", substituted)
        self.assertIn("coverage[0].snapshot_id does not match the frozen scope manifest", substituted)

        dirty_drift = validator.validate_review_result(
            valid_result(),
            scope_manifest=valid_manifest(),
            current_head="head-2",
            current_scope_hash="scope-hash-3",
        )
        self.assertIn("current scope hash differs from the frozen scope manifest", dirty_drift)

    def test_review_result_cli_requires_context_before_reporting_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            manifest_path = Path(directory) / "scope.json"
            path.write_text(json.dumps(valid_result()), encoding="utf-8")
            manifest_path.write_text(json.dumps(valid_manifest()), encoding="utf-8")
            missing_context = subprocess.run(
                [sys.executable, str(VALIDATOR_PATH), "--review-result", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, missing_context.returncode)
            self.assertIn("scope_manifest context is required", missing_context.stdout)
            self.assertIn("current_head context is required", missing_context.stdout)
            self.assertIn("current_scope_hash context is required", missing_context.stdout)
            self.assertNotIn("OK:", missing_context.stdout)

            complete_context = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR_PATH),
                    "--review-result",
                    str(path),
                    "--scope-manifest",
                    str(manifest_path),
                    "--current-head",
                    "head-2",
                    "--current-scope-hash",
                    "scope-hash-2",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, complete_context.returncode, complete_context.stdout)
            self.assertIn("OK: local review result satisfies schema 3.0", complete_context.stdout)

    def test_long_and_short_failures_preserve_original_return_code(self) -> None:
        for line_count in (1, 400):
            script = (
                "import sys; "
                f"[print('context line', i) for i in range({line_count})]; "
                "print('root cause', file=sys.stderr); sys.exit(7)"
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                text=True,
            )
            compact_failure = completed.stderr.strip().splitlines()[-1:]
            self.assertEqual(7, completed.returncode)
            self.assertEqual(["root cause"], compact_failure)


if __name__ == "__main__":
    unittest.main()
