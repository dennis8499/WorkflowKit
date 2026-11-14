---
name: wk-plan
description: 從構想探索、研究、需求到架構與可執行 Story。 使用 WorkflowKit 的 /plan 入口時載入。
---

# /plan — 規劃需求與 Story

Choose only the next needed capability: idea exploration → brainstorming or forge-idea; an evidence question → deep-recon; product concept → product-brief or prfaq; unclear product requirements → prd; existing material → spec; user interaction → ux; agreed requirements → architecture; multiple deliverables → create-epics-and-stories, then sprint-planning when tracking is needed; changed direction → correct-course; deeper elicitation → advanced-elicitation. Do not run this entire sequence for a small change.

Read only the selected native Skill's SKILL.md, then its current-stage references. The candidate registry is ../../gitlab-workspace-kit/references/bmad-entrypoints.json; inspect this entry only when choosing a capability. Check the selected native Skill exists; external BMAD capabilities may differ. Do not read every candidate's full instructions.

Run installed helpers through the installation root's .agents/gitlab-workspace-kit/run.py, retaining the original cwd and arguments. Keep installation root, source root and artifact output root distinct. Follow native completion markers and renderer instructions; load a cross-entry dependency only when the native stage calls for it.

Keep local artifacts, evidence and progress. A GitLab-bound development task may create local commits; every new task commit title must contain the Host-provided (#IID). Push, Draft MR creation, Issue creation, Wiki updates and review publication require the Host's confirmation of the actual deliverable. In a copied/manual task produce the requested artifacts for the user to publish.
