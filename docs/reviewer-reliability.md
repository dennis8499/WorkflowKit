# 審查可靠性與配對驗收

本輪使用八份 2026-11-10 對話的去識別互動模式，改善啟動、完成判定、查詢、恢復與草稿成本。對話中的業務 findings 不是正確答案；原始業務 Repo 不在驗收輸入中。

`test/fixtures/reviewer-reliability-cases.json` 對應全部八份紀錄。核心與整合測試涵蓋路徑漂移、preflight 不耗用 request、null reason、非阻擋說明、必要缺口、唯讀查詢、完成進度及 compact 修稿。正式來源與發布前搜尋重驗保持不變。

## 合成來源與獨立答案

```powershell
python -X utf8 -B scripts/benchmark-reviewer-reliability.py prepare --output .tmp/reliability-sources
```

每個案例建立 16 個本機 Git Repo：一個受審服務、固定 consumer（適用時）與無關 peer。案例涵蓋到期日邊界、歷史日期快取、合法重複鍵、空查詢、API consumer、既有行為／相容新增欄位，以及必要 consumer 缺失。所有分支及 peer HEAD 都是固定合成內容，不使用外部網路或真實業務資料。

只把案例的 `source.json`、workspace 與待測已固定 Skill 交給 reviewer。`oracle-parent-only.json` 放在 workspace 外，由獨立評分者保管；不能提供給 reviewer，也不能從答案自動填草稿。

## 凍結三個執行元件

Baseline 與 candidate 都要凍結 MergeReviewer、WorkflowKit 及 GitlabWorkSpace 的完整提交，不允許用目前 `HEAD` 代替基準版本。以下 ref 是本輪 0.20.6／1.7.0／0.47.0 對 0.21.1／1.8.0／0.48.0 的固定比較：

| Component | Baseline | Candidate |
| --- | --- | --- |
| MergeReviewer | `baaa033da81e6814bdbf9bf13b16fe801a4d4f6b` | `37c53df617f5baf4ef5a39384eb40e875650b55a` |
| WorkflowKit | `e723ce3de466d131fd44ed877b08c6f12dd3eaab` | `fb23cf375bd7bf24f88c084571fb22280119f9af` |
| GitlabWorkSpace | `dc5a17d35c129696f420b77758ded4a80254f331` | `bb20007eaac8dc19496e55794b6ed00717b2ab77` |

```powershell
python -X utf8 -B scripts/run-reviewer-reliability.py freeze --variant baseline --output .tmp/reliability-engines/baseline --merge-ref baaa033da81e6814bdbf9bf13b16fe801a4d4f6b --workflowkit-ref e723ce3de466d131fd44ed877b08c6f12dd3eaab --gitlab-workspace-ref dc5a17d35c129696f420b77758ded4a80254f331
python -X utf8 -B scripts/run-reviewer-reliability.py freeze --variant candidate --output .tmp/reliability-engines/candidate --merge-ref 37c53df617f5baf4ef5a39384eb40e875650b55a --workflowkit-ref fb23cf375bd7bf24f88c084571fb22280119f9af --gitlab-workspace-ref bb20007eaac8dc19496e55794b6ed00717b2ab77
```

The engine receipt records each full commit, reads component versions from the archived source, and hashes every archived and compiled payload. `run` rejects edited or mismatched engines before starting a model. Change the expected release pair and these refs together when starting a later acceptance cycle.

## 配對紀錄

每個案例至少三組 baseline／candidate，交替執行順序。配對使用相同模型、強度及 `source_identity`；所有回合開始前固定兩個版本的完整 Skill。每個 run 保存下列資料：

- `case`、`variant`（baseline 或 candidate）、`trial`、`source_identity`、`model`、`effort`、`skill_sha256`。
- `prompt_profile=native-review-no-routing/v2`；模型與強度由 host 固定，執行原生審查流程，不呼叫 routing completion。
- 每次獨立執行的 `execution_id`，以及實際 trace 的 `trace_path` 與 `trace_sha256`；trace 必須保留，雜湊不符或重用同一次觀測不能評分。
- `prompt_chars`、`tool_calls`、`elapsed_seconds`、`first_draft_seconds`、`duplicate_document_bytes`、`authoring_retries`；僅填觀測值。
- `status=completed`、`exit_code=0`、`native_state=published`、空 `source_drift` 及有效 `native_outcome` 都是必要條件。原生 `review_complete` 必須符合獨立人工評分；失敗、逾時、未發布、來源變更或結果不符都使評分拒絕該資料。
- `tokens` 為實際 token usage，無法觀測時填 null，不能由字數或 helper 時間推算。
- `adjudication` 保存獨立評分者 `reviewer`、`verified`、`matched_findings`（oracle 中的 ID）、`false_positives`、`required_evidence_omitted` 與 `review_complete`。不能用模型自稱完成取代核對。

```powershell
python -X utf8 -B scripts/benchmark-reviewer-reliability.py score --manifest .tmp/reliability-sources/manifest.json --oracle .tmp/reliability-sources/oracle-parent-only.json --runs .tmp/observed-runs.json --output .tmp/reliability-score.json
```

無觀測資料、未滿三組、缺少 trace 或未獨立評分，都不能通過。合成測試中的示範 metrics 只驗證評分器，不是實測結果。

## 門檻

候選版本須符合各案例的獨立答案，沒有新增漏報、誤報、假完成或必要證據遺漏。品質先通過，才比較每案中位數：啟動提示字數比例 ≤0.50、工具呼叫 ≤0.80、總時間 ≤1.10。真實必要缺口案例應保持未完成，不能為了提高完成率消掉缺口。

七個案例各做三組配對，共 42 次獨立模型執行；配對要交錯執行，並凍結相同來源、模型與思考強度。

helper 重播、prompt 長度測試、模型判斷小測試與完整模型審查分開紀錄。只有完整配對且品質及成本門檻全數通過，才能宣稱本輪端到端驗收通過。Syntax context 預設仍為 off。

本輪實際命令及結果見 [2026-11-11 驗證紀錄](validation/reviewer-reliability-20261111.md)。
