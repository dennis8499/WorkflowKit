# Reviewer reliability evaluation — 2026-11-11

## Status

Implementation and deterministic checks are complete. The model acceptance run is **incomplete**, so this report does not claim that the candidate passed the quality or efficiency gates.

The 0.21.0 trial exposed overbroad cross-Repository contract searches and false incomplete reviews. That issue was addressed in MergeReviewer 0.21.1 before freezing the final candidate. This final candidate run could not reach the model service: both initial requests failed DNS resolution and subsequent WebSocket and HTTP retries. No model review or independently scorable result was produced.

## Frozen versions

| Component | Baseline | Candidate |
| --- | --- | --- |
| MergeReviewer | 0.20.6 · `baaa033da81e6814bdbf9bf13b16fe801a4d4f6b` | 0.21.1 · `37c53df617f5baf4ef5a39384eb40e875650b55a` |
| WorkflowKit runtime | 1.7.0 · `e723ce3de466d131fd44ed877b08c6f12dd3eaab` | 1.8.0 · `fb23cf375bd7bf24f88c084571fb22280119f9af` |
| GitlabWorkSpace | 0.47.0 · `dc5a17d35c129696f420b77758ded4a80254f331` | 0.48.0 · `bb20007eaac8dc19496e55794b6ed00717b2ab77` |

The benchmark harness is WorkflowKit `4859c68e709788b67bf342b2a1f9bb843b6f944c`. The frozen engine receipts verify the archived versions, full source commits, payload hashes, and Skill hashes before a run starts.

| Engine | Payload files | Reviewer Skill SHA-256 |
| --- | ---: | --- |
| Baseline | 569 | `5261e77b327af86dac783dc3e16573102bc40e8076100aeeef6529e8e5383057` |
| Candidate | 576 | `bee927a36808e5ef22a2a6b4decd4a30d1d21f972a65a10e281329b16b01da09` |

## Deterministic checks

- MergeReviewer: boundary policy 12, workspace review 14, diagnostic shapes 1, documentation 3, batch review 25, search replay 3, and session contracts 25 tests passed.
- WorkflowKit: `python test/release/reviewer_reliability_benchmark_test.py` passed all 11 tests, including freeze/version/hash checks and fail-closed scoring cases. Python compilation and Node syntax checks passed.
- GitlabWorkSpace: `npm run test:behavior` passed after adding the validation progress cases. Compile, Webview typecheck, behavior-node, renderer, issue, and connect checks passed. The focused persisted-progress unit test passed. A separate full unit run had one unrelated Windows symlink test fail with `EPERM` in this sandbox.

## Model run

- Matrix: the existing seven synthetic cases, three paired trials per case; 42 independent executions expected.
- Settings: `gpt-6-luna / xhigh`, syntax context off, prompt profile `native-review-no-routing/v2`, two workers, alternating baseline/candidate order.
- Source manifest SHA-256: `235fdbf3b0a7e46bbabc1c8b39e8d8c2122610a719dfade5f8d641ffd285ff40`.
- Outcome: 2 baseline requests started; 0 completed; 0 valid reviews; 40 executions did not start. Both traces show zero tool calls. The service logs contain DNS error 11001 followed by repeated Responses WebSocket and HTTP connection failures.
- The two attempts and their trace/log hashes are preserved in `.tmp/reviewer-reliability/runs-v0211/retry-cancellation.json`. They are infrastructure cancellations, not model-quality failures, and were excluded from scoring. No independent adjudication or score was created.

## Next step

After model-service connectivity is restored, rerun the same frozen source manifest and engine receipts into a fresh run directory. Complete all 42 executions, independently adjudicate every published report against the seven-case oracle, and score the quality and per-case median gates. Do not treat deterministic tests or this interrupted batch as model acceptance.
