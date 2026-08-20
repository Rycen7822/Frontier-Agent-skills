"""Human-owned sentinel definition for Long Document Segmented Writing."""

DEFINITION = {
    "name": "Long Document Segmented Writing",
    "version": "2.0.0",
    "repeats": 3,
    "context_ceiling": 32768,
    "minimum_baseline_failure_cases": 2,
    "process_required": False,
    "regression_origin": "session-scratch-artifact-overuse",
    "verifier_source": "long_document_segmented_writing_verifier.py",
    "claims": ["segmented-writing", "compaction-recovery", "whole-draft-review"],
    "grader_rules": [
        "For long-document-segmented-writing-compact-recovery, quality passes when the sole recovery block has distinct Current recovery anchor, Next action, Final-assembly order, and Confidence gaps/proof fields bound to the supplied facts.",
        "For long-document-segmented-writing-compaction-resume, turn one owns the recovery anchor; quality evaluates the final self-contained two-section report and requires the correct distinction between request retries and fresh attempts.",
        "For long-document-segmented-writing-full-mode-selection, quality passes when 13 sources select full mode and the answer names scope, source inventory, reading ledger, section matrix, recovery packet, ordered section drafts, confidence review, and final document.",
        "For long-document-segmented-writing-whole-draft-review, quality passes when the answer identifies that zero retries overstates zero request retries, the twice-retried claim is contradicted by zero request retries, and release readiness is unsupported by the no-decision source.",
    ],
    "process_evidence": [
        "the source inventory is mapped to bounded draft sections",
        "the recovery record preserves the active section, source anchors, and unresolved decisions",
        "the assembled draft is checked for missing claims, contradictions, and broken source bindings",
    ],
    "fixtures": {
        "fixtures/service-scope.md": "The service listens only on 127.0.0.1.\n",
        "fixtures/failure-ownership.md": "Host failures include transport loss and process termination. Product failures are incorrect or incomplete deliverables. Timeout ownership remains unresolved.\n",
        "fixtures/recovery-state.md": "Active section: Failure ownership. Final assembly order: Failure ownership. Sources: failure-ownership.md. Unresolved decision: whether the observed timeout belongs to Host or product.\n",
        "fixtures/run-a.md": "The run recorded zero request retries. The worker survived TUI exit.\n",
        "fixtures/run-b.md": "Two fresh attempts were created. The final receipt closed with exit code 0.\n",
        "fixtures/draft.md": "The run had zero retries [run-a.md]. The run retried twice [run-a.md]. It is release-ready [release.md].\n",
        "fixtures/release.md": "No release decision has been recorded.\n",
        "fixtures/completion.md": "Completed entries: 12. Planned entries: 12.\n",
        "fixtures/mode-selection.md": "Source count: 13. Final section count: 2. Cross-session recovery: no. Full audit requested: no.\n",
    },
    "cases": [
        {
            "id": "direct-small-task",
            "coverage": "direct",
            "task": "Read `fixtures/service-scope.md`. Return one direct statement of reachability plus a brief reason as the complete response.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/service-scope.md"],
            "semantic_oracle": [
                "loopback-only service is not directly reachable from another host"
            ],
        },
        {
            "id": "compact-recovery",
            "coverage": "compact-recovery",
            "task": "Read `fixtures/failure-ownership.md` and `fixtures/recovery-state.md`. Apply the bound compact ledger contract. Output only its recovery block, with every field required by that contract bound to the supplied facts.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/failure-ownership.md",
                "fixtures/recovery-state.md",
            ],
            "semantic_oracle": [
                "recovery block contains the current anchor, next action, final assembly order, and confidence gap or proof"
            ],
        },
        {
            "id": "full-mode-selection",
            "coverage": "mode-selection",
            "task": "Read `fixtures/mode-selection.md`. Apply the bound long-document mode thresholds. Return only the selected mode, the triggering threshold fact, and every canonical artifact class owned by that mode.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/mode-selection.md"],
            "semantic_oracle": [
                "13 sources select full mode with eight nonduplicated artifact classes"
            ],
        },
        {
            "id": "compaction-resume",
            "coverage": "compaction-resume",
            "task": "This is a two-turn report task using `fixtures/run-a.md` and `fixtures/run-b.md`. First complete section one and provide a compact recovery anchor for section two. After the continuation request, return a self-contained completed two-section report.",
            "continuation": "Resume from the recovery anchor and return the self-contained completed two-section report, preserving the distinction between request retries and fresh attempts.",
            "protected": False,
            "turns": 2,
            "initial_files": ["fixtures/run-a.md", "fixtures/run-b.md"],
            "semantic_oracle": [
                "recovery anchor retains worker survival and final receipt evidence"
            ],
        },
        {
            "id": "whole-draft-review",
            "coverage": "whole-draft-review",
            "deterministic_quality_process": True,
            "task": "Review `fixtures/draft.md` against `fixtures/run-a.md` and `fixtures/release.md`. Return only valid JSON with shape `{\"findings\":[{\"claim\":string,\"source\":string,\"status\":string,\"source_fact\":string}]}`. Include one object per defective draft claim. Copy claim text without its citation or terminal punctuation; copy the supporting source sentence verbatim including punctuation; use only the source basename. Use `overbroad` when the source supports only a narrower claim, `contradicted` when the source states an incompatible fact, and `unsupported` when no source establishes or rules out the claim.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/draft.md",
                "fixtures/run-a.md",
                "fixtures/release.md",
            ],
            "semantic_oracle": [
                "three exact claim/source/status/source_fact bindings identify both retry defects and the unsupported release claim"
            ],
        },
        {
            "id": "protected-no-scratch",
            "coverage": "protected",
            "task": "Read `fixtures/completion.md` and return the completion rate as the complete response.",
            "protected": True,
            "turns": 1,
            "initial_files": ["fixtures/completion.md"],
            "semantic_oracle": [
                "completion rate is 100 percent in one direct response"
            ],
        },
    ],
}
