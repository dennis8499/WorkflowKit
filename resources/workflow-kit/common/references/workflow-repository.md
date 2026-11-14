### GitLab Workspace workflow kit

This Git repository uses the native repository profile. First read
`.agents/gitlab-workspace-kit/profile.md`, then invoke the corresponding installed
Skill. Use this repository root for Codex and Wiki. This profile governs local
tasks even when an ancestor contains a Group profile. Review helpers use the
actual declared VSCode workspace and saved `.code-workspace` when present.

For human-readable output, use the installed `$output-style` at
`.agents/skills/output-style/SKILL.md` before the selected workflow's fallback.
Preserve required artifact structure, evidence and completion gates. If absent,
keep the selected Skill's original output style.

Choose the development workflow requested by the user. When BMAD is selected, start
with `$bmad-help`, then invoke the chosen Skill; `$bmad-build` is the implementation
entry point. This repository root has one bundled runtime and 29 Codex Skills. Pass
the explicit project path to workflows, use `wiki/` as project knowledge and
`_bmad-output/` for planning and implementation artifacts. Preserve user
configuration, memory, render snapshots and generated output. If status reports
`bmadMode: external`, use the pre-existing BMAD and do not claim the kit's
`bmad-workflow` capability. Ensure the user-provided `uv` runtime is available before
running bundled BMAD workflows.

Run every local helper command from an installed Skill through this repository's
`.agents/gitlab-workspace-kit/run.py`, keeping the original command, working
directory and arguments. Bundled BMAD instructions include this wrapper; also
use it for Wiki, Reviewer, Python and Node.js helpers. Preserve each Reviewer's
existing `--runtime-root`; it must point to an authorized writable location
outside every Git Repo. If a helper requires an explicit system temporary
directory such as `--context-dir`, place it under the runner's
`<repository-root>/.gitlab-workspace/runtime/tmp` directory.

Use `$codebase-wiki` for Wiki maintenance, queries, functional exploration,
static code audit, ADR, Synthesis, BA/SA/SD, NotebookLM export and archaeology.
Normal queries are Wiki-first; source-first branches follow the Skill's router.
Use the native source inventory and Reviewer read plans. Account for all required
coverage, fixed evidence and unread obligations.
A selected concrete Query follow-up carries its one confirmation through the
bounded update/save and checks. Full Ingest uses the scanner inventory and
per-file coverage ledger; omissions, blocked files or drift remain incomplete.
Preserve user-authored Wiki content, synchronize `wiki/index.md` and append
`wiki/log.md` for durable updates. Raw sources remain read-only during Wiki work.

Use `$merge-reviewer` or `$release-reviewer` with exactly one Repo and explicit
base/head branches. Execute the native Reviewer in the current agent using fixed
model settings. Workbench supplies the task model and effort; copied prompts
inherit the current CLI settings. Use
`.agents/gitlab-workspace-kit/references/reviewer-execution.md` for saving progress,
same-request recovery and publication checks.

For a supplied `ReviewLaunchRequest/v1`, use its bound runner command verbatim;
`.agents/gitlab-workspace-kit/references/review-launch.md` defines launch,
preflight and read-only inspection. Otherwise use the installed native helper's
capabilities and documented arguments. New Merge drafts prefer supported compact
format; existing sessions retain their saved format and fixed evidence.

The native Skill owns review criteria, coverage, authoring and report layout.
Load its stage-specific reference when entering that stage. A successful helper
operation is not a semantic judgment. Preserve the same request and snapshot on
recovery; save concrete progress before handoff. Keep genuine evidence gaps
visible, and publish only the native outcome verified by its receipt. Reports
stay under the selected Repo's `review-reports/`; posting remains a separately
authorized action. Reviewer runtime must remain outside every Git Repo.

Use `$commit-reviewer` for staged Commit drafts or MR readiness checks on one explicit Repo. Follow its native `inspect`, analysis, `verify`/`report` workflow and preserve snapshot IDs, full SHAs and real developer confirmations. Commit mode reads staged changes only and stays offline. MR mode fetches only the selected remote target; ambiguous remotes need an explicit choice. Run it with the shared helper runner and a fresh `<workspace>/.commit-reviewer-runtime/<unique>` evidence directory. Exit 3 from report means a saved report still has failures, gaps or pending confirmation. Use the current Codex model settings. Present the draft for the developer to copy; Stage, Commit, Rebase, Push and MR creation remain developer actions.
