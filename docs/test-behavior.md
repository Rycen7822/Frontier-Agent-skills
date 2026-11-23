# Test Behavior in FAS

[`Test Behavior`](../test-behavior/SKILL.md) owns decisions about check necessity, timing, valid expectations, execution evidence, lifetime and retirement. It joined FAS in bundle 11.3.0. Other workflows retain their own methods and hand off testing decisions at the relevant point. See [workflow ownership](../test-behavior/references/workflow-ownership.md) for those handoffs.

Apply the skill before editing code or scripts that check software behavior. This includes temporary or inline reproductions, installation probes, helpers, fixtures and mocks. Apply it when behavior or compatibility obligations end, or when a migration completes, even if no test edit is planned. Reading code and running existing checks do not require new tests. Explicitly requested suite tests and delivered bug-reproduction tests remain delivery requirements.

Requirements and architecture decisions stay with the main workflow. Design discussion and ordinary implementation alone do not invoke Test Behavior. Its description applies when authoring checks or reviewing directly affected protection. It does not require a testing step before every development task.

The former [SQW testing reference](../software-quality-workflows/references/testing.md) links to the canonical owner. These links resolve in both the source repository and the packaged sibling-skill layout. Test Behavior's return links support a concrete handoff without requiring every workflow to load.

## Host activation

Test Behavior is eligible for implicit selection in Codex. Eligibility does not guarantee model selection. Pi and Hermes use their own loaders and invocation policies. See [host installation and invocation](hosts.md) for current setup.

The [default-visible activation paragraph](../test-behavior/references/activation.md) is an optional manual reference. Changing global instructions requires a separate explicit user request. It is not an installation step. Installing or updating FAS preserves personal `AGENTS.md` and `SOUL.md` files.

Verify packaged bytes and native discovery in a fresh host process after installation. A running session can retain an older catalog or body. These checks establish delivery and loading. Claims about improved agent behavior require relevant execution evidence.
