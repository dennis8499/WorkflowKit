# WorkflowKit

獨立發行的 Codex Skills 整合包，包含 Codebase LLM Wiki、MergeReviewer、ReleaseReviewer 與 Output Style。支援單一 Git Repo 和含直接子 Repo 的 Group；版本與 GitLab Workspace Extension 分開管理。

## 下載與安裝

從 [GitHub Releases](https://github.com/dennis8499/WorkflowKit/releases) 下載 `gitlab-workspace-kit-<版本>.zip`，依 `SHA256SUMS` 核對下載內容並解壓縮。在解壓後的 `workflow-kit` 目錄執行：

```powershell
python -X utf8 -B install.py --target C:\projects\MyProject
```

需要 Python 3.11+ 和 Git。安裝器會依目標是否為 Git 根目錄選擇 Repository 或 Group profile。`--profile repository` 或 `--profile group` 可明確指定；`--dry-run` 預檢而不變更目標。

```powershell
python -X utf8 -B install.py status C:\projects\MyProject --expected-version 1.1.0
python -X utf8 -B install.py rollback C:\projects\MyProject <交易識別>
```

安裝會驗證固定上游、逐檔摘要與目標環境，保留其他 Skills、Wiki、審查報告、人工 Checklist 及工作紀錄。衝突或未完成工作會阻擋覆寫；已支援的歷史版本可以交易升級與回復。BMAD 請使用其官方 CLI 另行安裝，Megin 可獨立使用。

GitLab Workspace 0.33.0+ 也能從 GitHub 或公司內網的 WorkflowKit Gitea 鏡像線上下載安裝。

## 維護與驗證

```powershell
python -X utf8 -B scripts/build-workflow-kit.py
python -X utf8 -B scripts/verify-release.py
python -X utf8 -B scripts/test.py
python -X utf8 -B scripts/workflow-kit-sources.py --archives-only
```

固定來源附件與來源摘要隨 Repo 維護，獨立 checkout 即可建置。維護者可在同層放置上游 Repo，執行 `scripts/workflow-kit-sources.py` 比對本機內容；一般建置及 CI 不需要這些 checkout。更新上游須明確釘選正式 Release、來源提交與 SHA-256，並通過雙 profile 的安裝、升級及 rollback 測試。

修改 `VERSION` 後，將提交整合至 `main`，推送同版本的 `v<版本>` tag。CI 先測試，再發布已驗證的 ZIP、獨立安裝器、`release.json` 和 `SHA256SUMS`。`release.json` 使用 `workflowkit-release/v1`，宣告套件版本、workspaceContract、installerApi、唯讀 statusApi、最低 Extension 版本與附件摘要；Extension 據契約和能力判斷相容性，不以產品版號限制使用。

`status` 為唯讀檢查，回報 `statusContract` 與完整性；發現未完成交易時保留現場並顯示原因。重新執行明確的安裝操作會在安裝器鎖定下先處理可安全復原的交易；包含歷史 BMAD 操作的交易須使用其原安裝器處理。

公司內網可執行 `scripts/mirror-release.py --tag v1.1.0`，將 GitHub 的正式附件逐位元鏡像至 `01002903/WorkflowKit`。發布權限由環境變數 `GITEA_TOKEN` 提供；下載者不需要 Token。

本 Repo 從 GitlabWorkSpace `7475cb09fb98851a5867422279d4635aeb49a0cd` 的整合包來源拆出。內部套件識別及既有安裝標記沿用 `gitlab-workspace-kit`，以維持歷史升級與 rollback 相容性。
