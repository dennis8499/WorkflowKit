---
name: wk-verify
description: 審查程式或文件、建立測試、導覽變更與回顧。 使用 WorkflowKit 的 /verify 入口時載入。
---

# /verify — 檢查、測試與驗收

Choose code-review for code defects, review for documents/general deliverables, qa-generate-e2e-tests for executable API/E2E tests, walkthrough for understanding a change, retrospective for an Epic review. This entry assesses the specified target; findings do not authorize unrelated edits or remote publication.

Read only the selected native Skill's SKILL.md, then its current-stage references. The candidate registry is ../../gitlab-workspace-kit/references/bmad-entrypoints.json; inspect this entry only when choosing a capability. Check the selected native Skill exists; external BMAD capabilities may differ. Do not read every candidate's full instructions.

Run installed helpers through the installation root's .agents/gitlab-workspace-kit/run.py, retaining the original cwd and arguments. Keep installation root, source root and artifact output root distinct. Follow native completion markers and renderer instructions; load a cross-entry dependency only when the native stage calls for it.

Keep local artifacts, evidence and progress. A GitLab-bound development task may create local commits; every new task commit title must contain the Host-provided (#IID). Push, Draft MR creation, Issue creation, Wiki updates and review publication require the Host's confirmation of the actual deliverable. In a copied/manual task produce the requested artifacts for the user to publish.
