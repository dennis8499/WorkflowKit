# GitLab Workspace repository profile

The versioned kit installs Codebase LLM Wiki, MergeReviewer,
ReleaseReviewer, CommitReviewer, Output Style and the 29 Codex Skills from BMAD Method v6.12.4 Core+BMM. Install and update the complete package transactionally; use only
its verified manifest and source snapshots. This profile applies to the selected actual Git repository root. Use its local
Wiki and native Wiki Skill; review helpers still honor the declared VSCode
workspace boundary.

## Development

Choose the development workflow requested by the user. The kit bundles BMAD Method
Core+BMM for Codex. Use `$bmad-help` to choose a workflow, then invoke the selected
BMAD Skill; use `$bmad-build` for implementation work when the user selects BMAD.
The `_bmad/` runtime is installed at this repository root. Configuration defaults use
the root folder name, Traditional Chinese for communication and documents, `wiki/`
for project knowledge, and `_bmad-output/` for planning and implementation artifacts.
Put local overrides in `_bmad/config.user.toml` or `_bmad/custom/`; keep user memory,
render snapshots and generated output. If an external BMAD runtime or Skill already
exists at this root, the installer preserves it and skips the bundled BMAD component
while continuing to install the other tools. Check `bmadMode` before assuming the
`bmad-workflow` capability. Before running bundled workflows, prepare the
user-provided `uv` runtime; installation itself works offline and does not need Node.js.

## Skill helper execution

Run local helper commands from BMAD, Codebase Wiki, MergeReviewer,
ReleaseReviewer and the other installed Skills through the shared runner so
Python, Node.js and `uv` use a writable runtime. Preserve the original working
directory, command arguments, output and exit status. Use the absolute runner
path under this repository root:

Runner syntax: `run.py [--runtime-root PATH] -- COMMAND [ARG ...]`. For example,
to check the installed MergeReviewer capabilities while keeping its arguments:

```powershell
$runner = (Resolve-Path ".agents\gitlab-workspace-kit\run.py").Path
python -X utf8 -B $runner --read-only -- python -X utf8 -B .agents\skills\merge-reviewer\scripts\review_session.py capabilities
```

For Node.js or `uv`, replace the command after `--` with the original executable
and arguments, for example `node .agents\skills\codebase-wiki\vendor\archify\bin\archify.mjs --help` or `uv run --no-cache python -c "print('ready')"`.

Bundled BMAD command examples already pass through this runner; retain their
`uv run` arguments. In external BMAD mode, apply the same wrapper to helper
commands from the pre-existing Skills. Reviewer commands keep their existing
`--runtime-root` argument and session state; point it to an authorized writable
location outside every Git Repo. If a helper requires an explicit system
temporary directory such as `--context-dir`, place it under the runner's
`<repository-root>/.gitlab-workspace/runtime/tmp` directory.

## Knowledge

Use `$codebase-wiki` for Wiki maintenance, queries, functional exploration,
static code audit, ADR, Synthesis, BA/SA/SD, NotebookLM export and archaeology.
Normal queries are Wiki-first; source-first branches follow the Skill's router.
A selected concrete Query follow-up carries its one confirmation through the
bounded update/save and checks. Full Ingest uses the scanner inventory and
per-file coverage ledger; omissions, blocked files or drift remain incomplete.
Preserve user-authored Wiki content, synchronize `wiki/index.md` and append
`wiki/log.md` for durable updates. Raw sources remain read-only during Wiki work.

Repository Wiki lives at `wiki/`; source references are repository-relative.
NotebookLM and full-source scans must use the requested root and scanner safety
rules. Sensitive exclusions remain unread. Source and evidence drift prevent a
complete result. Wiki work does not publish Issues or remote Git operations.

## Branch review

Use `$merge-reviewer` or `$release-reviewer` with exactly one Repo and explicit
base/head branches. Read `.agents/skills/model-routing/SKILL.md` and select the
current role: assessment, executing reviewer, or recovery. It owns model choice,
effort selection and handoff. Workbench selections remain fixed to the supplied
model and supported efforts; a direct call keeps the installed default.

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

## Installation and recovery

Only a verified installation record grants ownership of managed files. Updates
replace current managed content and remove unchanged retired managed Skills.
Local modifications or unknown ownership stop the update before mutation.
User Wiki, work records, locks, reports, exports and unrelated Skills remain.
A retained transaction supports explicit rollback, including removed files.
Interrupted transactions recover before subsequent install/status operations.

## Output

For human-readable output, use the installed `$output-style` at
`.agents/skills/output-style/SKILL.md` before the selected workflow's fallback.
Preserve required artifact structure, evidence and completion gates. If absent,
keep the selected Skill's original output style.

Use `$commit-reviewer` for staged Commit drafts or MR readiness checks on one explicit Repo. Follow its native `inspect`, analysis, `verify`/`report` workflow and preserve snapshot IDs, full SHAs and real developer confirmations. Commit mode reads staged changes only and stays offline. MR mode fetches only the selected remote target; ambiguous remotes need an explicit choice. Run it with the shared helper runner and a fresh `<workspace>/.commit-reviewer-runtime/<unique>` evidence directory. Exit 3 from report means a saved report still has failures, gaps or pending confirmation. Use the current Codex model settings. Present the draft for the developer to copy; Stage, Commit, Rebase, Push and MR creation remain developer actions.
