# Syntax context in WorkflowKit

The installed package includes pinned Tree-sitter bindings and C#, Java,
JavaScript/JSX and TypeScript/TSX grammars for Windows x64 GIL CPython 3.11–3.14.
No target program, project test, package manager or network is executed.

## Mode and integrity

Run `scripts/syntax-context/cli.py capabilities` through the shared runner.
Its `default_mode` comes from the managed acceptance record. Until paired model
quality and end-to-end performance gates pass, the shipped default is `off`.
An explicit `WORKFLOW_KIT_SYNTAX_CONTEXT=auto` opts into evaluation; `off` keeps
the original workflow. Keep the selected mode for the same review request.
For a bound workbench task also pass `--expected-engine-sha256 <engine_sha256>`.
An asset hash mismatch is an installation error; verify/reinstall instead of
loading global packages. Unsupported runtime/language, parse errors or resource
limits retain the original source reads with a visible fallback reason.

## Reviewer workflow

The installed Merge initial-read planner and Release worklist planner read only
the native frozen blobs. The plan preserves instructions, every patch and every
necessary source/parent; its reads use the native inclusive line range API.
Execute the returned initial requests/worklist through native `step` as usual.
All Git hunk changes, including string values, constants, comments and deletions,
remain obligations. A method excerpt includes the whole member, ancestor headers,
imports and initialization context. Header/import/container changes or uncertain
mapping retain the whole-file request. Large native outputs use native paging.

Syntax facts are navigation. Check every hunk, necessary control flow and
caller/consumer; use native search/read for formal evidence. Same-name calls are
candidates, including overloads, partial classes, extension methods, DI and
reflection. Release still performs entry-base whole-Repo searches and seven-kind
dependency coverage. Parsing or finishing reads never marks semantic coverage.
Investigate unread ranges whenever the finding or changed contract depends on
them. Preserve every unresolved obligation as a gap.

The runner saves `SyntaxReadPlan/v1` metadata under its own sibling
`syntax-context/` runtime, outside native snapshots and target sources. The key
binds the fixed context; facts bind Repo/source/ref/path/raw SHA and full engine
identity. Original native requests/worklist remain the session's authoritative
read plan. Resume the same requests and IDs; a new engine cannot silently replan
an existing request. Additional native reads use new operation IDs. Syntax
sidecars contain no raw source snippets and are not report evidence.

## Wiki source branches

When the selected mode is `auto`, after the native inventory use the same CLI
for Ingest, Audit, Functional exploration and Archaeology. With mode `off`, keep
the native workflow. Example (preserve quoting for the current shell):

```text
python -X utf8 -B .agents/gitlab-workspace-kit/run.py -- python -X utf8 -B .agents/gitlab-workspace-kit/scripts/syntax-context/cli.py analyze --root <explicit-root> --path <inventory-relative-path> --expected-source-sha256 <inventory-sha256> --snapshot-id <native-snapshot-id>
```

`plan` accepts one or more `--lines START:END` ranges in the original physical
line numbering. Both source operations require the inventory SHA; drift requires
a fresh inventory. The CLI is read-only, has no persistent Wiki cache, limits
source bytes/facts/time, and paginates arrays using `--offset` / `--page-size`.
Follow `next_offset` against the same SHA and engine identity. An oversized source
remains a full native-read obligation. Use native safe inventory selection and
resource/exclusion rules before calling the helper; never discover files by
walking around that inventory.

Read the selected complete members and required context from the actual source.
For full Ingest/audit/exploration, continue through all required files/members and
entrypoints; an outline does not establish processed/checked coverage. Unread
members stay partial/not-checked/blocked. Preserve native snapshot IDs, entrypoint
IDs, file ledgers, mapping rationales and validation. Normal Query remains
Wiki-first and does not trigger a syntax scan. NotebookLM retains complete safe
captured text for DLP/readiness; syntax excerpts never replace that input.
