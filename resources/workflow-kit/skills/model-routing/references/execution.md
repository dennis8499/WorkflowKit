# Execution protocol

## Runner and native runtime

The native runtime is an ownership boundary containing review jobs and fixed evidence. The kit runner owns a different directory for `tmp/` and `uv-cache/`. Keep these two paths separate before the first capture.

Use the runner's defaults and put the native runtime argument only after the separator:

```text
python -X utf8 -B <install-root>/.agents/gitlab-workspace-kit/run.py -- python -X utf8 -B <native-skill>/scripts/review_session.py start --workspace <workspace> --project <repo> --base <base> --head <head> --runtime-root <native-runtime> --request-id <id>
python -X utf8 -B <install-root>/.agents/gitlab-workspace-kit/run.py -- python -X utf8 -B <model-routing>/scripts/routing.py bind --tool <tool> --runtime-root <native-runtime> --request-id <id> --effort <requested>
```

For native session commands the runner automatically uses `<native-runtime>-workflow-kit` as its cache/temp sibling. Other helpers use the installation's `.gitlab-workspace/runtime`. An explicit runner override, when necessary, must name a separate authorized directory. Passing the native runtime to the runner before `--` fills it with cache files and prevents native ownership initialization; preserve that diagnostic and stop instead of deleting unknown contents.

Check for `<native-runtime>/jobs/<request-id>.json` with a local file existence check before calling `status`. A fresh review has no marker or job yet; perform native `start` once in that case.

## Routing state

Run `<model-routing-dir>/scripts/routing.py` through the installed kit runner, preserving the native runtime argument. Commands emit bounded JSON and use no Git or network operations:

```text
bind --tool merge-reviewer|release-reviewer --runtime-root PATH --request-id UUID --effort auto|low|medium|high|xhigh|max
status --tool TOOL --runtime-root PATH --request-id UUID
decide --tool TOOL --runtime-root PATH --request-id UUID --revision N --decision-file PATH
escalate --tool TOOL --runtime-root PATH --request-id UUID --revision N --decision-file PATH
complete --tool TOOL --runtime-root PATH --request-id UUID --revision N
```

`bind` requires a successful native capture, derives the immutable source identity, and atomically creates `runtime/routing/<tool>/<request-id>.json`. Existing matching binds are idempotent; mode/identity changes are errors. `status` returns `ReviewModelRouting/v1`. Mutations require the returned revision. On a conflict, reload status and reconcile; never overwrite another revision. Exact decision-file retries return the existing result.

The record includes tool, request, runtime/context/draft paths, native input digest, immutable source identity and hash, requested effort, selected model/effort, phase, reason/evidence, checkpoint, history and revision. `phase=routing` needs assessment; `reviewing` is ready for native semantic review; `complete` requires a native published receipt. Historical records remain readable after native context cleanup. Their presence is not permission to dispatch a cancelled or failed job.

A decision file is a UTF-8 JSON object:

```json
{"effort":"xhigh","reason":"The renamed API field is consumed by the fixed billing Repo.","evidence":["service/head/<sha>/api.py:12; billing/head/<sha>/client.py:24"],"checkpoint":"Recheck the API compatibility judgment, then trace the billing caller."}
```

`checkpoint` is required for escalation. References must point to actual frozen evidence; the state helper validates structure and identity, while the agent and native Reviewer validate semantics. Store logical identifiers and masked excerpts, never credentials or full connection strings.

The workbench invokes `$model-routing` for `routing_phase=assess`, with `routing_adapter=workbench`, the supplied request ID/runtime and original native prompt. The assessment saves its decision and returns `{"action":"review","request_id":"<id>"}` under the host's output schema; it never publishes. Formal review uses the native Skill, shared reviewer execution guidance and the saved handoff paths. It delivers the native report or a saved escalation in ordinary prose. The host reads `ReviewModelRouting/v1`, validates model availability and exact effort through `model/list`, and starts each turn with explicit `model` and `effort`. The persisted state and native receipt, rather than the model's final prose, establish completion.

Formal review and each escalation use a fresh reviewer conversation. The handoff carries the original task, accepted user supplements, fixed native session and checkpoint. Continue the native review from those artifacts; the assessment's completion rule applies only to its own conversation.

Direct execution uses the current parent for assessment and a fresh Luna child for each chosen effort. Pass `routing_role=reviewer` to the child and the checkpoint when replacing it. The parent waits until the previous child has ended, reloads status, then either reports completion or dispatches the strictly higher selected effort. A child uses the native Reviewer in its current execution and never starts another routing child. Both adapters preserve the native draft/coverage schemas, source verification, sensitive-value masking and incomplete-review semantics.
