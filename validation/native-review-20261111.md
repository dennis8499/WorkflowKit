# 移除 Auto 與原生審查驗收：2026-11-11

交付狀態：**實作完成、效能待驗收**。移除 Auto、判級、自動升級與路由專用子代理，保留手動模型／強度、完整覆蓋及首次發布驗證。真實模型測試已有原生發布結果；目前沒有達到中大型中位耗時減半的證據，不能宣稱已恢復原業務約一小時的水準。

## 交付版本與來源

| 元件 | 交付版本 | 基底提交 |
| --- | --- | --- |
| GitlabWorkSpace | 0.49.0 | `bb20007eaac8dc19496e55794b6ed00717b2ab77` |
| WorkflowKit | 1.9.0 | `0b86ea0cced2680c8783083c0998a65ea389f9b9` |
| MergeReviewer | 0.22.0 | `37c53df617f5baf4ef5a39384eb40e875650b55a` |

本輪變更保存在工作樹，未提交或發布。交付檔案為 [VSIX](../../GitlabWorkSpace/dist/gitlab-workspace-0.49.0.vsix)、[WorkflowKit ZIP](../dist/gitlab-workspace-kit-1.9.0.zip)、[產生式 installer](../dist/workflowkit-installer-1.9.0.py) 及 [MergeReviewer ZIP](../../MergeReviewer/dist/merge-reviewer-0.22.0.zip)。SHA-256 列於驗收 JSON 與各專案的發布 checksum。

CLI 配對的候選 engine 是不可變的工作樹快照 `candidate-accepted-source`；名稱僅表示已固定來源，沒有驗收通過的含義。其 Merge Skill payload hash 為 `9fe4d53d6a5fd4970d6a7e0daad5cce405fb8fa5e11a2117e84f02f73fdbb913`。配對開始後又補上大型回應原始 artifact 連結、摘要 revision、契約範例及 Host 的暫停／清理防護；這些最終差異以後續相容測試驗證，**不得把較早快照的時間當成最終套件的有效效能驗收**。

最終來源另凍結為 `candidate-host-receipts-final`，Merge Skill payload hash `86c76f2c6d9881066eea9f59fd232fb0d2b4f7de00defe54c390b91dfbe481c9`。升級測試找到並修正 predecessor 凍結工具漏列 `review_launch.py`／`runner-capabilities.json` 的問題；補入的是已核對原始 1.8 ZIP 與提交的確切 hash，沒有接受未知來源或放寬安裝身分驗證。

## 已實作的行為

- 新 App Server 審查不建立 routing binding，模型及強度以 `model/list` 核對，每次 `turn/start` 明確傳入。CLI 提示詞由目前 agent 執行，沿用 CLI 當前設定，明確停用舊 profile 的 routing 要求。
- 所有原生 Reviewer 共用發布收據核對。回合結束不等於報告發布；沒有持久進展則待續，有進展最多在同 thread／request／設定接續兩次。已發布且有必要缺口時直接交付；既有報告的清理由 helper 完成。
- 暫停保留原生 request、快照、草稿與操作；明確取消才取消原生工作。舊 routing JSON 保持唯讀，恢復前驗證固定來源與 runtime；可用 checkpoint 僅在草稿 hash 及操作 ID 一致時匯入。沒有保存強度者須在恢復準備頁手動選擇。
- 升級仍使用現有交易、可信 predecessor 及工作台資源鎖。正在執行的工作台 Reviewer 會阻擋套件切換；獨立 CLI 升級須先停止 Reviewer。修改過的受管理檔案阻擋升級並保留原件，不強制刪除。歷史 routing、原始 launch 與 native job 不偽造完成。
- 結構化及原生 Merge preflight 純讀，不建立 request／scratch。compact 由 launcher 明確選擇，舊草稿沿用原格式；草稿與報告文件在對應階段載入。
- 批次預抓與正式搜尋共用 Repo 範圍解析。尚未註冊的契約延後預抓；無效查詢不預先執行 Git。原生 `author` 以操作 ID、預期 hash、compact 更新與 journal 保存草稿／checkpoint，重送冪等，衝突不覆寫。
- `status --summary` 讀保存進度與最近檢查，附 revision、時間及 freshness；不展開草稿或重新做 diagnostics。相同 blob 共享正文，保留來源、操作 artifact 及覆蓋義務。最終結論由 outcome 產生，首次發布仍完整驗證固定證據與搜尋。
- 診斷新增保存的階段／等待區間、各次 thread／turn、派送設定與 native helper 時間。未觀察到的模型／強度及 token 保留未知；累積 token 不冒充每回合增量。

## 功能與相容測試

最終計數及原始 log 索引保存在 [驗收 JSON](native-review-20261111.json)。

| 驗證 | 結果 |
| --- | --- |
| GitlabWorkSpace 全 unit sweep | 1,352 項：1,348 通過、3 跳過、1 項競態壓力測試未通過；該項獨立重驗 100 輪／300 次派送通過 |
| 固定設定／原生收據／舊啟動綁定相關測試 | 81 項通過；最終 native 完成／checkpoint／清理／Release 收據 15 項及提示詞 10 項，合計 25 項通過 |
| GWS lint、TypeScript、webview build、VSIX 驗證 | 通過；最終包另有版本與 checksum 驗證 |
| MergeReviewer 主要回歸 | 127 項中 125 項通過；兩項環境阻擋後在正常環境重驗通過 |
| Merge 原生效率／evidence view／session flow | 47 項通過，另有文件測試 3 項通過 |
| WorkflowKit launch／benchmark／source | 14／12／9 項；benchmark 的 engine 清理遇 WinError 32，該項獨立重驗通過 |
| 四種 1.8→1.9 升級／重複安裝／回復與客製 Router 保留 | 四種 profile／BMAD 組合及修改拒絕斷言通過 |
| 真實 1.8 native request 原地續作 | Group／Repository 均保留原 input digest、開始時間、固定來源、草稿及操作；原 ID 重送可重用，歷史 routing 不改寫，完整測試含清理通過 |
| 最終包安裝後原生 Merge／Release、獨立 installer、BMAD 與 predecessor | 5 項通過 |

Git 搜尋測試直接攔截底層 `run_git_capture` 的 `grep` 位置，核對 repo-local 及 identified-repos 沒有掃描無關 peer；另驗證新契約順序與無效 query。草稿測試涵蓋保存、冪等重送、hash 衝突、中斷復原、checkpoint freshness、便宜唯讀摘要及相同正文去重。ReleaseReviewer 原始審查邏輯未修改，使用安裝後的原生 facade 驗證相容性。

Host 的 Release 收據檢查另對齊原生規則：checksum 保留報告末尾 metadata，只排除可編輯 Checklist，並依 Python 原生讀檔方式處理換行。回歸驗證 Checklist 編輯可接受、固定正文變動被拒絕，避免有效 Release 報告被誤判為未發布。

受限沙箱的 MSYS 命名物件／符號連結拒絕與 App Server 子程序逾時，分別以正常 Windows 環境重驗，保留原失敗 log。第一次廣泛 WorkflowKit discovery 已停止，沒有完整通過結果；另一輪 OneDrive 暫存的安裝驗證也已停止，改用正常本機暫存位置重驗相同重要案例，不能把中止紀錄算成成功。舊 Router／Skills 數量斷言與漏填的契約 scope 已修正。續作測試一度假設舊版存在 `fixed_identity`，改為核對實際可用的固定來源；所有續作斷言通過後的 Windows 超長備份清理錯誤，也已限制在原測試目錄內以 extended path 重驗通過。測試中重建同版本包造成的狀態誤差，另以固定最終包重驗。

## 真實 App Server 功能驗證

使用實際 Codex CLI 0.166.0 的 App Server、產品 bound launch 與 CodexBridge。模型 `gpt-6-luna`、強度 `high`，單一 Repo fixture 移除除數為零的防護。

完成耗時 **250.167 秒**；原生 `published`、`review_complete=true`，捕捉 1 次、request 1 個、報告 1 份，沒有 fetch 或來源工作樹變更。報告正確指出 `ZeroDivisionError`，快照 context 已清理；沒有 routing summary 或 routing child。事件 SHA-256：`276a696a4b92c442808585b68df0dd25d9204ba5188d4537db15eacf1bfff1cd`。

原始 [result](../.tmp/native-review-app-server-gpt-6-luna-high-result.json)、[events](../.tmp/native-review-app-server-gpt-6-luna-high-events.json)、[streaming trace](../.tmp/native-review-app-server-gpt-6-luna-high-trace.jsonl) 保留。這是功能驗證，與 CLI 配對的來源及強度不同，不能混用計算加速比。它使用較早本輪工作樹；後續 Host 差異另由上列測試覆蓋。

另外保存三次診斷失敗：未綁定舊入口、Windows runtime 尚未建立，以及較早 CLI 300 秒診斷逾時。runtime 建立與互動回覆競態已修正；原本失敗結果保留，不覆寫為成功。

## 真實 CLI 配對

每案 16 Repo，同一份固定來源、`gpt-6-luna`／`xhigh`，B→C、C→B、B→C 交替。兩版都使用 native review、停用 routing，故不能據此推算歷史 Router 本身的成本。1 檔與 20 檔來源各只有一項預植空清單缺陷，其餘檔案為安全括號調整。

本輪配對與同機回歸測試並行，機器負載沒有隔離；加上候選快照與最終交付存在上述差異，時間只能作診斷觀測，不是受控的發布效能驗收。

<!-- observed-results:start -->
| 檔數 | 版本 | 第幾次 | 總秒數 | 首次草稿秒數 | 工具呼叫 | 命令失敗 | 執行結果 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | baseline | 1 | 496.864 | 417.999 | 30 | 3 | completed／published |
| 1 | candidate | 1 | 453.163 | 366.759 | 19 | 2 | completed／published |
| 1 | baseline | 2 | 382.881 | 315.110 | 17 | 0 | completed／published |
| 1 | candidate | 2 | 577.787 | 472.028 | 26 | 3 | completed／published |
| 1 | baseline | 3 | 516.056 | 446.439 | 20 | 1 | completed／published |
| 1 | candidate | 3 | 854.870 | 804.272 | 36 | 7 | completed／published |
| 20 | baseline | 1 | 580.191 | 531.623 | 37 | 2 | completed／published |
| 20 | candidate | 1 | 630.159 | 478.605 | 30 | 4 | completed／published |
| 20 | candidate | 2 | 900.619 | 832.884 | 97 | 5 | timed-out／published |

1 檔三組：baseline 中位 496.864 秒、candidate 中位 577.787 秒，比值 1.163。小型不變慢門檻：未通過。20 檔因第二次候選逾時，沒有三組有效配對，不能計算發布門檻所需中位數。
<!-- observed-results:end -->

父層獨立核對 `previous_day([])` 應由 `None` 退化為 `IndexError`、安全變更沒有新缺陷、固定版本及逐檔覆蓋。預植缺陷召回與誤報只適用這些合成來源；P1／P2 分級在重複執行間有差異，不能據此宣稱正式品質已穩定。真實業務、必要 consumer 缺失、安全反例等完整模型矩陣仍未驗收。

20 檔候選第二次執行 900.619 秒逾時：原生報告已發布，但 CLI 程序未在驗收上限內正常結束，保留失敗狀態。trace 顯示 97 次工具呼叫，包含 PowerShell 引號／單元素陣列修復及 compact／展開欄位衝突；首次草稿在 832.884 秒才保存。這些作者工作與模型協調成本沒有因 Router 移除而消失。`authoring_retries=0` 的舊量測僅計 check／finish 的 exit code 3，不能解讀成沒有 author 或 shell 重試；完整命令失敗另列在驗收 JSON。

依規則，初始大型案例失敗後不擴測 6／7／11 檔，不排除逾時後計算成功中位數。不放寬品質或時間門檻、不以提示詞變短或工具呼叫減少替代端到端加速。

## 保留證據與後續門檻

原始 CLI run、trace、timeline、native job、報告與凍結 engine 由 [驗收 JSON](native-review-20261111.json) 索引；可攜證據包位於 `dist/native-review-validation-20261111.zip`。原始失敗嘗試、測試 log、模型設定及 checksum 均保留，不提供不可觀察的子代理設定或估算 token。

正式加速仍需用最終 package 凍結新 engine，取得真實業務來源後完成同模型／強度的三組配對；必要缺陷與完整覆蓋不得退步，1 檔不得變慢，6／7／11／20 檔中位耗時至少減半。通過之前，本輪只交付實作及相容性成果。
