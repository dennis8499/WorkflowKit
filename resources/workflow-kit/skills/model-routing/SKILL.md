---
name: model-routing
description: Route WorkflowKit MergeReviewer and ReleaseReviewer reviews to the selected model's reasoning efforts using frozen changes and risk evidence. Apply before either installed Reviewer, for effort overrides, and when resuming or escalating a routed review.
---

# Model Routing

Use the workbench-supplied model and supported efforts for assessment and review. A direct Skill without model selection retains `gpt-6-luna` and the legacy five efforts. Accept `effort=auto` (default) or a supported manual effort for this request. Read [execution protocol](references/execution.md) for capture, dispatch or recovery; read [routing policy](references/routing-policy.md) only when assessing or escalating risk. Native authoring and output-style examples are needed when writing their artifacts, not before launch validation.

Select the current role before following the numbered workflow:

- `routing_adapter=workbench routing_phase=assess`: perform step 1 only; save `decide`, then return `action=review`.
- `routing_phase=review` or `routing_role=reviewer`: the assessment has ended. Start at step 2 in the current agent and complete the native review, authoring, `check` and `finish`. The only successful exits are saved `complete` or a saved strictly higher `escalate`. A manual workbench request with no native job first performs the capture/bind bootstrap, then continues the native review in this same turn.
- A direct parent without either marker performs the full workflow and dispatches the reviewer child.

## 1. Freeze once and assess

Resolve exactly one Reviewer, Repo, base and head, and the authorized external runtime. Read its native Skill and capabilities. Carry the supplied request ID; otherwise generate a UUID. Validate the launch before loading deeper authoring references. For a supplied bound request, read `.agents/gitlab-workspace-kit/references/review-launch.md`. Otherwise check `<runtime>/jobs/<id>.json`: resume an existing job, or run supported read-only preflight and native `start` once when absent. New Merge sessions prefer advertised compact format; older helpers and existing sessions keep their supported format. Save runtime, context, draft and evidence paths.

Use the kit runner's defaults: `python -X utf8 -B <runner> -- python -X utf8 -B <helper> <command> ... --runtime-root <native-runtime>`. The native `--runtime-root` belongs after `--`, in the helper arguments. The runner stores its own temporary/cache files in a separate location; its optional runtime override must never point to the native review runtime. Use the concrete host-supplied helper command when provided; see [the two runtime paths](references/execution.md#runner-and-native-runtime).

Run `routing.py bind --tool <tool> --runtime-root <runtime> --request-id <id> --effort <requested>`, adding the supplied `--model` and `--supported-efforts` for workbench selections. This binds routing to that native job's fixed sources, model and capabilities. Reuse a saved decision on recovery. Routing reads never mark coverage reviewed and never fill semantic review decisions.

In `auto`, read the complete change inventory and patches through native evidence operations, including continuations, then enough context to establish the highest applicable risk tier. Once frozen behavior supports that choice, hand off remaining consumer investigation to the reviewer. Preserve uncertainty in the handoff; do not finish semantic review during assessment. Save a UTF-8 decision JSON with `effort`, concrete `reason`, `evidence` references and a checkpoint naming pending reads and decisions. Run `routing.py decide ... --revision <revision> --decision-file <file>`. Line counts and paths alone cannot establish risk. Manual effort is selected by `bind` without assessment.

The assess role stops after saving the decision and returns `{"action":"review","request_id":"<id>"}`. The host starts the review at the selected effort. The review role continues through native publication or escalation. Never start a child from the workbench adapter.

## 2. Execute at the selected effort

For a direct Skill, start exactly one fresh reviewer child with the saved record's explicit model and selected reasoning effort. Pass `routing_role=reviewer`, the routing state path, native Skill path, tool, request ID, runtime, context, draft, fixed sources and original user instructions. Give it the checkpoint on recovery. Wait for it to yield or complete before dispatching another child. Preserve the parent's sandbox and authorization. Failure to start the exact model/effort stops dispatch and preserves the session.

For `routing_role=reviewer` or `routing_adapter=workbench routing_phase=review`, execute the native Reviewer in the current agent. This is the already-routed continuation: use `status` and the saved context, and proceed with native evidence operations, authoring, `check` and `finish`. For a manual workbench request without a job yet, first perform step 1's single capture and `bind`; then continue the review in this same turn. Do not route recursively. A review includes all native coverage, evidence and publication requirements.

Read [reviewer execution](references/reviewer-execution.md) before doing the review. A direct parent includes this role guidance and the record's `files`, draft and checkpoint in its child handoff. If an active native request remains unfinished after a child yields without escalation, ask that same child to continue the concrete authoring/validation work, at most twice, then report the saved unfinished state. This continuation keeps the same model, effort and capture; terminal errors and unknown dispatches stop.

## 3. Checkpoint, escalate or complete

If new fixed evidence needs greater effort in `auto`, save the native draft and a UTF-8 handoff with `effort`, `reason`, `evidence` and `checkpoint` (remaining work plus previously reviewed paths/decisions to recheck). Run `routing.py escalate ... --revision <revision> --decision-file <file>`, then yield `{"action":"escalate","request_id":"<id>"}` when a strictly higher actual effort was saved. The parent/host starts that effort only after this execution ends. Recheck the checkpoint's affected decisions before continuing. At the saved model's maximum, retain the cap reason and finish the current review with missing evidence visible.

A manual effort remains fixed. Record a higher-effort recommendation in progress or supported `scope_notes` and continue at the requested effort. Reserve native limitations for necessary missing evidence; a model recommendation or a hypothetical external consumer is not such a gap.

After each completed semantic work unit, save the native draft and `routing.py checkpoint` with the current revision. Its `ReviewExecutionCheckpoint/v1` records completed operation IDs, unread continuations, open questions and the next concrete action. The helper binds it to the request, fixed snapshot and saved draft hash. It does not mark coverage reviewed or change effort. Resume from native status and this checkpoint; reconcile a changed draft before trusting the older navigation notes.

After native `finish` and receipt verification, run `routing.py complete ... --revision <revision>`. This requires a published native job and preserves its review outcome, including incomplete coverage. Deliver the report link, important findings, gaps and actual effort. The workbench assessment returns its requested JSON; the formal reviewer delivers ordinary prose after saving completion or escalation. The host reads the saved state and receipt.

After context compression or interruption, call native `status` and `routing.py status` for the same ID. Reuse the decision, fixed sources and checkpoint; a deliberate refresh uses a new ID. Show the selected effort, reason and any escalation to the user. Routing records survive native context cleanup. Cancellation follows the native helper and preserves the routing audit record.
