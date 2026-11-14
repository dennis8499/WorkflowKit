# GitlabWorkSpace × WorkflowKit 整合驗證（2026-11-14）

本紀錄區分本機回歸、專用 GitLab 主路徑與尚未完成的實機矩陣，不把靜態檢查當作全量端到端驗收。1.10.0 的版本 metadata 與產物已通過正式 build／verify，正式發行仍由相同 Commit 的 GitHub Actions proof 提升已驗證產物。

## WorkflowKit 本機證據

功能候選 c189 的五個選定官方案例已跨獨立執行補齊：五入口登錄表、bundled／external × Group／Repository 四組安裝、external 原件逐 byte 保留及重裝／轉換／rollback，以及 bundled profile 轉換與個人內容保留。11 個凍結資產前後雜湊一致。

原 combined 執行的最後案例在 `TemporaryDirectory` cleanup 遇到 Windows 145，因此保留 exit 1。僅最後官方案例使用獨立短 Host Temp 重跑，功能及正常清理均通過（exit 0，211.881 秒）。沒有忽略清理錯誤或修改測試；原因尚未完全定論，也不宣稱這五個選定案例等同整套 `scripts/test.py` 通過。

1.10.0 發行準備另通過 21 個必要 metadata／來源／入口／樣式／descriptor／前版識別案例中的 20 個，1 個 symbolic-link 權限限制而略過。`workflow-kit-sources.py --archives-only` 驗證五個來源與 28 個 workspace 檔案；官方 build／verify-release 驗證 ZIP、獨立安裝器、相同 installer 副本及 checksum inventory。安裝器 7,385,352 bytes 小於既有 8 MiB 限制，ZIP 33,658,214 bytes 小於 80 MiB 限制，沒有提高下載上限或最低相容版。Kit 自有文字依 `.gitattributes` 正規為 LF 後重凍結；已逐檔核對 staged canonical bytes、工作樹及來源摘要一致，保留上游二進位原位元組。

升版檢查發現原登錄的四個 1.9.0 身分只代表較早候選，沒有包含正式發行的四種 profile。新回歸在修正前四種正式身分均重現「not a reviewed predecessor」，修正後均通過。正式附件從 GitHub tag `943d249d86a5f10ca38e7da07ade691decdc1b2d` 下載並核對 API digest；只追加其精確 variant，保留原 74 條登錄與舊候選。未知或被修改的 Skill 摘要仍拒絕，沒有將本輪未公開的 c189 1.9.0 候選標成正式版本。最小來源 fixture 與 provenance 位於 `test/fixtures/formal-workflow-kit-1.9.0/`。

## GitlabWorkSpace 整合證據

同一功能候選已驗證 Group source-first 需求探索與人工選定開卡、一般 Issue Build 的本機 Commit 與人工確認交付、僅本機的 Build Auto、固定來源六頁 Wiki 新增發布，以及雙 Reviewer 各一份報告的人工確認發布與封存。MergeReviewer 與 ReleaseReviewer 的兩則評論經正常 MR 討論 GET 回讀，各唯一一則，完整正文與核准 hash 一致。這兩份報告為靜態審查，沒有在 Reviewer 階段執行目標測試或部署。

GitlabWorkSpace 的正式 all 首輪因啟動測試的總事件數斷言失敗；原失敗紀錄保留。後續修正測試對合法背景通知的假設，保留 AbortSignal 與完整 progress 檢查，新增 MCP 前後狀態及遲到 STALE 環境事件檢查，沒有修改 runtime 或加入任意延遲。修正後完整 unit 為 1730 通過／0 失敗／4 略過；behavior 380 案、Issue 30 情境／140 步驟、Connect 10 情境／35 步驟、renderer、release 與 package／verify 分項通過。Host 為 24 通過／5 pending，未將 pending／略過計為通過。這些是分項補驗，不宣稱原單輪 all 全部成功。

## 尚待驗證

完整實機矩陣仍包含 Wiki 完整／增量更新、人工頁保留及衝突／部分／timeout；多 Issue 部分成功／unknown 及重啟對帳；全部提交歷史改寫與 target advance 情境；五入口各路由、external BMAD 原生續作、專案規則確認套用；CLI／Chat 手動實跑；舊 worktree、失效 owner、清理故障及跨平台變體。既有未知任務仍保留隔離，沒有以新環境成功補造其停止證據。
