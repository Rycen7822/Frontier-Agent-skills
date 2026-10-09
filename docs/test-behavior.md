# Test Behavior in FAS

Bundle 11.3.0 adds [Test Behavior](../test-behavior/SKILL.md) as the owner of check necessity, timing, valid expectations, execution evidence, lifetime and retirement. SQW continues to guide implementation and completion. Debugging, runtime verification, simplification, investigation, design, planning, review and skill evaluation retain their methods and link to the testing owner at the relevant decision. The [workflow ownership note](../test-behavior/references/workflow-ownership.md) explains those handoffs.

Apply the skill before the first edit of code or scripts used to check software behavior, including temporary or inline reproductions, installation probes, helpers, fixtures and mocks. Also apply it when behavior or compatibility obligations end or a migration completes, even if no test edit is planned. Pure reading and running existing checks do not require new tests. Explicitly requested suite tests or delivered BRTs remain delivery requirements.

The former [SQW testing reference](../software-quality-workflows/references/testing.md) remains a link to the canonical owner. Direct links resolve both in the source repository and in the packaged sibling skill layout. Test Behavior's return links support a concrete handoff; they do not require loading every workflow.

## Host activation

The new skill is eligible for implicit selection in Codex. Eligibility alone does not ensure that a model selects it, and Pi and Hermes use their own loaders. Use the [default-visible activation paragraph](../test-behavior/references/activation.md) in the relevant host's existing global instructions when it must apply independently of SQW or another named workflow.

| Host | Skill discovery | Default instruction location |
|---|---|---|
| Codex | `frontier-engineering-plugin:test-behavior` in the installed plugin catalog. | `$CODEX_HOME/AGENTS.md`, defaulting to `~/.codex/AGENTS.md`. |
| Pi | `test-behavior` in the installed package's skill paths. | Pi's agent-directory `AGENTS.md`, normally `~/.pi/agent/AGENTS.md`. |
| Hermes | `test-behavior` in the native skill catalog. | `$HERMES_HOME/SOUL.md`, normally `~/.hermes/SOUL.md`. |

Preserve personal instructions and existing skills when adding the entry. For a Pi package installed from this repository, the native command `pi update --extension git:github.com/Rycen7822/Frontier-Agent-skills` updates that package; `pi update --extensions` updates installed packages collectively. Ensure the resolved skill paths include the new `test-behavior` directory.

Verify packaged bytes and each host's native discovery in a fresh process after installation. A running session can retain an older catalog or body. These checks establish delivery and loading; claims about improved agent behavior require relevant agent execution evidence.
