from __future__ import annotations

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedReceipts(SkillEvaluatorTestCase):  # noqa: F405
    def test_analyzer_cli_accepts_bound_receipt_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            result = self.run_cmd(
                'scripts/analyze_runs.py', str(bundle['index']),
                '--spec', str(bundle['spec']), '--json', str(bundle['summary']),
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_analyzer_cli_rejects_old_receipt_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            receipt['schema_version'] = 2
            rewrite_bound_receipt(bundle, receipt)
            result = self.run_cmd(
                'scripts/analyze_runs.py', str(bundle['index']),
                '--spec', str(bundle['spec']), '--json', str(bundle['summary']),
            )
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn('receipt schema_version must equal 3', result.stdout)

    def test_receipt_and_report_v3_bind_capture_routing_boundaries_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            self.assertEqual(receipt['schema_version'], 3)
            self.assertTrue(load_analyzer_module().verify_self_hash(receipt, 'receipt_hash'))
            self.assertEqual(
                receipt['trace']['context_capture'],
                {'status': 'captured', 'source': 'replay_manifest'},
            )
            self.assertEqual(receipt['counts']['host_injected_body_count'], 1)
            self.assertEqual(receipt['counts']['model_initiated_body_read_count'], 0)
            self.assertEqual(receipt['boundaries']['first_successful_source_write_seq'], None)
            self.assertEqual(receipt['boundaries']['first_deliverable_seq'], 5)
            self.assertEqual(
                set(receipt['routing']),
                {'retrieved', 'selected', 'body_loaded', 'incorporated', 'applied', 'resources_loaded'},
            )

            report = self.assert_valid_receipt_bundle(bundle)
            self.assertEqual(report['schema_version'], 3)
            self.assertTrue(load_analyzer_module().verify_self_hash(report, 'report_hash'))
            for field in (
                'candidate_revision', 'candidate_source_tree_hash', 'candidate_plugin_tree_hash',
                'spec_content_hash', 'cases_content_hash', 'case_contracts_content_hash',
                'fixture_manifest_set_hash', 'grader_set_hash', 'grader_batch_schedule_hash',
                'treatment_hash', 'environment_hash', 'receipt_index_content_hash',
            ):
                self.assertIn(field, report)


    def test_receipt_v3_separates_host_injection_model_reread_and_routing_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            missing_host = write_receipt_bundle(root / 'missing-host')
            receipt = json.loads(missing_host['receipt'].read_text(encoding='utf-8'))
            receipt['counts']['host_injected_body_count'] = 0
            receipt['counts']['model_initiated_body_read_count'] = 1
            rewrite_bound_receipt(missing_host, receipt)
            result = self.run_receipt_analysis(missing_host)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('requires exactly one host body injection', result.stdout)

            duplicate_host = write_receipt_bundle(root / 'duplicate-host')
            add_context_component(
                duplicate_host, artifact_name='body-reread.txt', append=True,
                content=(duplicate_host['artifact_dir'] / 'context/body.txt').read_text(encoding='utf-8'),
            )
            receipt = json.loads(duplicate_host['receipt'].read_text(encoding='utf-8'))
            receipt['counts']['host_injected_body_count'] = 2
            receipt['counts']['model_initiated_body_read_count'] = 0
            rewrite_bound_receipt(duplicate_host, receipt)
            result = self.run_receipt_analysis(duplicate_host)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('requires exactly one host body injection', result.stdout)

            model_reread = write_receipt_bundle(root / 'model-reread')
            add_context_component(
                model_reread, artifact_name='body-reread.txt', append=True,
                content=(model_reread['artifact_dir'] / 'context/body.txt').read_text(encoding='utf-8'),
            )
            report = self.assert_valid_receipt_bundle(model_reread)
            self.assertEqual(report['evidence_status'], 'complete')
            self.assertEqual(report['run_matrix'][0]['counts']['model_initiated_body_read_count'], 1)
            self.assertGreater(report['run_matrix'][0]['bytes']['repeated_static_content_bytes'], 0)

            not_inferred = write_receipt_bundle(root / 'not-inferred')
            receipt = json.loads(not_inferred['receipt'].read_text(encoding='utf-8'))
            for stage in ('incorporated', 'applied'):
                receipt['routing'][stage] = {
                    'status': 'not_evaluable', 'value': None, 'evidence': [],
                }
            rewrite_bound_receipt(not_inferred, receipt)
            record = self.assert_valid_receipt_bundle(not_inferred)['run_matrix'][0]
            self.assertIsNone(record['skill_incorporated'])
            self.assertIsNone(record['skill_applied'])


    def test_receipt_v3_rejects_self_hash_identity_and_boundary_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            legacy = write_receipt_bundle(root / 'legacy-version')
            receipt = json.loads(legacy['receipt'].read_text(encoding='utf-8'))
            receipt['schema_version'] = 2
            rewrite_bound_receipt(legacy, receipt)
            result = self.run_receipt_analysis(legacy)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('receipt schema_version must equal 3', result.stdout)
            failure_report = json.loads(legacy['summary'].read_text(encoding='utf-8'))
            self.assertEqual((3, 'invalid'), (
                failure_report['schema_version'], failure_report['evidence_status'],
            ))
            self.assertTrue(load_analyzer_module().verify_self_hash(failure_report, 'report_hash'))

            self_hash = write_receipt_bundle(root / 'self-hash')
            receipt = json.loads(self_hash['receipt'].read_text(encoding='utf-8'))
            receipt['counts']['workflow_artifact_count'] = 1
            self_hash['receipt'].write_text(json.dumps(receipt) + '\n', encoding='utf-8')
            index = json.loads(self_hash['index'].read_text(encoding='utf-8'))
            index['receipt']['sha256'] = 'sha256:' + hashlib.sha256(
                self_hash['receipt'].read_bytes()
            ).hexdigest()
            self_hash['index'].write_text(json.dumps(index) + '\n', encoding='utf-8')
            result = self.run_receipt_analysis(self_hash)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('receipt self-hash mismatch', result.stdout)

            identity = write_receipt_bundle(root / 'identity')
            receipt = json.loads(identity['receipt'].read_text(encoding='utf-8'))
            receipt['run']['provenance']['candidate_source_tree_hash'] = 'sha256:' + '0' * 64
            rewrite_bound_receipt(identity, receipt)
            result = self.run_receipt_analysis(identity)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('candidate_source_tree_hash mismatch', result.stdout)

            boundary = write_receipt_bundle(root / 'boundary')
            receipt = json.loads(boundary['receipt'].read_text(encoding='utf-8'))
            receipt['boundaries']['first_deliverable_seq'] = 4
            rewrite_bound_receipt(boundary, receipt)
            result = self.run_receipt_analysis(boundary)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('first_deliverable_seq does not match ordered trace', result.stdout)


    def test_missing_or_tampered_receipt_and_artifact_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = write_receipt_bundle(root / 'valid')
            self.assert_valid_receipt_bundle(bundle)

            missing = write_receipt_bundle(root / 'missing')
            missing['receipt'].unlink()
            result = self.run_receipt_analysis(missing)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('evidence_status=incomplete', result.stdout)

            ambiguous = write_receipt_bundle(root / 'ambiguous-identity')
            spec = json.loads(ambiguous['spec'].read_text(encoding='utf-8'))
            second_candidate = copy.deepcopy(spec['variants'][0])
            second_candidate.update({
                'id': 'candidate_forced_2',
                'treatment_hash': 'sha256:' + 'e' * 64,
            })
            spec['variants'].append(second_candidate)
            ambiguous['spec'].write_text(json.dumps(spec), encoding='utf-8')
            ambiguous['receipt'].unlink()
            result = self.run_receipt_analysis(ambiguous)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('evidence_status=invalid', result.stdout)
            self.assertIn('candidate variants do not bind one treatment_hash', result.stdout)

            tampered = write_receipt_bundle(root / 'tampered')
            tampered['receipt'].write_text('{}\n', encoding='utf-8')
            result = self.run_receipt_analysis(tampered)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('receipt sha256 mismatch', result.stdout)

            artifact = write_receipt_bundle(root / 'artifact')
            (artifact['artifact_dir'] / 'trace.jsonl').write_text('{"event":"tampered"}\n', encoding='utf-8')
            result = self.run_receipt_analysis(artifact)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('artifact sha256 mismatch', result.stdout)


    def test_receipt_rejects_path_symlink_identity_and_bad_line_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            escaped = write_receipt_bundle(root / 'path')
            index = json.loads(escaped['index'].read_text(encoding='utf-8'))
            index['receipt']['path'] = '../receipt.json'
            escaped['index'].write_text(json.dumps(index) + '\n', encoding='utf-8')
            result = self.run_receipt_analysis(escaped)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('receipt path', result.stdout)

            symlinked = write_receipt_bundle(root / 'symlink')
            outside = root / 'outside.txt'
            outside.write_text('outside\n', encoding='utf-8')
            alias = symlinked['artifact_dir'] / 'escape.txt'
            alias.symlink_to(outside)
            receipt = json.loads(symlinked['receipt'].read_text(encoding='utf-8'))
            alias_hash = 'sha256:' + hashlib.sha256(outside.read_bytes()).hexdigest()
            receipt['artifacts'].append({'path': 'escape.txt', 'sha256': alias_hash, 'encoding': 'utf-8'})
            receipt['grader_outputs'][0]['invocation']['input_artifacts'].append({'path': 'escape.txt', 'sha256': alias_hash})
            rewrite_bound_receipt(symlinked, receipt)
            result = self.run_receipt_analysis(symlinked)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('artifact path escapes', result.stdout)

            bad_span = write_receipt_bundle(root / 'span')
            receipt = json.loads(bad_span['receipt'].read_text(encoding='utf-8'))
            stdout_path = bad_span['artifact_dir'] / 'verifier/stdout.json'
            stdout = json.loads(stdout_path.read_text(encoding='utf-8'))
            stdout['checks'][0]['evidence'][0]['locator']['end_line'] = 6
            stdout_path.write_text(json.dumps(stdout) + '\n', encoding='utf-8')
            stdout_hash = 'sha256:' + hashlib.sha256(stdout_path.read_bytes()).hexdigest()
            next(item for item in receipt['artifacts'] if item['path'] == 'verifier/stdout.json')['sha256'] = stdout_hash
            rewrite_bound_receipt(bad_span, receipt)
            result = self.run_receipt_analysis(bad_span)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('line locator is outside artifact bounds', result.stdout)


    def test_receipt_and_fixture_manifest_reject_duplicate_normalized_or_resolved_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = write_receipt_bundle(root / 'normalized')
            receipt = json.loads(normalized['receipt'].read_text(encoding='utf-8'))
            trace = next(item for item in receipt['artifacts'] if item['path'] == 'trace.jsonl')
            receipt['artifacts'].append({**trace, 'path': './trace.jsonl'})
            rewrite_bound_receipt(normalized, receipt)
            result = self.run_receipt_analysis(normalized)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('duplicate normalized artifact path', result.stdout)

            resolved = write_receipt_bundle(root / 'resolved')
            (resolved['artifact_dir'] / 'alias.jsonl').symlink_to('trace.jsonl')
            receipt = json.loads(resolved['receipt'].read_text(encoding='utf-8'))
            trace = next(item for item in receipt['artifacts'] if item['path'] == 'trace.jsonl')
            receipt['artifacts'].append({**trace, 'path': 'alias.jsonl'})
            rewrite_bound_receipt(resolved, receipt)
            result = self.run_receipt_analysis(resolved)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('duplicate resolved artifact path', result.stdout)

            fixture = write_receipt_bundle(root / 'fixture')
            case = json.loads(fixture['cases'].read_text(encoding='utf-8').strip())
            manifest_path = fixture['spec'].parent / 'artifacts' / case['fixture']['manifest']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['artifacts'].append({**manifest['artifacts'][0], 'path': './' + manifest['artifacts'][0]['path']})
            manifest_path.write_text(json.dumps(manifest) + '\n', encoding='utf-8')
            case['fixture']['sha256'] = 'sha256:' + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            fixture['cases'].write_text(json.dumps(case) + '\n', encoding='utf-8')
            receipt = json.loads(fixture['receipt'].read_text(encoding='utf-8'))
            receipt['run']['provenance']['fixture_hash'] = case['fixture']['sha256']
            receipt['run']['provenance']['case_sha256'] = 'sha256:' + hashlib.sha256(
                json.dumps(case, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
            ).hexdigest()
            rewrite_bound_receipt(fixture, receipt)
            result = self.run_receipt_analysis(fixture)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('fixture duplicate normalized artifact path', result.stdout)


    def test_candidate_package_and_fixture_bytes_are_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = write_receipt_bundle(root / 'package')
            spec = json.loads(package['spec'].read_text(encoding='utf-8'))
            candidate = Path(spec['target']['candidate_path']) / 'SKILL.md'
            candidate.write_text(candidate.read_text(encoding='utf-8') + '\nchanged\n', encoding='utf-8')
            result = self.run_receipt_analysis(package)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('candidate package inventory hash mismatch', result.stdout)

            fixture = write_receipt_bundle(root / 'fixture')
            case = json.loads(fixture['cases'].read_text(encoding='utf-8').strip())
            manifest_path = fixture['spec'].parent / 'artifacts' / case['fixture']['manifest']
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            fixture_file = manifest_path.parent / manifest['artifacts'][0]['path']
            fixture_file.write_text('tampered fixture\n', encoding='utf-8')
            result = self.run_receipt_analysis(fixture)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('fixture artifact sha256 mismatch', result.stdout)


    def test_receipt_verification_reuses_precomputed_candidate_inventory(self) -> None:
        module = load_analyzer_module()
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            spec = json.loads(bundle['spec'].read_text(encoding='utf-8'))
            case = json.loads(bundle['cases'].read_text(encoding='utf-8').strip())
            row = json.loads(bundle['index'].read_text(encoding='utf-8').strip())
            variant = spec['variants'][0]
            package_hash = module.resolve_candidate_package_hash(spec, bundle['spec'])
            shutil.rmtree(Path(spec['target']['candidate_path']))
            verification = module.verify_receipt(
                row, spec, bundle['spec'], case, variant, package_hash,
            )
        self.assertEqual(verification['status'], 'complete')


    def test_deterministic_invocation_rejects_missing_or_tampered_inputs_and_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = write_receipt_bundle(root / 'missing')
            (missing['artifact_dir'] / 'trace.jsonl').unlink()
            result = self.run_receipt_analysis(missing)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('evidence_status=incomplete', result.stdout)

            tampered = write_receipt_bundle(root / 'tampered')
            (tampered['artifact_dir'] / 'trace.jsonl').write_text('tampered\n', encoding='utf-8')
            result = self.run_receipt_analysis(tampered)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('artifact sha256 mismatch', result.stdout)

            declaration = write_receipt_bundle(root / 'declaration')
            spec = json.loads(declaration['spec'].read_text(encoding='utf-8'))
            verifier = declaration['spec'].parent / spec['graders'][0]['verifier']['path']
            verifier.write_text('raise SystemExit(1)\n', encoding='utf-8')
            result = self.run_receipt_analysis(declaration)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('deterministic verifier sha256 mismatch', result.stdout)


    def test_nonhard_outcome_deterministic_requires_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            spec = json.loads(bundle['spec'].read_text(encoding='utf-8'))
            self.assertFalse(spec['graders'][0]['hard_gate'])
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            stdout = json.loads((bundle['artifact_dir'] / 'verifier/stdout.json').read_text(encoding='utf-8'))
            receipt['grader_outputs'][0] = {'grader_id': 'focused-check', 'output': stdout}
            rewrite_bound_receipt(bundle, receipt)
            result = self.run_receipt_analysis(bundle)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('selected deterministic grader focused-check requires invocation', result.stdout)


    def test_deterministic_invocation_rejects_exit_pass_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            receipt['grader_outputs'][0]['invocation']['exit_code'] = 1
            rewrite_bound_receipt(bundle, receipt)
            result = self.run_receipt_analysis(bundle)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('exit_code/pass result contradiction', result.stdout)


    def test_deterministic_invocation_stdout_is_single_check_and_score_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            duplicate = write_receipt_bundle(root / 'duplicate')
            receipt = json.loads(duplicate['receipt'].read_text(encoding='utf-8'))
            stdout_path = duplicate['artifact_dir'] / 'verifier/stdout.json'
            stdout = json.loads(stdout_path.read_text(encoding='utf-8'))
            stdout['checks'].append(dict(stdout['checks'][0]))
            stdout_path.write_text(json.dumps(stdout) + '\n', encoding='utf-8')
            next(item for item in receipt['artifacts'] if item['path'] == 'verifier/stdout.json')['sha256'] = (
                'sha256:' + hashlib.sha256(stdout_path.read_bytes()).hexdigest()
            )
            rewrite_bound_receipt(duplicate, receipt)
            result = self.run_receipt_analysis(duplicate)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('duplicate grader check ID', result.stdout)

            score = write_receipt_bundle(root / 'score')
            receipt = json.loads(score['receipt'].read_text(encoding='utf-8'))
            stdout_path = score['artifact_dir'] / 'verifier/stdout.json'
            stdout = json.loads(stdout_path.read_text(encoding='utf-8'))
            stdout['score'] = 99
            stdout_path.write_text(json.dumps(stdout) + '\n', encoding='utf-8')
            next(item for item in receipt['artifacts'] if item['path'] == 'verifier/stdout.json')['sha256'] = (
                'sha256:' + hashlib.sha256(stdout_path.read_bytes()).hexdigest()
            )
            rewrite_bound_receipt(score, receipt)
            result = self.run_receipt_analysis(score)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('grader score mismatch', result.stdout)


    def test_deterministic_invocation_inputs_cannot_reference_grader_outputs_or_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = write_receipt_bundle(root / 'output')
            receipt = json.loads(output['receipt'].read_text(encoding='utf-8'))
            stdout = next(item for item in receipt['artifacts'] if item['path'] == 'verifier/stdout.json')
            receipt['grader_outputs'][0]['invocation']['input_artifacts'] = [
                {'path': stdout['path'], 'sha256': stdout['sha256']},
            ]
            rewrite_bound_receipt(output, receipt)
            result = self.run_receipt_analysis(output)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('input_artifacts must not reference receipt or grader outputs', result.stdout)

            receipt_ref = write_receipt_bundle(root / 'receipt')
            receipt = json.loads(receipt_ref['receipt'].read_text(encoding='utf-8'))
            index = json.loads(receipt_ref['index'].read_text(encoding='utf-8'))
            receipt['grader_outputs'][0]['invocation']['input_artifacts'] = [{
                'path': 'receipt.json',
                'sha256': index['receipt']['sha256'],
            }]
            rewrite_bound_receipt(receipt_ref, receipt)
            result = self.run_receipt_analysis(receipt_ref)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('input_artifacts must not reference receipt or grader outputs', result.stdout)


    def test_deterministic_invocation_rejects_artifact_root_or_incomplete_input_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrong_root = write_receipt_bundle(root / 'root')
            receipt = json.loads(wrong_root['receipt'].read_text(encoding='utf-8'))
            receipt['grader_outputs'][0]['invocation']['artifact_root'] = 'artifacts/wrong-root'
            rewrite_bound_receipt(wrong_root, receipt)
            result = self.run_receipt_analysis(wrong_root)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('invocation artifact_root mismatch', result.stdout)

            incomplete = write_receipt_bundle(root / 'inputs')
            receipt = json.loads(incomplete['receipt'].read_text(encoding='utf-8'))
            receipt['grader_outputs'][0]['invocation']['input_artifacts'] = []
            rewrite_bound_receipt(incomplete, receipt)
            result = self.run_receipt_analysis(incomplete)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('invocation input_artifacts do not equal the frozen input set', result.stdout)


    def test_treatment_failure_with_complete_evidence_stays_in_outcome_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            receipt['run']['error_type'] = 'model_refusal'
            stdout_path = bundle['artifact_dir'] / 'verifier/stdout.json'
            stdout = json.loads(stdout_path.read_text(encoding='utf-8'))
            stdout['overall_pass'] = False
            stdout['score'] = 0
            stdout['checks'][0]['pass'] = False
            stdout['checks'][0]['notes'] = 'The model refused the requested task.'
            stdout_path.write_text(json.dumps(stdout) + '\n', encoding='utf-8')
            next(item for item in receipt['artifacts'] if item['path'] == 'verifier/stdout.json')['sha256'] = (
                'sha256:' + hashlib.sha256(stdout_path.read_bytes()).hexdigest()
            )
            receipt['grader_outputs'][0]['invocation']['exit_code'] = 1
            rewrite_bound_receipt(bundle, receipt)
            result = self.run_receipt_analysis(bundle)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(bundle['summary'].read_text(encoding='utf-8'))
            self.assertEqual(report['evidence_status'], 'complete')
            self.assertEqual(report['variant_summaries']['candidate_forced']['valid_records'], 1)
            self.assertEqual(report['variant_summaries']['candidate_forced']['task_pass']['successes'], 0)


    def test_verified_receipt_derives_routing_usage_and_case_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            report = self.assert_valid_receipt_bundle(bundle)
            summary = report['variant_summaries']['candidate_forced']
            self.assertEqual(summary['task_pass']['successes'], 1)
            self.assertEqual(summary['numeric']['tokens_in']['mean'], 10)
            self.assertTrue(report['run_matrix'][0]['skill_body_loaded'])
            self.assertTrue(report['run_matrix'][0]['task_pass'])


    def test_rubric_semantics_reject_missing_duplicate_or_misscored_checks(self) -> None:
        analyzer = load_analyzer_module()
        requirements = [{
            'id': 'outcome', 'dimension': 'outcome', 'required': True,
            'grader_id': 'g', 'check_id': 'check-a',
        }]
        artifacts = {'trace.jsonl': ['evidence']}
        output = {
            'overall_pass': True,
            'score': 100,
            'checks': [{
                'id': 'check-a', 'pass': True,
                'evidence': [{
                    'artifact': 'trace.jsonl',
                    'locator': {'start_line': 1, 'end_line': 1},
                    'observation': 'evidence',
                }],
                'notes': 'verified', 'uncertainty': 'none',
            }],
            'missing_evidence': [],
            'grader_failure': False,
            'grader_failure_reason': None,
        }
        analyzer.validate_grader_output(output, requirements, artifacts)

        missing = json.loads(json.dumps(output))
        missing['checks'] = []
        with self.assertRaisesRegex(ValueError, 'selected check IDs'):
            analyzer.validate_grader_output(missing, requirements, artifacts)

        duplicate = json.loads(json.dumps(output))
        duplicate['checks'].append(dict(duplicate['checks'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate grader check ID'):
            analyzer.validate_grader_output(duplicate, requirements, artifacts)

        misscored = json.loads(json.dumps(output))
        misscored['score'] = 99
        with self.assertRaisesRegex(ValueError, 'grader score mismatch'):
            analyzer.validate_grader_output(misscored, requirements, artifacts)


    def test_optional_check_failure_can_preserve_required_overall_pass(self) -> None:
        analyzer = load_analyzer_module()
        requirements = [
            {'id': 'required', 'dimension': 'outcome', 'required': True, 'grader_id': 'g', 'check_id': 'required'},
            {'id': 'optional', 'dimension': 'quality', 'required': False, 'grader_id': 'g', 'check_id': 'optional'},
        ]
        evidence = lambda observation: [{
            'artifact': 'trace.jsonl',
            'locator': {'start_line': 1, 'end_line': 1},
            'observation': observation,
        }]
        output = {
            'overall_pass': True,
            'score': 50,
            'checks': [
                {'id': 'required', 'pass': True, 'evidence': evidence('pass'), 'notes': '', 'uncertainty': 'none'},
                {'id': 'optional', 'pass': False, 'evidence': evidence('fail'), 'notes': '', 'uncertainty': 'none'},
            ],
            'missing_evidence': [],
            'grader_failure': False,
            'grader_failure_reason': None,
        }
        validated = analyzer.validate_grader_output(output, requirements, {'trace.jsonl': ['evidence']})
        self.assertTrue(validated['overall_pass'])
        self.assertEqual(validated['score'], 50)


    def test_requirement_join_derives_dimension_scores_safety_counts_and_hard_ids(self) -> None:
        analyzer = load_analyzer_module()
        case = {'requirements': [
            {'id': 'outcome', 'dimension': 'outcome', 'required': True, 'grader_id': 'g', 'check_id': 'outcome'},
            {'id': 'process', 'dimension': 'process', 'required': False, 'grader_id': 'g', 'check_id': 'process'},
            {'id': 'quality', 'dimension': 'quality', 'required': False, 'grader_id': 'g', 'check_id': 'quality'},
            {
                'id': 'unsafe', 'dimension': 'safety', 'required': True,
                'severity': 'critical', 'safety_kind': 'unauthorized_action',
                'grader_id': 's', 'check_id': 'unsafe',
            },
        ]}
        graders = {'g': {'hard_gate': False}, 's': {'hard_gate': True}}
        results = {
            'g': {'checks': {'outcome': True, 'process': False, 'quality': True}},
            's': {'checks': {'unsafe': False}},
        }
        derived = analyzer.derive_run_fields(case, graders, results)
        self.assertEqual(derived, {
            'task_pass': True,
            'process_score': 0,
            'quality_score': 100,
            'safety_pass': False,
            'critical_safety_incidents': 1,
            'unauthorized_side_effects': 1,
            'hard_gate_failures': ['unsafe'],
        })


    def test_candidate_required_hard_failures_block_usefulness_and_authority(self) -> None:
        analyzer = load_analyzer_module()
        graders = {'g': {'hard_gate': True}}

        def hard_failure_state(dimension: str, required: bool) -> tuple[list[str], list[str]]:
            case = {'requirements': [
                {'id': 'outcome', 'dimension': 'outcome', 'required': True, 'grader_id': 'g', 'check_id': 'outcome'},
                {'id': dimension, 'dimension': dimension, 'required': required, 'grader_id': 'g', 'check_id': dimension},
            ]}
            derived = analyzer.derive_run_fields(
                case,
                graders,
                {'g': {'checks': {'outcome': True, dimension: False}}},
            )
            self.assertTrue(derived['task_pass'])
            _, blockers = analyzer.summarize_candidate_hard_failures(
                {'candidate': len(derived['hard_gate_failures'])}, {'candidate'},
            )
            return derived['hard_gate_failures'], blockers

        scenarios = (
            ('required-process', 'process', True, 'complete', [], ['process'], 'not_supported', 'blocked'),
            ('required-quality', 'quality', True, 'complete', [], ['quality'], 'not_supported', 'blocked'),
            ('optional-quality', 'quality', False, 'complete', [], [], 'supported', 'eligible'),
            ('external-blocker', 'quality', False, 'complete', ['unresolved evidence owner'], [], 'supported', 'blocked'),
            ('incomplete-process', 'process', True, 'incomplete', ['run matrix evidence is incomplete'], ['process'], 'inconclusive', 'blocked'),
        )
        for name, dimension, required, evidence, extra_blockers, expected_failures, expected_usefulness, expected_authority in scenarios:
            with self.subTest(name=name):
                hard_failures, candidate_blockers = hard_failure_state(dimension, required)
                blockers = [*candidate_blockers, *extra_blockers]
                usefulness = analyzer.derive_usefulness_status(
                    level='L2', evidence_status=evidence, primary_benefit_status='pass',
                    guardrail_statuses=['pass'], protected_outcome_failures=0,
                    material_harm=False, candidate_hard_failures=len(hard_failures),
                )
                authority = analyzer.derive_final_authority_status(
                    usefulness_status=usefulness,
                    manual_gate_passed=True,
                    candidate_hard_failures=len(hard_failures),
                    blocking_observations=blockers,
                )
                decision_signal = analyzer.derive_decision_signal('L2', usefulness)
                report = {
                    'evidence_status': evidence,
                    'usefulness_status': usefulness,
                    'final_authority_status': authority,
                    'decision_signal': decision_signal,
                }
                self.assertEqual(expected_failures, hard_failures)
                self.assertEqual(
                    [] if not expected_failures else ['candidate: 1 case-level hard grader failure(s)'],
                    candidate_blockers,
                )
                self.assertEqual((expected_usefulness, expected_authority), (usefulness, authority))
                self.assertEqual(
                    f'evidence_status={evidence} usefulness_status={expected_usefulness} '
                    f'final_authority_status={expected_authority} decision_signal={decision_signal}',
                    analyzer.decision_status_text(report),
                )
        self.assertEqual(
            'blocked',
            analyzer.derive_final_authority_status(
                usefulness_status='supported', manual_gate_passed=False,
                candidate_hard_failures=0, blocking_observations=[],
            ),
        )


    def test_grader_failure_invalidates_treatment_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            stdout_path = bundle['artifact_dir'] / 'verifier/stdout.json'
            stdout = {
                'overall_pass': False,
                'score': 0,
                'checks': [],
                'missing_evidence': [{'check_id': None, 'item': 'verifier unavailable'}],
                'grader_failure': True,
                'grader_failure_reason': 'verifier crashed',
            }
            stdout_path.write_text(json.dumps(stdout) + '\n', encoding='utf-8')
            next(item for item in receipt['artifacts'] if item['path'] == 'verifier/stdout.json')['sha256'] = (
                'sha256:' + hashlib.sha256(stdout_path.read_bytes()).hexdigest()
            )
            receipt['grader_outputs'][0]['invocation']['exit_code'] = 1
            rewrite_bound_receipt(bundle, receipt)
            result = self.run_receipt_analysis(bundle)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('grader failure requires run.valid=false', result.stdout)


    def test_manual_review_receipt_replaces_legacy_cli_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            review = add_manual_review_receipt(bundle)
            result = self.call_cli(
                'scripts/analyze_runs.py', str(bundle['index']), '--spec', str(bundle['spec']),
                '--manual-review-receipt', str(review['reference']), '--json', str(bundle['summary']),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(bundle['summary'].read_text(encoding='utf-8'))
            self.assertEqual(report['manual_review']['decision'], 'approve')
            self.assertEqual(report['manual_review']['reviewer_role'], 'independent-evaluator')
            self.assertRegex(report['manual_review']['receipt_sha256'], r'^sha256:[0-9a-f]{64}$')

            missing = self.call_cli(
                'scripts/analyze_runs.py', str(bundle['index']), '--spec', str(bundle['spec']),
            )
            self.assertEqual(missing.returncode, 3, missing.stdout + missing.stderr)
            self.assertIn('evidence_status=incomplete', missing.stdout)

            legacy = self.call_cli(
                'scripts/analyze_runs.py', str(bundle['index']), '--spec', str(bundle['spec']),
                '--manual-review-status', 'complete', '--manual-reviewer', 'anyone',
                '--manual-review-evidence', str(review['evidence']),
            )
            self.assertEqual(legacy.returncode, 2, legacy.stdout + legacy.stderr)

            duplicate = self.call_cli(
                'scripts/analyze_runs.py', str(bundle['index']), '--spec', str(bundle['spec']),
                '--manual-review-receipt', str(review['reference']),
                '--manual-review-receipt', str(review['reference']),
            )
            self.assertEqual(duplicate.returncode, 2, duplicate.stdout + duplicate.stderr)


    def test_manual_review_receipt_rejects_role_evidence_decision_or_signature_mismatch(self) -> None:
        mutations = [
            lambda receipt: receipt.update(reviewer_role='wrong-role'),
            lambda receipt: receipt['evidence'].append({
                'type': 'extra-review', 'artifact': receipt['evidence'][0]['artifact'],
                'sha256': receipt['evidence'][0]['sha256'],
            }),
            lambda receipt: receipt.update(decision='promote'),
            lambda receipt: receipt.update(signature='   '),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as tmp:
                bundle = write_receipt_bundle(Path(tmp))
                review = add_manual_review_receipt(bundle)
                receipt = json.loads(Path(review['path']).read_text(encoding='utf-8'))
                mutate(receipt)
                Path(review['path']).write_text(json.dumps(receipt), encoding='utf-8')
                result = self.call_cli(
                    'scripts/analyze_runs.py', str(bundle['index']), '--spec', str(bundle['spec']),
                    '--manual-review-receipt', str(review['reference']),
                )
                self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                self.assertIn('evidence_status=invalid', result.stdout)

        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            add_manual_review_receipt(bundle)
            spec = json.loads(bundle['spec'].read_text(encoding='utf-8'))
            spec['manual_review']['required_evidence'] = ['artifact-review', 'artifact-review']
            bundle['spec'].write_text(json.dumps(spec), encoding='utf-8')
            validator = self.call_cli(
                'scripts/validate_eval_suite.py', str(bundle['spec']), str(bundle['cases']),
            )
            self.assertEqual(validator.returncode, 1, validator.stdout + validator.stderr)
            self.assertIn('required_evidence entries must be unique', validator.stdout)


    def test_manual_review_receipt_is_contained_hash_bound_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            review = add_manual_review_receipt(bundle)
            Path(review['evidence']).write_text('tampered\n', encoding='utf-8')
            tampered = self.call_cli(
                'scripts/analyze_runs.py', str(bundle['index']), '--spec', str(bundle['spec']),
                '--manual-review-receipt', str(review['reference']),
            )
            self.assertEqual(tampered.returncode, 3, tampered.stdout + tampered.stderr)
            self.assertIn('evidence_status=invalid', tampered.stdout)

            escaped = self.call_cli(
                'scripts/analyze_runs.py', str(bundle['index']), '--spec', str(bundle['spec']),
                '--manual-review-receipt', '../manual-review/receipt.json',
            )
            self.assertEqual(escaped.returncode, 3, escaped.stdout + escaped.stderr)
            self.assertIn('evidence_status=invalid', escaped.stdout)




    def test_context_attribution_requires_verified_component_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            artifact = add_context_component(bundle)
            report = self.assert_valid_receipt_bundle(bundle)
            context = report['run_matrix'][0]['context_usage']
            self.assertTrue(context['attributed'])
            self.assertEqual(context['bytes'], len(artifact.read_bytes()))
            self.assertEqual(context['unique_static_content_bytes'], context['bytes'])
            self.assertEqual(context['repeated_static_content_bytes'], 0)
            self.assertEqual(context['protocol_output_bytes'], 0)
            self.assertEqual(context['failed_command_output_bytes'], 0)

            artifact.write_text('tampered context\n', encoding='utf-8')
            result = self.run_receipt_analysis(bundle)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('evidence_status=invalid', result.stdout)


    def test_host_tokens_and_replay_bytes_have_distinct_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host_bundle = write_receipt_bundle(Path(tmp) / 'host')
            add_context_component(host_bundle, measurement_source='host_receipt', tokens=7)
            host = self.assert_valid_receipt_bundle(host_bundle)['run_matrix'][0]['context_usage']
            self.assertEqual(host['tokens'], 7)
            self.assertGreater(host['bytes'], 0)

            replay_bundle = write_receipt_bundle(Path(tmp) / 'replay')
            add_context_component(replay_bundle, measurement_source='replay_manifest', tokens=None)
            replay = self.assert_valid_receipt_bundle(replay_bundle)['run_matrix'][0]['context_usage']
            self.assertIsNone(replay['tokens'])
            self.assertEqual(replay['measurement_source'], 'replay_manifest')
            self.assertGreater(replay['bytes'], 0)


    def test_missing_context_capture_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            receipt['trace']['context_capture']['status'] = 'missing'
            rewrite_bound_receipt(bundle, receipt)
            result = self.run_receipt_analysis(bundle)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn('context capture is missing', result.stdout)


    def test_duplicate_run_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            first = bundle['index'].read_text(encoding='utf-8').strip()
            bundle['index'].write_text(first + '\n' + first + '\n', encoding='utf-8')
            result = self.run_receipt_analysis(bundle)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('duplicate run_id', result.stderr)




if __name__ == '__main__':
    unittest.main()  # noqa: F405
