---
name: wk-project
description: 維護代理指引、自訂設定、討論及查看進度。 使用 WorkflowKit 的 /project 入口時載入。
---

# /project — 專案規則與進度

Choose project-context for verified agent guidance, customize for persistent workflow settings, party-mode for requested multi-role discussion, sprint-planning status for Sprint progress, help for next-step guidance. Resume an existing record with the capability that created it and its exact Story/file identity. Project-rule changes are a proposed diff; apply them to the original Group/Repo only after the user confirms that diff.

Read only the selected native Skill's SKILL.md, then its current-stage references. The candidate registry is ../../gitlab-workspace-kit/references/bmad-entrypoints.json; inspect this entry only when choosing a capability. Check the selected native Skill exists; external BMAD capabilities may differ. Do not read every candidate's full instructions.

Run installed helpers through the installation root's .agents/gitlab-workspace-kit/run.py, retaining the original cwd and arguments. Keep installation root, source root and artifact output root distinct. Follow native completion markers and renderer instructions; load a cross-entry dependency only when the native stage calls for it.

Keep local artifacts, evidence and progress. A GitLab-bound development task may create local commits; every new task commit title must contain the Host-provided (#IID). Push, Draft MR creation, Issue creation, Wiki updates and review publication require the Host's confirmation of the actual deliverable. In a copied/manual task produce the requested artifacts for the user to publish.
