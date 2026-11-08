# Tree-sitter integration, WorkflowKit 1.6.0

WorkflowKit adds installed-only syntax hooks to Codebase Wiki 0.7.2,
MergeReviewer 0.20.6 and ReleaseReviewer 0.12.0. Original upstream repositories,
ZIPs and pins are unchanged. Overlay manifests authenticate every installed
replacement; native evidence and report validators retain their upstream bytes.

The shared helper vendors official Windows x64 wheels for GIL CPython 3.11–3.14:
Tree-sitter 0.26.0, C# 0.23.5, Java 0.23.5, JavaScript 0.25.0 and TypeScript 0.23.2.
JSX and TSX are included. `vendor-lock.json` records original wheel URLs, hashes,
ABIs and licenses; `bundle.json` binds every extracted file, query and helper.
Maintainers refresh with `scripts/prepare-syntax-vendor.py`; normal builds and
installed runtime do not download or install packages.

The bundle fixes the core language-ABI range (13 through 15) and each grammar's
ABI (C#/JavaScript 15; Java/TypeScript/TSX 14). Windows builds load each pinned
grammar and compile the selected query to check that binding. Runtime loading
checks the same exact ABI. Wheel license texts remain MIT. The four small
WorkflowKit-authored selector queries carry their own revision/hash and
`NOASSERTION` license metadata because this repository declares no separate
public license for its own source.

Merge initial requests and Release worklist requests select complete changed
members, headers, imports and initialization from fixed blobs. Existing native
line-range operations provide evidence. Container/header changes, errors,
unsupported sources or mapping limits retain original reads. Add/delete/rename
paths with no reliable two-sided mapping retain full native reads. Literal Git
changes remain obligations even when syntax shape is identical. Read plans and
operation IDs are saved once. Native coverage and semantic conclusions remain
agent-authored; parser completion cannot mark them reviewed.

Wiki uses its original safe inventory, source SHA and snapshot identity before
syntax navigation. Full workflows still account for every required file and
entrypoint. Query stays Wiki-first, and NotebookLM full-source DLP is unchanged.
Wiki syntax CLI is read-only and uses process-local cache. Reviewer metadata
sidecars use the runner-owned external runtime.

GitlabWorkSpace 0.44.0 binds the whole shared bundle with
`SyntaxAnalysisBinding/v1` in its existing runner binding, rechecks it before
launch, and carries the identity through new, copied and resumed tasks. Native
upstream payload identity and final installed payload identity remain distinct.
VSIX contains only integration code; parser assets remain in WorkflowKit.

The acceptance record currently ships `default_mode=off`: independent paired
model quality and total review-time evidence are still required. Explicit
`WORKFLOW_KIT_SYNTAX_CONTEXT=auto` enables evaluation; `off` restores original
reads. Mechanical context-byte reduction alone cannot pass the enablement gate.
See the installed [agent reference](../resources/workflow-kit/common/references/syntax-context.md)
for CLI, range semantics, fallbacks and completion obligations.

The 1.5.0 predecessor is frozen from the committed local HEAD after verifying
the original ZIP's payload and installer against committed fingerprints. Its
Group/Repository and bundled/external identities are trusted for transactional
upgrade and rollback; this does not claim external release publication.

The pinned 0.26.0 Windows core wheels crash on CPython 3.11–3.13 when their
progress callback is exercised. The helper parses bounded immutable bytes with
an external process watchdog instead; tests cover real parsing on every ABI.

## Acceptance evidence

`python -B scripts/benchmark-syntax.py --output <report.json>` measures selected
source bytes and cold/warm in-memory facts-cache costs. Grammar-module and OS
caches may already be warm. It cannot establish model-token reduction, whole
review time, required coverage, missed defects or false positives.

For independent model trials, pass `--model-results <paired-runs.json>`. The JSON
array contains `scenario`, `size` (`large` / `small`), `cache` (`cold` / `warm`),
`model`, `effort`, `fixture_sha256`, `expected_critical`, `off` and `auto`. Each
run contains a unique `run_id`, actual `input_tokens`, `tool_round_trips`,
`total_seconds`, independently judged `critical_found`, `false_positives` and
`coverage_complete`. Keep the fixture/model/effort fixed and record at least
three independent pairs for each cache state of every scenario. Include both
large and small scenarios and safe cases whose `expected_critical` is empty.

The scorer requires the full declared critical-defect set, preserves baseline
defect detection, rejects increased false positives or incomplete coverage,
and checks the 20% large-input, 10% large-total-time and 5% small-regression
thresholds for every group. It records the evidence-file SHA and tool-round-trip
medians. Scoring never edits the managed acceptance record or enables a package.
