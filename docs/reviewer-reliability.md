# 原生審查配對驗收

本輪移除 Auto、判級、路由子代理與自動升級。兩個比較版本都由目前 agent 完成原生審查，host 明確指定同一模型與強度。配對衡量原生審查流程的改變；不能據此推算歷史 Router 的時間成本，也不能以合成來源代表原業務 Repo。

## 固定來源與版本

Baseline 是完整 Git 提交：MergeReviewer 0.21.1 `37c53df617f5baf4ef5a39384eb40e875650b55a`、WorkflowKit 1.8.0 `0b86ea0cced2680c8783083c0998a65ea389f9b9`、GitlabWorkSpace 0.48.0 `bb20007eaac8dc19496e55794b6ed00717b2ab77`。Candidate 是 0.22.0／1.9.0／0.49.0；尚未提交時使用明確的 `--working-tree`，保存每個來源及編譯檔的 hash，不能宣稱基底 commit 已含候選變更。

```powershell
python -X utf8 -B scripts/run-reviewer-reliability.py freeze --variant baseline --output .tmp/engines/baseline --merge-ref 37c53df617f5baf4ef5a39384eb40e875650b55a --workflowkit-ref 0b86ea0cced2680c8783083c0998a65ea389f9b9 --gitlab-workspace-ref bb20007eaac8dc19496e55794b6ed00717b2ab77
python -X utf8 -B scripts/run-reviewer-reliability.py freeze --variant candidate --working-tree --output .tmp/engines/candidate --merge-ref 37c53df617f5baf4ef5a39384eb40e875650b55a --workflowkit-ref 0b86ea0cced2680c8783083c0998a65ea389f9b9 --gitlab-workspace-ref bb20007eaac8dc19496e55794b6ed00717b2ab77
```

每個 engine 只能建立一次；執行前重驗所有 payload。修改來源後另建 engine，不覆寫既有觀測。套件更新時先停止正在執行的 reviewer；身分或版本不相容時保留舊 payload 與診斷。

## 合成來源與獨立答案

```powershell
python -X utf8 -B scripts/benchmark-reviewer-reliability.py prepare --output .tmp/performance-sources --case empty-query --changed-files 1 --changed-files 20
```

每案包含 16 個本機 Repo。`empty-query` 移除空清單防護，額外變更檔案是語意相同的括號調整。檔數測試驗證流程規模，不代表同檔數真實業務的複雜度。通過初始小型／大型驗收後，再增加 6、7、11 檔。

不帶 `--changed-files` 可產生七種語意案例：日期邊界、日期快取、合法重複鍵、空查詢、已識別 consumer、相容的既有行為與必要 consumer 缺失。模型只讀 `source.json`、固定 workspace 與凍結 Skill；`oracle-parent-only.json` 在 workspace 外由獨立評分者保管。

## 三組交替配對

```powershell
python -X utf8 -B scripts/run-native-review-pairs.py --manifest .tmp/performance-sources/manifest.json --baseline .tmp/engines/baseline --candidate .tmp/engines/candidate --output .tmp/paired-runs --model gpt-6-luna --effort xhigh --parallel 2 --timeout 900
```

每案依序 B→C、C→B、B→C。`--parallel 2` 僅並行獨立案例，不使用 reviewer 子代理。逾時只約束驗收程序，不是產品審查停止條件。失敗、重試、設定錯誤及網路錯誤均保存；一案發生失敗就停止該案後續擴測，不能排除失敗後宣稱三組成功。

每次執行保存來源身分、engine ledger、選定模型與強度、獨立 execution ID、完整 `trace.jsonl`、`timeline.jsonl`、原生 job、報告及 trace SHA-256。`run.json` 記錄總耗時、首次草稿、工具呼叫、可觀察 token 及原生 outcome；無法觀察的資料為 null。App Server 的獨立功能驗證使用 `scripts/verify-native-review-live.cjs`，保存實際 bridge 事件與固定設定。

## 品質及時間門檻

父層評分者閱讀固定來源與各報告，逐案保存 `adjudication`：`reviewer`、`verified`、命中的 oracle finding ID、誤報數、遺漏必要證據數與審查完整性。模型自稱完成不能代替評分。

```powershell
python -X utf8 -B scripts/benchmark-reviewer-reliability.py score --manifest .tmp/performance-sources/manifest.json --oracle .tmp/performance-sources/oracle-parent-only.json --runs .tmp/adjudicated-runs.json --output .tmp/paired-score.json
```

評分需要每案三組獨立配對、相同來源／模型／強度、有效且未重用的 trace、零來源漂移、原生發布與完整性符合獨立答案。必要缺陷、完整覆蓋及安全反例不得退步；缺少必要 consumer 的案例必須保持未完成。

1 檔候選中位耗時不得增加；6／7／11／20 檔須不超過 baseline 的 50%。提示詞字數、搜尋與工具呼叫數只記錄觀測值，不代替端到端時間。真實業務來源尚未驗證時，交付標示「實作完成、效能待驗收」。未通過初始品質與時間門檻，不擴至其餘規模或宣稱達標。

本輪實際版本、失敗嘗試、raw trace 與分段時間見 [2026-11-11 驗收紀錄](../validation/native-review-20261111.md)。先前的 [Router 時期驗證](../validation/reviewer-reliability-20261111.md) 保留為歷史紀錄。
