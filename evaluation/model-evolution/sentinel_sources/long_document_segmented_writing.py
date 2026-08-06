"""Human-owned sentinel definition for Long Document Segmented Writing."""

DEFINITION = {
    "name": "Long Document Segmented Writing",
    "version": "1.1.0",
    "context_ceiling": 32768,
    "process_required": False,
    "regression_origin": "session-scratch-artifact-overuse",
    "verifier_source": "long_document_segmented_writing_verifier.py",
    "claims": ["segmented-writing", "compaction-recovery", "whole-draft-review"],
    "process_evidence": [
        "the source inventory is mapped to bounded draft sections",
        "the recovery record preserves the active section, source anchors, and unresolved decisions",
        "the assembled draft is checked for missing claims, contradictions, and broken source bindings",
    ],
    "fixtures": {
        "fixtures/service-scope.md": "The service listens only on 127.0.0.1.\n",
        "fixtures/failure-ownership.md": "Host failures include transport loss and process termination. Product failures are incorrect or incomplete deliverables. Timeout ownership remains unresolved.\n",
        "fixtures/recovery-state.md": "Active section: Failure ownership. Sources: failure-ownership.md. Unresolved decision: whether the observed timeout belongs to Host or product.\n",
        "fixtures/run-a.md": "The run recorded zero request retries. The worker survived TUI exit.\n",
        "fixtures/run-b.md": "Two fresh attempts were created. The final receipt closed with exit code 0.\n",
        "fixtures/draft.md": "The run had zero retries [run-a.md]. The run retried twice [run-a.md]. It is release-ready [release.md].\n",
        "fixtures/release.md": "No release decision has been recorded.\n",
        "fixtures/completion.md": "Completed entries: 12. Planned entries: 12.\n",
    },
    "cases": [
        {
            "id": "direct-small-task",
            "coverage": "direct",
            "task": "Read `fixtures/service-scope.md`. In two sentences, state whether another host can directly reach the service. Do not create workflow state.",
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
            "task": "Read `fixtures/failure-ownership.md` and `fixtures/recovery-state.md`. Produce only a compact recovery packet that preserves the active section, source anchors, and unresolved ownership decision.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/failure-ownership.md",
                "fixtures/recovery-state.md",
            ],
            "semantic_oracle": [
                "packet retains the unresolved timeout ownership decision"
            ],
        },
        {
            "id": "segmented-draft",
            "coverage": "segmented-draft",
            "task": "Draft a short two-section technical report from `fixtures/run-a.md` and `fixtures/run-b.md`. Preserve the distinction between zero request retries and two fresh attempts, and attribute both claims.",
            "protected": False,
            "turns": 1,
            "initial_files": ["fixtures/run-a.md", "fixtures/run-b.md"],
            "semantic_oracle": [
                "retries and fresh attempts remain distinct and source-bound"
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
            "task": "Review `fixtures/draft.md` against `fixtures/run-a.md` and `fixtures/release.md`. Identify contradictions, unsupported claims, and broken source bindings.",
            "protected": False,
            "turns": 1,
            "initial_files": [
                "fixtures/draft.md",
                "fixtures/run-a.md",
                "fixtures/release.md",
            ],
            "semantic_oracle": [
                "retry contradiction and unsupported release claim are reported"
            ],
        },
        {
            "id": "protected-no-scratch",
            "coverage": "protected",
            "task": "Read `fixtures/completion.md` and state the completion rate directly. Do not create scratch files or expose internal workflow text.",
            "protected": True,
            "turns": 1,
            "initial_files": ["fixtures/completion.md"],
            "semantic_oracle": [
                "completion rate is 100 percent with no workflow artifact"
            ],
        },
    ],
}
