---
name: wk-goal
description: 分類任務、核對目前階段並協調下一步。 使用 WorkflowKit 的 /goal 入口時載入。
---

# /goal — 描述目標，讓 BMAD 選流程

Use the user's goal and the observed project artifacts to choose one entry: plan for discovery/specification/design, build for implementation, verify for assessment/testing, project for rules/progress. If phase or required input is unclear, read only bmad-help and ask the missing question. Once selected, invoke only that entry. For GitLab Wiki, Group requirement analysis, Issue development or MR review launched by GitLab Workspace, preserve the Host's fixed source and delivery binding.

Read only the selected native Skill's SKILL.md, then its current-stage references. The candidate registry is ../../gitlab-workspace-kit/references/bmad-entrypoints.json; inspect this entry only when choosing a capability. Check the selected native Skill exists; external BMAD capabilities may differ. Do not read every candidate's full instructions.

Run installed helpers through the installation root's .agents/gitlab-workspace-kit/run.py, retaining the original cwd and arguments. Keep installation root, source root and artifact output root distinct. Follow native completion markers and renderer instructions; load a cross-entry dependency only when the native stage calls for it.

Keep local artifacts, evidence and progress. A GitLab-bound development task may create local commits; every new task commit title must contain the Host-provided (#IID). Push, Draft MR creation, Issue creation, Wiki updates and review publication require the Host's confirmation of the actual deliverable. In a copied/manual task produce the requested artifacts for the user to publish.
