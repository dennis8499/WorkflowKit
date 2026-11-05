# Routing policy

The actual reviewer model is `gpt-6-luna`. Use the highest applicable effort across the selected changes. Establish risk from frozen behavior, not filenames, keyword hits, file counts, existing finding priority, or the number of supporting Repos alone. This is a starting policy to evaluate, not a guarantee that effort predicts review quality.

| Effort | Evidence needed |
| --- | --- |
| `low` | Pure explanatory prose, comments, formatting, or no effective diff; no changed runtime behavior or operational/agent instructions. |
| `medium` | Clear local logic with a bounded effect and no external contract, persistent-data side effect, security boundary or deployment change. |
| `high` | Default for ordinary implementation changes or behavior that does not meet the narrower lower-effort conditions. |
| `xhigh` | Changed cross-Repo/public contracts, authorization, data consistency, concurrency/retry semantics, or deployment dependencies/targets requiring connected reasoning. |
| `max` | Broad destructive behavior or tightly coupled high-risk mechanisms, such as a cross-service data migration with rollback and compatibility interactions. |

Read enough necessary context to explain which behavior selects the effort. Uncertainty about a plausible high-risk mechanism selects at least `xhigh` while preserving the evidence gap. A missing file remains missing at `max`.

Examples:

- Thousands of plain-language documentation edits can use `low`; changing a deployment runbook's deletion command or a Skill's authorization instructions needs behavioral assessment.
- A one-line unscoped deletion of durable production data can need `max` even in one file.
- A single-function pure calculation fix with clear local callers can use `medium`. A normal multi-function feature starts at `high`.
- A renamed API field consumed by a supporting Repo needs `xhigh`, even when the diff is small. Supporting Repos with no affected contract do not independently raise effort.
- Adding a queue/database dependency or changing its deployment target needs `xhigh`; an equivalent unused example does not establish a deployment change.
- A changed permission check plus migration and retry behavior affecting shared durable state can need `max` when the mechanisms interact.

For escalation, name the newly discovered behavior and its frozen evidence, explain why the current effort is insufficient, and checkpoint the affected earlier judgments for recheck. Raise directly to the warranted supported level. `auto` never lowers effort within a request. A manual choice is fixed even when the recommendation is higher. Never substitute another model or quietly reduce an unsupported effort.
