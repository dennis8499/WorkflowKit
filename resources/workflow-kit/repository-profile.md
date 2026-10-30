# GitLab Workspace repository profile

The versioned kit installs Codebase LLM Wiki, MergeReviewer,
ReleaseReviewer, Output Style and the 29 Codex Skills from BMAD Method v6.12.4 Core+BMM. Install and update the complete package transactionally; use only
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
base/head branches. Load that installed Skill's rules, then use its own
`scripts/review_session.py`: `start`, necessary ordered `step` batches, `check`,
then `finish`. Save request ID, runtime, draft and artifact paths. After context
compression use `status` and its remaining work to resume the same frozen review;
use `cancel` with the same ID to abandon it. The two tools keep independent
runtime markers, job schemas, drafts and caches; route by the selected tool.

The first helper freezes base/head and fresh local peer HEADs within the declared
VSCode workspace, including its saved `.code-workspace`. Local branches, peer
HEADs, preview and copying require zero network calls; frozen review stays offline.
MergeReviewer may share in-flight synchronization or complete results younger than
300 seconds; ReleaseReviewer fetches explicit remote inputs independently. Stop
on failure without stale-ref fallback. New versions require `start --refresh`.
Group roots default to `.review-runtime/` for Merge and `.release-review-runtime/`
for Release. Single-Repo roots require an external `--runtime-root`; the workbench
uses `gitlabWorkspace.reviewRuntimePath` and a separate `release-reviewer/` child
for Release. Keep runtime outside every Git Repo.

The Skill agent applies Codex Code Review criteria to the Code Diff and follows
fixed evidence to necessary contracts and direct/indirect consumers. Merge keeps
`merge-reviewer-workspace-result/v3`, P0-P3 findings and pending confirmations.
Release keeps `ReleaseReviewDraft/v3`, direct P0/P1 blockers, evidence gaps and new
deployment dependencies; compare resource use with the entry Repo's fixed base.
Use each Skill's own evidence and result contract; helper success does not complete
semantic review. `check` gathers authoring gaps without Git; exit 3 repairs the same
frozen draft and exit 2 stops. `finish` validates evidence and saves publication
before cleanup, then safely returns that existing report when retried.

Write one Markdown report under the selected Repo's `review-reports/`, titled
`合併審查: {Repo}` for Merge or `上版檢查: {Repo}` for Release. Keep incomplete
coverage visible. Release includes an editable manual Checklist while fixed
report content stays intact. Existing reports and manual checklist entries survive
Skills updates and rollback. MR handoff supplies editable branch candidates;
posting a report remains a separate user-authorized action.

Both reviewer reports use exactly these five H2 headings, in order: `審查結論`,
`問題總攬`, `問題詳情（工程師參考）`, `範圍與限制`, `技術審查紀錄（工程師參考）`.
Problem details show name, impact, operation scenario and suggested action, then trigger,
technical explanation, impact scope, engineering fix and fixed evidence. New drafts use
Merge `report_layout=engineering-review/v1` or Release `report_layout=engineering-review/v2`
and complete that Skill's engineering fields, including Release expected/actual.
Comparison and coverage records belong in the technical section; Release dependencies
and the editable Checklist belong in scope and limitations.

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
