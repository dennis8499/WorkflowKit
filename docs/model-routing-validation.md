# Model Routing 驗證紀錄

2026-11-05，Codex CLI 0.166.0，模型固定 `gpt-6-luna`。本機模型目錄提供 low、medium、high、xhigh、max。原始紀錄見[實測 JSON](validation/model-routing-20261105.json)；可使用 `node scripts/benchmark-model-routing.cjs` 重跑，工作台須先編譯，必要時以 `WORKFLOWKIT_WORKBENCH_ROOT` 指定路徑。

## 固定內容案例

| 內容 | 預期／實際路由 |
| --- | --- |
| 大量純敘述文件 | low／low |
| 單一純計算函式的局部格式處理 | medium／medium |
| 一般多函式匯入功能 | high／high |
| 單行取消租戶條件的整批資料刪除 | max／max |
| 跨 Repo API 欄位改名及未更新的 caller | xhigh／xhigh |
| 新佇列尚未部署、consumer 尚未切換 | xhigh／xhigh |
| Markdown Skill 改變授權行為 | xhigh／xhigh |
| 大量文件混入權限檢查刪除 | xhigh／xhigh |

8／8 路由符合固定案例的預期。資料刪除、跨 Repo、部署、混合權限四個案例另以固定 high 與 auto 所選強度分別審查；兩組均辨識所有四個案例的已知問題，包括部署案例的佇列與 consumer 兩項缺失。全程未呼叫工具。

## 時間與用量

| 階段 | 回合數 | 總秒數 | 總 tokens |
| --- | ---: | ---: | ---: |
| 八個案例的 high 路由判斷 | 8 | 81.747 | 143,628 |
| 四個關鍵案例的固定 high 審查 | 4 | 37.436 | 68,363 |
| 四個關鍵案例的 auto 正式審查 | 4 | 50.644 | 69,101 |

數值包含該客戶端的固定上下文，快取命中及推理 token 另保留於原始 JSON。auto 的正式審查時間以外，還有前置路由成本；這組品質優先的小樣本沒有證明節省 tokens 或延遲。

這是隔離靜態內容的單次比較，用於檢查初始政策與關鍵缺陷回歸；原生 capture、草稿、發布、恢復及安裝相容性由獨立整合測試驗證。

## 整合與封裝回歸

- WorkflowKit 的 16 組 release unittest 與 release CI，共 172 個案例；Windows 無權建立 symlink 的 1 個案例略過。初次並行執行的安裝逾時、Chrome 清理與最後一個 profile 案例已分別補跑通過；1.3.6 的 Group／Repository、BMAD bundled／external 升級、重裝及 rollback 四種組合均已驗證。
- GitlabWorkSpace 完整單元回歸共 1,103 項：1,095 通過、3 略過、5 失敗。長時間主機停頓期間失敗的 5 項既有 Git／程序案例單獨重跑全部通過，另有 1 項名稱相符的案例通過。Routing Bridge 的 24 項測試包含五種手動強度、實際啟動參數、升級、取消、恢復、模型不可用、使用者補充及發布後續問答。
- 工作台 lint、TypeScript、webview 型別檢查、兩個 webview build、VSIX 封裝與內容驗證通過。最後的手動 bootstrap 與 Windows 停止確認修正另通過 46 項相關回歸。WorkflowKit source pin、Skill 結構與發行 ZIP／installer 驗證通過。
- 真實 Luna 的原生 MergeReviewer 測試以 `high` 判斷後選擇 `medium`，保留同一 request／固定 SHA，完成 coverage、原生發布及 Routing complete，產出一份報告且 `review_complete=true`。Git fetch 次數為 0，受版控的工作樹保持乾淨。最終任務為 `completed`，capture、job、報告均恰好一份；證據摘要與封裝 SHA-256 見[整合實測 JSON](validation/model-routing-integration-20261105.json)。

Windows PowerShell 管線造成 Unicode 損壞的問題已加入共用 reviewer 指引；保留可恢復的 authoring 診斷，沒有以路由閱讀代替 coverage。另修正 `taskkill` 將已退出子程序列為失敗的競態：退出碼 128 只有在根程序與輸出中每個目標 PID 均確定不存在時才接受，仍有程序存活、探測失敗或缺少根程序資訊時持續保留鎖與待核對狀態。

測試主機曾長時間停頓，因此完整回歸的總 wall-clock 不適合用於效能比較；上方隔離模型案例的用量與耗時另行保存。

執行 `node scripts/verify-model-routing-live.cjs` 可重跑真實原生審查：先完成 WorkflowKit build 與工作台 compile，腳本以目前 Codex 帳號呼叫模型，在系統暫存目錄建立新的 Group／Repo，保留 fixture 供檢視，並將結果寫入 `.tmp/model-routing-native-result.json`。它不會自動核准額外存取；缺少模型、環境或必要權限會保存診斷並失敗。工作台路徑亦可用 `WORKFLOWKIT_WORKBENCH_ROOT` 指定。
