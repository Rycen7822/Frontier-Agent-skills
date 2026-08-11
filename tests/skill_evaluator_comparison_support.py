from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from skill_evaluator_test_support import *  # noqa: F403


class ComparisonTestCase(SkillEvaluatorTestCase):  # noqa: F405
    def _materialize_cycle(
        self,
        root: Path,
        *,
        observations: bool,
        source_revision: str | None = None,
    ) -> dict[str, Path]:
        root.mkdir(parents=True)
        paths = materialize_epoch6_contract_fixture(root)  # noqa: F405
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        safety_estimand = copy.deepcopy(spec['analysis']['estimands'][0])
        safety_estimand.update({
            'estimand_id': 'safety-benefit',
            'metric': 'safety_pass_rate',
        })
        spec['analysis']['estimands'].append(safety_estimand)
        spec['hard_gates'].append({
            'gate_id': 'safety-gate',
            'kind': 'safety',
            'metric': 'safety_pass_rate',
            'direction': 'at_least',
            'threshold': 0.0,
            'authority': 'deterministic',
            'required': True,
        })
        scenarios = [
            json.loads(line)
            for line in paths['scenarios'].read_text(
                encoding='utf-8',
            ).splitlines()
            if line.strip()
        ]
        second = copy.deepcopy(scenarios[0])
        second['case_id'] = 'case-second'
        second['execution_context']['task'] = 'Complete the second fixture task.'
        second['turns'][0]['input']['content'] = (
            'Complete the second fixture task.'
        )
        paths['scenarios'].write_text(
            ''.join(
                json.dumps(item, separators=(',', ':')) + '\n'
                for item in (scenarios[0], second)
            ),
            encoding='utf-8',
        )
        proof = json.loads(paths['quality_proof'].read_text(encoding='utf-8'))
        proof['case_classes'] = [
            {'case_id': 'case-basic', 'class': 'positive'},
            {'case_id': 'case-second', 'class': 'boundary_or_failure'},
        ]
        proof['duplicate_groups'] = [{
            'group_id': 'shared-fixture',
            'kind': 'fixture_overlap',
            'case_ids': ['case-basic', 'case-second'],
            'status': 'allowed',
            'review_locator': None,
        }]
        proof['provenance_clusters'][0]['case_ids'] = [
            'case-basic',
            'case-second',
        ]
        paths['quality_proof'].write_text(
            json.dumps(proof, indent=2) + '\n',
            encoding='utf-8',
        )
        package_root = root / spec['subject']['package']['path']
        package_root.mkdir(parents=True, exist_ok=True)
        skill_path = package_root / 'SKILL.md'
        skill_path.write_text(
            '# Evaluated skill\n'
            + ('\nCandidate revision.\n' if source_revision else ''),
            encoding='utf-8',
        )
        package_digest = (
            'sha256:' + hashlib.sha256(skill_path.read_bytes()).hexdigest()
        )
        spec['subject']['package']['package_digest'] = package_digest
        host = json.loads(paths['host'].read_text(encoding='utf-8'))
        subject_id = spec['subject']['skill_id']
        target = next(
            item for item in host['catalog']['entries']
            if item['id'] == subject_id
        )
        target['root_digest'] = package_digest
        if source_revision is not None:
            spec['subject']['version'] = '3.3.0-test'
            spec['subject']['package']['source_revision'] = source_revision
            for grader in spec['graders']:
                if grader['type'] == 'deterministic':
                    grader['verifier']['source_revision'] = source_revision
            target['version'] = spec['subject']['version']
        paths['host'].write_text(
            json.dumps(host, indent=2) + '\n',
            encoding='utf-8',
        )
        paths['spec'].write_text(
            json.dumps(spec, indent=2) + '\n',
            encoding='utf-8',
        )
        rebind_epoch6_contract_fixture(paths)  # noqa: F405

        paths.update({
            'plan': root / 'execution-plan.json',
            'index': root / 'artifacts/index.jsonl',
            'summary': root / 'summary.json',
            'failures': root / 'failures.json',
            'observations': root / 'comparison-observations.json',
        })
        compiled = self.call_cli(
            'scripts/compile_eval_plan.py',
            str(paths['spec']),
            str(paths['scenarios']),
            str(paths['host']),
            '--output', str(paths['plan']),
        )
        self.assertEqual(
            0, compiled.returncode, compiled.stdout + compiled.stderr,
        )
        executed = self.call_cli(
            'scripts/run_eval_plan.py',
            str(paths['plan']),
            '--index', str(paths['index']),
            '--new-attempt-budget', str(runner_worst_case_attempt_budget(
                json.loads(paths['plan'].read_text(encoding='utf-8')),
            )),
        )
        self.assertEqual(
            0, executed.returncode, executed.stdout + executed.stderr,
        )
        command = [
            'scripts/analyze_runs.py',
            str(paths['index']),
            '--spec', str(paths['spec']),
            '--json', str(paths['summary']),
            '--failure-index', str(paths['failures']),
        ]
        if observations:
            command.extend((
                '--comparison-observations',
                str(paths['observations']),
            ))
        analyzed = self.call_cli(*command)
        self.assertIn(
            analyzed.returncode,
            {0, 1, 3},
            analyzed.stdout + analyzed.stderr,
        )
        return paths

    def _rebind_cycle_host(
        self,
        paths: dict[str, Path],
        execution_updates: dict[str, str],
    ) -> None:
        """Rebind closed synthetic evidence to a model-only host identity."""
        compiler = load_compiler_module()  # noqa: F405

        host = json.loads(paths['host'].read_text(encoding='utf-8'))
        host['identity']['execution'].update(execution_updates)
        paths['host'].write_text(
            json.dumps(host, indent=2) + '\n', encoding='utf-8',
        )

        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        plan = json.loads(paths['plan'].read_text(encoding='utf-8'))
        plan['execution_profile'] = compiler._execution_profile(spec, host)
        paths['plan'].write_text(
            json.dumps(plan, indent=2) + '\n', encoding='utf-8',
        )

    def _rebind_cycle_judge(
        self,
        paths: dict[str, Path],
        grader_revision: str,
    ) -> None:
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        grader = spec['graders'][0]
        grader['grader_id'] = f"grader.changed.{grader_revision}"
        paths['spec'].write_text(
            json.dumps(spec, indent=2) + '\n', encoding='utf-8',
        )
        plan = json.loads(paths['plan'].read_text(encoding='utf-8'))
        for entry in plan['entries']:
            entry['grader_ids'] = [grader['grader_id']]
        paths['plan'].write_text(
            json.dumps(plan, indent=2) + '\n', encoding='utf-8',
        )

    def _cycle_binding(
        self,
        comparison_root: Path,
        paths: dict[str, Path],
        *,
        observations: bool,
    ) -> dict:
        evidence = load_evidence_io_module()  # noqa: F405
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        plan = json.loads(paths['plan'].read_text(encoding='utf-8'))

        def artifact(name: str, schema: str) -> dict:
            path = paths[name]
            return {
                'path': path.name,
                'schema': schema,
                'digest': evidence.file_sha256(path),
            }

        cycle_id = f"{spec['evaluation_id']}.{paths['spec'].parent.name}"
        if observations:
            observation_document = json.loads(
                paths['observations'].read_text(encoding='utf-8'),
            )
            observation_document['cycle_id'] = cycle_id
            paths['observations'].write_bytes(
                evidence.canonical_json_bytes(observation_document),
            )
        capsule = {
            'schema_version': 'comparison-cycle-capsule/2',
            'cycle_id': cycle_id,
            'evaluation_id': spec['evaluation_id'],
            'plan_id': plan['plan_id'],
            'execution_profile': plan['execution_profile'],
            'artifacts': {
                'spec': artifact('spec', 'eval-spec-v6'),
                'execution_plan': artifact('plan', 'execution-plan-v2'),
                'host_manifest': artifact('host', 'host-manifest-v2'),
                'summary': artifact('summary', 'analysis-summary-v5'),
                'failure_index': artifact('failures', 'failure-index-v2'),
                'observations': (
                    artifact('observations', 'comparison-observations-v2')
                    if observations else None
                ),
            },
        }
        capsule_path = paths['spec'].parent / 'cycle-capsule.json'
        capsule_path.write_bytes(evidence.canonical_json_bytes(capsule))
        paths['capsule'] = capsule_path

        return {
            'cycle_id': cycle_id,
            'expected_identity': {
                'evaluation_id': spec['evaluation_id'],
                'plan_id': plan['plan_id'],
                'execution_profile': plan['execution_profile'],
            },
            'capsule': {
                'path': capsule_path.relative_to(comparison_root).as_posix(),
                'schema': 'comparison-cycle-capsule/2',
                'digest': evidence.file_sha256(capsule_path),
            },
        }

    def _write_plan(
        self,
        root: Path,
        *,
        kind: str,
        bindings: dict,
        output_root: str = 'comparison-output',
    ) -> tuple[Path, dict]:
        template_name = (
            'comparison-plan.revision.example.json'
            if kind == 'revision'
            else 'comparison-plan.model-transition.example.json'
        )
        template_path = (
            ROOT / 'templates' / template_name  # noqa: F405
        )
        plan = json.loads(template_path.read_text(encoding='utf-8'))
        plan['input_bindings'] = copy.deepcopy(bindings)
        plan['output']['root'] = output_root
        path = root / 'comparison-plan.json'
        path.write_text(
            json.dumps(plan, indent=2) + '\n',
            encoding='utf-8',
        )
        return path, plan

    def _rewrite_plan(
        self,
        path: Path,
        plan: dict,
    ) -> None:
        path.write_text(
            json.dumps(plan, indent=2) + '\n',
            encoding='utf-8',
        )

    def _write_document(
        self,
        path: Path,
        value: dict,
    ) -> None:
        evidence = load_evidence_io_module()  # noqa: F405
        path.write_bytes(evidence.canonical_json_bytes(value))

    def _set_failures(
        self,
        paths: dict[str, Path],
        failures: list[dict],
    ) -> None:
        evidence = load_evidence_io_module()  # noqa: F405
        index = json.loads(paths['failures'].read_text(encoding='utf-8'))
        index.update({
            'item_count': len(failures),
            'shown_count': len(failures),
            'omitted_count': 0,
            'truncated': False,
            'family_counts': {
                family: sum(item['family'] == family for item in failures)
                for family in sorted({item['family'] for item in failures})
            },
            'severity_counts': {
                severity: sum(item['severity'] == severity for item in failures)
                for severity in sorted({item['severity'] for item in failures})
            },
            'failures': failures,
        })
        self._write_document(paths['failures'], index)
        summary = json.loads(paths['summary'].read_text(encoding='utf-8'))
        failure_view = summary['output_manifest']['failure_index']
        failure_view.update({
            'item_count': index['item_count'],
            'shown_count': index['shown_count'],
            'omitted_count': 0,
            'truncated': False,
            'family_counts': index['family_counts'],
            'severity_counts': index['severity_counts'],
        })
        summary['representative_failure_ids'] = [
            item['failure_id'] for item in failures[:10]
        ]
        self._write_document(paths['summary'], summary)

    def _set_metric_evidence(
        self,
        paths: dict[str, Path],
        values: dict[str, float],
    ) -> None:
        plan = json.loads(paths['plan'].read_text(encoding='utf-8'))
        case_ids = sorted({entry['case_id'] for entry in plan['entries']})
        self.assertGreaterEqual(len(case_ids), 2)
        summary = json.loads(paths['summary'].read_text(encoding='utf-8'))
        for metric_id, value in values.items():
            metric = summary['paired_metrics'][metric_id]
            metric.update({
                'status': 'pass',
                'point': value,
                'lower': value,
                'upper': value,
                'case_count': len(case_ids),
                'excluded_pairs': 0,
                'case_differences': {
                    case_id: value for case_id in case_ids
                },
            })
        self._write_document(paths['summary'], summary)

    def _set_transition_evidence(
        self,
        paths: dict[str, Path],
        *,
        task_benefit: float,
        native_value: float,
        stage_passed: dict[str, int] | None = None,
    ) -> None:
        self._set_failures(paths, [])
        self._set_metric_evidence(paths, {
            'task-benefit': task_benefit,
            'safety-benefit': 0.5,
        })

        summary = json.loads(paths['summary'].read_text(encoding='utf-8'))
        summary.update({
            'analysis_ready': True,
            'evidence_status': 'complete',
            'feasibility_status': 'feasible',
        })
        passed = stage_passed or {}
        selected = {'retrieved', 'loaded', 'applied'}
        summary['stage_summaries'] = [
            item for item in summary['stage_summaries']
            if not (
                item['surface'] == 'skill_tool_access'
                and item['stage'] in selected
            )
        ] + [
            {
                'surface': 'skill_tool_access',
                'stage': stage,
                'eligible': 2,
                'reached': passed.get(stage, 2),
                'passed': passed.get(stage, 2),
                'status': (
                    'pass' if passed.get(stage, 2) == 2 else 'fail'
                ),
                'reason_key': 'comparison_transition_fixture',
            }
            for stage in ('retrieved', 'loaded', 'applied')
        ]
        self._write_document(paths['summary'], summary)

        plan = json.loads(paths['plan'].read_text(encoding='utf-8'))
        case_ids = sorted({
            entry['case_id'] for entry in plan['entries']
            if entry['disposition'] == 'execute'
        })
        observations = json.loads(
            paths['observations'].read_text(encoding='utf-8'),
        )
        for metric in observations['metrics']:
            if metric['metric_id'] not in {'task-benefit', 'safety-benefit'}:
                continue
            benefit = (
                task_benefit
                if metric['metric_id'] == 'task-benefit'
                else 0.5
            )
            metric.update({
                'status': 'complete',
                'reason': None,
                'repeat_count': 1,
                'values': [
                    {
                        'case_id': case_id,
                        'comparator_value': native_value,
                        'candidate_value': native_value + benefit,
                    }
                    for case_id in case_ids
                ],
            })
        self._write_document(paths['observations'], observations)

    def _revision_failure(self, paths: dict[str, Path]) -> dict:
        plan = json.loads(paths['plan'].read_text(encoding='utf-8'))
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        entry = plan['entries'][0]
        return {
            'failure_id': 'sf-' + '1' * 24,
            'family': 'treatment',
            'code': 'treatment.failed',
            'severity': 'high',
            'evidence_state': 'verified',
            'evaluation_id': spec['evaluation_id'],
            'plan_id': plan['plan_id'],
            'entry_id': entry['entry_id'],
            'case_id': 'case-basic',
            'treatment_id': 'candidate',
            'repeat': 1,
            'attempt': 1,
            'dimension': 'outcome',
            'requirement_id': 'outcome',
            'fault_id': None,
            'gate_id': None,
            'principal_id': None,
            'handoff_id': None,
            'action_id': None,
            'observation_id': None,
            'finding_id': None,
            'reason_key': 'required_outcome_failed',
            'locator': {
                'kind': 'json_pointer',
                'artifact': 'summary.json',
                'json_pointer': '/paired_metrics/task-benefit',
            },
            'occurrence_count': 1,
            'observed': 'the frozen outcome requirement failed',
            'expected': 'the frozen outcome requirement passes',
            'impact': 'the revision target remains open',
            'retest': 'compare the next closed cycle under the frozen plan',
        }

    def _bound_cycle_paths(
        self,
        root: Path,
        plan: dict,
        role: str,
    ) -> dict[str, Path]:
        binding = plan['input_bindings'][role]
        capsule_path = root / binding['capsule']['path']
        capsule = json.loads(capsule_path.read_text(encoding='utf-8'))
        capsule_root = capsule_path.parent
        paths = {
            'spec': capsule_root / capsule['artifacts']['spec']['path'],
            'plan': capsule_root / capsule['artifacts']['execution_plan']['path'],
            'host': capsule_root / capsule['artifacts']['host_manifest']['path'],
            'summary': capsule_root / capsule['artifacts']['summary']['path'],
            'failures': capsule_root / capsule['artifacts']['failure_index']['path'],
            'capsule': capsule_path,
        }
        if capsule['artifacts']['observations'] is not None:
            paths['observations'] = (
                capsule_root / capsule['artifacts']['observations']['path']
            )
        return paths

    def _refresh_cycle_binding(
        self,
        root: Path,
        plan: dict,
        role: str,
    ) -> None:
        evidence = load_evidence_io_module()  # noqa: F405
        binding = plan['input_bindings'][role]
        capsule_path = root / binding['capsule']['path']
        capsule = json.loads(capsule_path.read_text(encoding='utf-8'))
        spec_path = capsule_path.parent / capsule['artifacts']['spec']['path']
        plan_path = (
            capsule_path.parent
            / capsule['artifacts']['execution_plan']['path']
        )
        spec = json.loads(spec_path.read_text(encoding='utf-8'))
        execution_plan = json.loads(plan_path.read_text(encoding='utf-8'))
        capsule.update({
            'evaluation_id': spec['evaluation_id'],
            'plan_id': execution_plan['plan_id'],
            'execution_profile': execution_plan['execution_profile'],
        })
        for reference in capsule['artifacts'].values():
            if reference is not None:
                reference['digest'] = evidence.file_sha256(
                    capsule_path.parent / reference['path'],
                )
        capsule_path.write_bytes(evidence.canonical_json_bytes(capsule))
        binding['expected_identity'] = {
            'evaluation_id': capsule['evaluation_id'],
            'plan_id': capsule['plan_id'],
            'execution_profile': capsule['execution_profile'],
        }
        binding['capsule']['digest'] = evidence.file_sha256(capsule_path)

    def _refresh_all_cycle_bindings(
        self,
        root: Path,
        plan: dict,
    ) -> None:
        for role in plan['input_bindings']:
            self._refresh_cycle_binding(root, plan, role)

    def _assert_revision_status(
        self,
        root: Path,
        baseline: dict,
        output_root: str,
        expected: str,
    ) -> dict:
        plan = copy.deepcopy(baseline)
        self._refresh_all_cycle_bindings(root, plan)
        plan['output']['root'] = output_root
        plan_path = root / f'{output_root}.plan.json'
        self._rewrite_plan(plan_path, plan)
        result = self.call_cli('scripts/compare_cycles.py', str(plan_path))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        report_path = root / output_root / plan['output']['report']
        report = json.loads(report_path.read_text(encoding='utf-8'))
        self.assertEqual(expected, report['result']['status'], report)
        return report

    def _revision_fixture(self, root: Path) -> tuple[Path, dict]:
        candidate_revision = '9' * 40
        prior = self._materialize_cycle(
            root / 'cycles/prior',
            observations=False,
        )
        candidate = self._materialize_cycle(
            root / 'cycles/candidate',
            observations=False,
            source_revision=candidate_revision,
        )
        failure = self._revision_failure(prior)
        self._set_failures(prior, [failure])
        self._set_failures(candidate, [])
        metric_values = {'task-benefit': 1.0, 'safety-benefit': 1.0}
        self._set_metric_evidence(prior, metric_values)
        self._set_metric_evidence(candidate, metric_values)
        plan_path, plan = self._write_plan(
            root,
            kind='revision',
            bindings={
                'prior': self._cycle_binding(
                    root,
                    prior,
                    observations=False,
                ),
                'candidate': self._cycle_binding(
                    root,
                    candidate,
                    observations=False,
                ),
            },
        )
        package_root = json.loads(
            candidate['spec'].read_text(encoding='utf-8'),
        )['subject']['package']['path']
        policy = plan['decision_policy']
        policy['target'].update({
            'diagnostic_ids': [failure['failure_id']],
            'case_ids': [failure['case_id']],
            'requirement_ids': [failure['requirement_id']],
        })
        policy['change_set'].update({
            'paths': [f'{package_root}/SKILL.md'],
            'candidate_revision': candidate_revision,
        })
        policy['metric_rules'] = [
            {
                'purpose': 'target_improvement',
                'metric_id': 'task-benefit',
                'direction': 'higher_is_better',
                'margin': 0.0,
            },
            {
                'purpose': 'protected_noninferiority',
                'metric_id': 'safety-benefit',
                'direction': 'higher_is_better',
                'margin': 0.0,
            },
        ]
        policy['required_gates'] = ['safety']
        self._rewrite_plan(plan_path, plan)
        return plan_path, plan

    def _transition_fixture(
        self,
        root: Path,
        *,
        target_execution_updates: dict[str, str] | None = None,
        target_judge_revision: str | None = None,
    ) -> tuple[Path, dict]:
        reference = self._materialize_cycle(
            root / 'cycles/A',
            observations=True,
        )
        target = self._materialize_cycle(
            root / 'cycles/C',
            observations=True,
        )
        execution_updates = {
            'provider': 'target-provider',
            'model': 'target-model',
            'model_revision': 'target-revision',
        }
        execution_updates.update(target_execution_updates or {})
        self._rebind_cycle_host(target, execution_updates)
        if target_judge_revision is not None:
            self._rebind_cycle_judge(target, target_judge_revision)
        self._set_transition_evidence(
            reference,
            task_benefit=0.5,
            native_value=0.0,
        )
        self._set_transition_evidence(
            target,
            task_benefit=0.45,
            native_value=0.45,
        )
        plan_path, plan = self._write_plan(
            root,
            kind='model_transition',
            bindings={
                'A': self._cycle_binding(
                    root,
                    reference,
                    observations=True,
                ),
                'C': self._cycle_binding(
                    root,
                    target,
                    observations=True,
                ),
            },
            output_root='transition-output',
        )
        plan['decision_policy']['required_gates'] = ['safety']
        self._rewrite_plan(plan_path, plan)
        return plan_path, plan

    def _bridge_transition_fixture(
        self,
        root: Path,
        *,
        judge_change: bool = False,
    ) -> tuple[Path, dict]:
        reference = self._materialize_cycle(
            root / 'cycles/A',
            observations=True,
        )
        bridge = self._materialize_cycle(
            root / 'cycles/B',
            observations=True,
        )
        target = self._materialize_cycle(
            root / 'cycles/C',
            observations=True,
        )
        self._rebind_cycle_host(bridge, {'harness_version': '2.0.0'})
        self._rebind_cycle_host(target, {
            'harness_version': '2.0.0',
            'provider': 'target-provider',
            'model': 'target-model',
            'model_revision': 'target-revision',
        })
        if judge_change:
            grader_revision = 'v2'
            self._rebind_cycle_judge(bridge, grader_revision)
            self._rebind_cycle_judge(target, grader_revision)
        for paths, benefit, native in (
            (reference, 0.5, 0.0),
            (bridge, 0.5, 0.0),
            (target, 0.45, 0.45),
        ):
            self._set_transition_evidence(
                paths,
                task_benefit=benefit,
                native_value=native,
            )
        plan_path, plan = self._write_plan(
            root,
            kind='model_transition',
            bindings={
                role: self._cycle_binding(root, paths, observations=True)
                for role, paths in (
                    ('A', reference),
                    ('B', bridge),
                    ('C', target),
                )
            },
            output_root='transition-output',
        )
        policy = plan['decision_policy']
        policy.update({
            'mode': 'bridge',
            'required_gates': ['safety'],
            'judge_policy': (
                'bridge_required_if_changed'
                if judge_change
                else 'require_same_judge'
            ),
            'apparatus_change_fields': ['host_version', 'harness_version'],
        })
        self._rewrite_plan(plan_path, plan)
        return plan_path, plan
