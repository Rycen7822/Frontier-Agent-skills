"""Human-owned sentinel definition for Long Document Segmented Writing."""

DEFINITION = {
    "name": "Long Document Segmented Writing",
    "version": "1.1.0",
    "context_ceiling": 32768,
    "regression_origin": "session-scratch-artifact-overuse",
    "claims": ["segmented-writing", "compaction-recovery", "whole-draft-review"],
    "process_evidence": [
        "the source inventory is mapped to bounded draft sections",
        "the recovery record preserves the active section, source anchors, and unresolved decisions",
        "the assembled draft is checked for missing claims, contradictions, and broken source bindings",
    ],
    "cases": [
        (
            "direct-small-task",
            "direct",
            "Source A states that the service listens only on 127.0.0.1. Answer whether it is directly reachable from another host in two sentences, and do not create workflow state.",
            False,
            1,
        ),
        (
            "compact-recovery",
            "compact-recovery",
            "A report is paused in section 'Failure ownership'; Source A lines 12-18 define Host failures, Source B lines 4-9 define product failures, and the unresolved decision is whether a timeout is Host- or product-owned. Produce only a compact recovery packet.",
            False,
            1,
        ),
        (
            "segmented-draft",
            "segmented-draft",
            "Draft a short technical report in bounded sections from these facts: Source A says retries are zero; Source B says two attempts were created. Preserve the distinction and attribute each claim.",
            False,
            1,
        ),
        (
            "compaction-resume",
            "compaction-resume",
            "Begin a two-section report from Source A: the worker survived TUI exit, and Source B: the final receipt closed with exit 0. Complete section one and include a compact recovery anchor for section two.",
            False,
            2,
        ),
        (
            "whole-draft-review",
            "whole-draft-review",
            "Review this assembled draft: 'The run had zero retries [Source A]. The run retried twice [Source A]. It is release-ready [Source B].' Source A records zero retries and Source B records no release decision. Identify contradictions, missing support, and broken claims.",
            False,
            1,
        ),
        (
            "protected-no-scratch",
            "protected",
            "Source A records 12 completed entries out of 12 planned entries. State the completion rate directly; do not create scratch files or expose internal workflow text.",
            True,
            1,
        ),
    ],
}
