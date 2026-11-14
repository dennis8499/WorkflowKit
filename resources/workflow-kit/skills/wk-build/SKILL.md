---
name: wk-build
description: 完成明確變更、Bug 或 Story，執行測試並展示成果。 使用 WorkflowKit 的 /build 入口時載入。
---

# /build — 實作與修改

Use bmad-build by default. Use bmad-build-auto only when explicitly requested and the Host or current session has verified synchronous subagents and actual sandbox git add/commit support. Otherwise explain the missing capability and offer ordinary Build. Auto requires a clean worktree; a blocked record must be diagnosed before retry, and a done record starts a follow-up review rather than an ordinary resume. Preserve the native renderer: run.py → uv render_skill.py → the single workflow.md printed to stdout.

Read only the selected native Skill's SKILL.md, then its current-stage references. The candidate registry is ../../gitlab-workspace-kit/references/bmad-entrypoints.json; inspect this entry only when choosing a capability. Check the selected native Skill exists; external BMAD capabilities may differ. Do not read every candidate's full instructions.

Run installed helpers through the installation root's .agents/gitlab-workspace-kit/run.py, retaining the original cwd and arguments. Keep installation root, source root and artifact output root distinct. Follow native completion markers and renderer instructions; load a cross-entry dependency only when the native stage calls for it.

Keep local artifacts, evidence and progress. A GitLab-bound development task may create local commits; every new task commit title must contain the Host-provided (#IID). Push, Draft MR creation, Issue creation, Wiki updates and review publication require the Host's confirmation of the actual deliverable. In a copied/manual task produce the requested artifacts for the user to publish.
