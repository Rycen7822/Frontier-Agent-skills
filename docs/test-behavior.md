# Test Behavior in FAS

Bundle 11.3.0 adds [Test Behavior](../test-behavior/SKILL.md) as the owner of check necessity, timing, valid expectations, execution evidence, lifetime and retirement. SQW continues to guide implementation and completion. Debugging, runtime verification, simplification, investigation, design, planning, review and skill evaluation retain their methods and link to the testing owner at the relevant decision. The [workflow ownership note](../test-behavior/references/workflow-ownership.md) explains those handoffs.

Apply the skill before the first edit of code or scripts used to check software behavior, including temporary or inline reproductions, installation probes, helpers, fixtures and mocks. Also apply it when behavior or compatibility obligations end or a migration completes, even if no test edit is planned. Pure reading and running existing checks do not require new tests. Explicitly requested suite tests or delivered BRTs remain delivery requirements.

Requirements and architecture decisions stay with the main workflow. Design discussion and ordinary implementation alone do not call for Test Behavior; its description routes tasks at check authorship or the review of directly affected protection. It does not prescribe a testing step before every development task.

The former [SQW testing reference](../software-quality-workflows/references/testing.md) remains a link to the canonical owner. Direct links resolve both in the source repository and in the packaged sibling skill layout. Test Behavior's return links support a concrete handoff; they do not require loading every workflow.

## Host activation

The skill's description is the discovery entrypoint, and it is eligible for implicit selection in Codex. Eligibility alone does not ensure that a model selects it, and Pi and Hermes use their own loaders. Installing or updating FAS preserves personal `AGENTS.md` and `SOUL.md` files. The [default-visible activation paragraph](../test-behavior/references/activation.md) is an optional manual reference; changing global instructions requires a separate explicit user request and is not an installation step.

| Host | Skill discovery | Installation surface |
|---|---|---|
| Codex | `frontier-engineering-plugin:test-behavior` in the installed plugin catalog. | The plugin's complete skill directories. |
| Pi | `test-behavior` in the installed package's skill paths. | The repository package and resolved skill paths. |
| Hermes | `test-behavior` in the native skill catalog. | The installed FAS skill directories. |

Preserve personal instructions and existing skills during installation. For a Pi package installed from this repository, the native command `pi update --extension git:github.com/Rycen7822/Frontier-Agent-skills` updates that package; `pi update --extensions` updates installed packages collectively. Ensure the resolved skill paths include the new `test-behavior` directory.

Verify packaged bytes and each host's native discovery in a fresh process after installation. A running session can retain an older catalog or body. These checks establish delivery and loading; claims about improved agent behavior require relevant agent execution evidence.
