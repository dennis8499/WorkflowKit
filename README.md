# WorkflowKit

WorkflowKit 是可離線安裝的 Codex 工作流程套件，包含 Codebase LLM Wiki 0.7.1、MergeReviewer 0.20.3、ReleaseReviewer 0.10.1、Output Style，以及 BMAD Method v6.12.4 Core+BMM 的 29 個 Codex Skills。支援獨立 Git Repository 與含直接子 Repo 的 Group；套件版號與 GitLab Workspace Extension 分開管理。

## 安裝

需要 Python 3.11+。安裝器不需要 Node.js 或網路；若環境沒有 `uv`，安裝仍會完成並提示你在執行 BMAD 工作流程前備妥它。

下載 `gitlab-workspace-kit-1.3.1.zip`，解壓後執行：

```powershell
python -X utf8 -B install.py --target C:\projects\MyProject
```

安裝器會依目標選擇 Group 或 Repository profile，也可明確指定：

```powershell
python -X utf8 -B install.py --target C:\projects\MyGroup --profile group
python -X utf8 -B install.py --target C:\projects\MyRepo --profile repository
python -X utf8 -B install.py status C:\projects\MyProject --expected-version 1.3.1
python -X utf8 -B install.py rollback C:\projects\MyProject <交易路徑>
```

Group profile 在選定的 Group 根目錄安裝一份共用 BMAD runtime。從子 Repo 工作時，將該 Repo 的明確路徑交給 BMAD 工作流程。Repository profile 則安裝在選定 Git Repository 根目錄。

## BMAD 設定與外部安裝

BMAD 入口是 `$bmad-help`；使用者選擇 BMAD 工作流程後，再執行相應 Skill，例如 `$bmad-build`。預設設定位於 `_bmad/config.toml`：專案名稱取安裝根目錄名稱，溝通與文件使用繁體中文，知識來源為 `wiki/`，規劃及實作產出放在 `_bmad-output/`。本機覆寫可放在 `_bmad/config.user.toml` 或 `_bmad/custom/`。

若目標根目錄已有外部 `_bmad/` runtime 或 BMAD Skill，安裝器會保留原內容，將 `bmadMode` 設為 `external`，並略過整個內建 BMAD 元件，其他工具仍會安裝。單獨存在 `_bmad-output/` 不會觸發略過。外部模式不宣告 `bmad-workflow` 能力。使用 `status` 查看目前模式與能力。

升級會逐檔管理內建 runtime，只覆寫已驗證且未修改的受管檔案。使用者設定、記憶、render snapshots、Wiki、工作產出與不屬於套件的檔案會保留；BMAD Skill 目錄若有修改或未知檔案，安裝器會停止覆寫。包含舊版 BMAD 操作的未完成交易，請使用建立該交易的原安裝器復原。

## Wiki 視覺化

使用 `$codebase-wiki` 明確要求繪製架構、流程或其他支援的圖表。固定版 Archify 會在驗證、交付、內容及瀏覽器檢查全數通過後，才一起寫入圖表與 Wiki 頁面。WorkflowKit 安裝不需要 Node.js；實際發佈圖表需要 Node.js 18+ 和本機瀏覽器。

## 建置與驗證

```powershell
python -X utf8 -B scripts/workflow-kit-sources.py --archives-only
python -X utf8 -B scripts/build-workflow-kit.py
python -X utf8 -B scripts/verify-release.py
python -X utf8 -B scripts/test.py
```

BMAD 上游固定於 [v6.12.4](https://github.com/bmad-code-org/BMAD-METHOD/releases/tag/v6.12.4) 與提交 `bab9082c3e884e0d72c759bcd1a6d90bcc01be84`。維護者可用固定來源附件、官方 CLI 與 lockfile 重建 Codex payload；一般建置只使用凍結附件，不需要 Node.js 或網路。

本機建置會產生 ZIP、獨立安裝器、`release.json`、`SHA256SUMS` 及離線來源附件。發行格式沿用 `workflowkit-release/v1`、installer API 1 與 status API 1；遠端發布另行處理。
