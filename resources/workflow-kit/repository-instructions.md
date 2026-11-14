### GitLab Workspace workflow kit

Use the selected repository root and preserve the Host's fixed source, output paths and delivery binding.

For BMAD, use `$wk-goal` to choose a workflow, `$wk-plan` for planning, `$wk-build` for implementation, `$wk-verify` for assessment or `$wk-project` for rules and progress. Load only the current native Skill and stage references. Use external BMAD only for capabilities actually installed. Build Auto requires explicit selection, synchronous subagents and verified sandbox local Git support.

For Wiki queries or source-first functional exploration use `$codebase-wiki`; existing Wiki is not required for functional exploration. For MR review choose `$merge-reviewer` or `$release-reviewer` with one explicit Repo and fixed base/head. For staged Commit drafts use `$commit-reviewer`. Read `.agents/gitlab-workspace-kit/references/workflow-repository.md` only when the selected workflow needs its knowledge, review or profile-specific rules; preserve native artifact/evidence contracts.

Run local Skill helpers through the absolute installation root's `.agents/gitlab-workspace-kit/run.py`, retaining cwd and arguments. Preserve Reviewer `--runtime-root` outside Git Repos. For supplied ReviewLaunchRequest use its bound command and read the review-launch reference.

Keep source, installation and task output roots distinct. A GitLab Issue task may make local commits whose titles include its provided (#IID); the Host validates the whole commit chain. Remote publication, push and Draft MR creation require confirmation of the actual results. Copied/manual tasks produce artifacts for the user to publish. Project rules are proposed diffs until the user confirms applying them to the original Group/Repo.
