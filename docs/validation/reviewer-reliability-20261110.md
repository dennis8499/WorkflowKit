# 2026-11-10 審查可靠性驗證

此檔隨本輪實作補入實際驗證結果。日期採使用者時區 Asia/Taipei。

## 已觀測

- 合成 oracle／評分器測試：7/7 通過。包含品質退步、來源不符、模型不符、無實測 metrics、trace 雜湊不符、必要缺口假完成等拒絕案例。
- 七種合成來源已成功建立，每案 16 個 Git Repo，模型審查狀態明確記為 `not-run`。
- Codex CLI 0.166.0、`gpt-6-luna / xhigh` 可用性探測成功；只有回覆 READY，不算審查品質或效能驗收。

## 尚未完成的門檻

完整模型基線／候選配對、獨立語意評分、工具次數與端到端耗時門檻尚未取得完整觀測。不得將單元測試或合成 oracle 自測視為這些門檻已通過。

## 2026-11-11 Windows 與發行驗證

TEMP、TMP 與 TMPDIR 指向 repo 外的 `C:\Users\denni\Temp`。完整 `scripts/test.py` 通過 207 tests、0 failures、2 skipped；兩項 skip 都是 Windows 帳號無法建立 symbolic link 的測試。`scripts/test_release_ci.py -v` 在來源凍結後另通過 25 tests。

MergeReviewer 0.21.0 以乾淨提交 `eb3e7caffcf7b587bd7307bf96cf0ca2d6fd2e06` 凍結，來源 archive SHA-256 為 `ee2000a83d922ebd161246709b2a89f6edf634135d4d3f233279ecebdaace54e`。WorkflowKit 1.8.0 建置與 `verify-release.py` 均通過：tar archive 10,931,704 bytes、SHA-256 `8f10758b419440968c8539fb40b691dba3bf13aa966c4f49bd94556cf59b99b3`；release ZIP 35,740,439 bytes、SHA-256 `fe14a447a959ea06641920cb62e103d03219dfe329b5d4e8d7044e59db6e3cef`；installer SHA-256 `f0c93f6716e709cb40ef74945043032d5216a7f3259deba65b94ba1e34891354`。

GitlabWorkSpace 的 Windows `npm test` 使用外部暫存與證據目錄 `C:\Users\denni\Temp\gws-full-acceptance-20261111\evidence`，完整 suite `success`。unit 為 1,358 passed、0 failed、3 skipped；VS Code extension 為 24 passing、4 pending；package 與 VSIX 驗證通過。這次安裝了 VS Code 1.145.3，整份驗證耗時約 43 分 54 秒。

完整 Codex 模型 baseline／candidate 配對與獨立品質評分仍為 `not-run`；不以可用性探測、helper 測試或合成 oracle 自測代替端到端驗收。
