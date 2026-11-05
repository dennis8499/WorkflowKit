---
name: output-style
description: Choose concise, explanatory, learning or formal presentation for GitLab Workspace answers, progress and work artifacts. Apply when using the installed Wiki, merge or release workflow, or when the user invokes $output-style or requests an output style.
---

# Output Style

Adapt human-readable output to the current task. This installed Skill replaces the
other workflow Skills' fallback presentation rules; their workflow, evidence and
artifact contracts still govern the work. It does not change host settings.

## Choose the mode

Accept `style=auto|concise|explanatory|learning|formal` in the user's prompt.
An explicit style or natural-language presentation request wins over automatic
selection. Apply it to the requested task; extend it across later tasks only when
the user asks. `style=auto` restores automatic selection. No new CLI option,
review-result field or configuration file is required.

For `auto`, choose separately for each answer or artifact:

| Mode | Use when | Presentation |
| --- | --- | --- |
| `concise` | Status, direct questions, routine actions and completion replies | State the result first; include the essential evidence, limitation and next action. Simple answers usually need one to three sentences. |
| `explanatory` | Why/how questions, diagnosis, mechanisms and comparisons | Give the answer, then explain the cause or decision using relevant evidence, tradeoffs and a concrete example when useful. |
| `learning` | The user asks to learn, be taught or receive a walkthrough | Explain the relevant concepts and steps while completing the authorized work. Use a worked example or a short optional exercise when helpful. |
| `formal` | Reports, requirements, plans, acceptance records and durable work documents | Use the target artifact's required structure, traceability and level of detail; put the main conclusion in its existing summary or first paragraph. |

A formal artifact and its short chat delivery may use different modes. An
ambiguous ordinary reply defaults to `concise`; an artifact with a required
template uses `formal`. Select silently without adding a mode announcement.
Read [the examples](references/examples.md) before authoring a MergeReviewer or
ReleaseReviewer draft, when the task mixes modes, or when an explicit override
could conflict with a required artifact.

## Make merge and release reviews readable

For MergeReviewer and ReleaseReviewer, apply the following in every mode to
drafts, reports, progress and delivery. Write for PMs, QA and engineers; `formal`
keeps the required structure and evidence while using plain reader-facing prose.
Other workflows retain their existing presentation rules.

- Write the plain-language content in the workflow's existing draft fields
  before `check` and `finish`. Let the native helper validate and render the
  report, then deliver it unchanged. Keep its five sections, finding blocks,
  evidence and editable confirmation records.
- Start the summary with the actual merge or release recommendation, the main
  reason and the next action. When there are no confirmed defects, name the
  checked scope and any pending confirmations or evidence gaps. Say what the
  evidence supports rather than declaring an unconditional pass.
- Use concrete behavior in titles, impact, scenarios and expected/actual results:
  who or which system is affected, what action or timing triggers it, and what
  happens. For example, write 「付款成功通知重送時，可能重複建立訂單」 instead of
  only 「缺少冪等性保護」. Explain a necessary term in everyday Chinese before
  its original name in parentheses; keep identifiers and literal evidence exact.
- Give an actionable fix and how to verify it. In engineering fields, retain
  the precise cause, affected scope, relevant symbols and source citations.
  Describe only supported consequences; mark code-derived scenarios as inferred
  and reserve reproduced claims for actual execution records.
- In dependency descriptions, recommendations and next steps, explain how to
  complete the generated deployment checklist: identify the target environment
  or resource, the action to check and the expected result or verification evidence.
  Keep the helper-generated questions and unknown conditions pending. Ask for
  proof of configuration or access without secret values; preserve human entries.
- In progress replies, state the verified result so far and the remaining work.
  In completion replies, give the actual recommendation, important blockers or
  gaps and one clickable report link. Keep all material limitations even when
  `style=concise` needs more than three sentences.

This follows the result-first communication and task-specific Skill guidance in
[Claude Code output styles](https://code.claude.com/docs/en/output-styles).

## Preserve the work

- Write in Traditional Chinese unless the user or target project specifies another
  language. Keep code, commands, paths, IDs, schema keys, status values and raw
  evidence verbatim.
- Preserve the target artifact's required sections, finding fields, evidence,
  checklists, approval and acceptance records. An explicit style changes prose
  density and explanation, not those requirements.
- Keep every finding, pending confirmation, blocker, coverage gap, limitation,
  material error and required verification result. Distinguish proved facts,
  inference, unexecuted checks and human confirmations. Concision does not change
  a review verdict or turn an incomplete check into a pass.
- Keep raw outputs and literal human responses unchanged in their evidence
  records. Summarize them only where the workflow permits a separate summary.
- Continue the requested work in every mode. Learning adds explanation; it does
  not add approval gates, require the user to implement a step, or leave an
  authorized task unfinished for an exercise.
- Follow the current task's permissions, scope and completion gates. Presentation
  never authorizes additional writes, publication or external actions.
