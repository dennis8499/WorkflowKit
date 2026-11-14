# WorkflowKit

WorkflowKit 是可離線安裝的 Codex 工作流程套件，包含 Codebase LLM Wiki 0.7.3、MergeReviewer 0.22.0、ReleaseReviewer 0.12.1、Output Style，以及 BMAD Method v6.12.4 Core+BMM 的 29 個 Codex Skills，另提供五個輕量 BMAD 入口。支援獨立 Git Repository 與含直接子 Repo 的 Group；套件版號與 GitLab Workspace Extension 分開管理。

1.10.0 加入 BMAD 五入口、三個常用操作與按階段載入，支援 source-first 需求探索及 GitLab Workspace 的固定來源、獨立任務與人工確認交付流程。Build Auto 須明確選用並通過實際 sandbox 能力檢查；既有 external BMAD 與個人內容保持受保護。詳見 [1.10.0 發行說明](docs/releases/v1.10.0.md)與[整合驗證紀錄](docs/validation/workflow-integration-20261114.md)。

工作台的新管理入口與獨立任務交付需搭配 GitLab Workspace 0.51.0；獨立 CLI Skills 及既有 installer／status API 保持相容。

1.9.0 移除 Auto、路由子代理與實驗性 Tree-sitter 整合，審查使用固定模型設定和原生讀取計畫，並整合原子草稿與搜尋範圍修正。詳見 [1.9.0 發行說明](docs/releases/v1.9.0.md)。

1.8.0 加入固定啟動請求、唯讀審查查詢及 compact 能力協商，整合完成判定、報告渲染與進度修正。新功能由安裝能力啟用，既有 CLI 與歷史收據保持相容。詳見 [1.8.0 發行說明](docs/releases/v1.8.0.md)與[可靠性驗收](docs/reviewer-reliability.md)。

1.7.0 新增審查模型選擇：支援此能力的 GitLab 工作台可指定模型與思考強度，評估、正式審查及升級沿用同一模型。未指定模型時保留 Luna 預設。詳見 [1.7.0 發行說明](docs/releases/v1.7.0.md)。

## 安裝

需要 Python 3.11+。安裝器不需要 Node.js 或網路；若環境沒有 `uv`，安裝仍會完成並提示你在執行 BMAD 工作流程前備妥它。

下載 `gitlab-workspace-kit-1.10.0.zip`，解壓後執行：

```powershell
python -X utf8 -B install.py --target C:\projects\MyProject
```

安裝器會依目標選擇 Group 或 Repository profile，也可明確指定：

```powershell
python -X utf8 -B install.py --target C:\projects\MyGroup --profile group
python -X utf8 -B install.py --target C:\projects\MyRepo --profile repository
python -X utf8 -B install.py status C:\projects\MyProject --expected-version 1.10.0
python -X utf8 -B install.py rollback C:\projects\MyProject <交易路徑>
```

Group profile 在選定的 Group 根目錄安裝一份共用 BMAD runtime。從子 Repo 工作時，將該 Repo 的明確路徑交給 BMAD 工作流程。Repository profile 則安裝在選定 Git Repository 根目錄。

整合後的 Skills 透過 `.agents/gitlab-workspace-kit/run.py` 啟動本機 Python、Node.js 與 `uv` 輔助工具。它會把暫存檔和 `uv` 快取放在安裝根目錄的 `.gitlab-workspace/runtime/`；單 Repo 的 Reviewer 仍須使用 Git Repo 外已授權可寫的 `--runtime-root`。

## Reviewer 固定模型設定

`$merge-reviewer`、`$release-reviewer` 由目前 agent 執行完整原生審查。工作台在建立任務時選擇模型與固定強度；複製提示詞沿用目前 CLI 設定。審查以原生發布收據和必要缺口判斷完成，不再呼叫 Router。

恢復保留原 request、固定 SHA、草稿及操作紀錄。GitLab Workspace 0.49.0 可將舊路由工作轉為原保存模型及最後強度；尚未選定強度時先完成手動設定。歷史 JSON 保留作稽核，不補跑 routing complete。正在執行或派送不明的任務須先確認停止，才能切換套件。


## BMAD 設定與外部安裝

從 `$wk-goal` 描述目標，由智慧入口選擇流程；已有明確目的時可直接選以下入口。入口只載入目前需要的原生 Skill 與階段參考，不會先讀完整 BMAD 能力集合。

| 工作台入口 | CLI／Codex 聊天 | 用途 |
|---|---|---|
| `/goal` | `$wk-goal` | 任務分類、選擇流程與下一步 |
| `/plan` | `$wk-plan` | 構想、研究、需求、架構與 Story |
| `/build` | `$wk-build` | 實作、修改與測試 |
| `/verify` | `$wk-verify` | 審查、測試、驗收與回顧 |
| `/project` | `$wk-project` | 專案規則、自訂設定與進度 |

工作台另提供「開始明確變更」「繼續既有工作」「查看進度與下一步」三個快捷操作。原生 `$bmad-help`、`$bmad-build` 等能力仍可使用；`/goal`、`/plan` 是工作台標籤，複製時使用 `$wk-*`，避免和 Codex 內建命令混淆。

Build 預設使用一般模式。Build Auto 只有明確選用、同步子代理已開啟，且實際 App Server sandbox 的本機 Git 提交探測通過後才啟用。它會先建立本機 Commit；GitLab 綁定任務的 Push、開卡、Wiki／報告發布及建立 Draft MR，仍由 Host 在人工確認實際成果後執行。

預設設定位於 `_bmad/config.toml`：專案名稱取安裝根目錄名稱，溝通與文件使用繁體中文，知識來源為 `wiki/`，規劃及實作產出放在 `_bmad-output/`。本機覆寫可放在 `_bmad/config.user.toml` 或 `_bmad/custom/`。

若目標根目錄已有外部 `_bmad/` runtime 或 BMAD Skill，安裝器會保留原內容，將 `bmadMode` 設為 `external`，並略過整個內建 BMAD 元件，其他工具與輕量入口仍會安裝。單獨存在 `_bmad-output/` 不會觸發略過。外部模式不宣告內建 `bmad-workflow`／`bmad-entrypoints` 驗證能力；工作台逐入口核對實際存在的原生 Skills 後才啟用。使用 `status` 查看目前模式與能力。

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

## Commit 準備與 MR 前檢查

Group 與 Repository profiles 均包含 CommitReviewer 0.1.0。使用 `$commit-reviewer` 準備已暫存變更的 Commit 草稿，或檢查 MR 前的主線同步、線性歷史、Issue 編號與他人異動。報告位於受檢 Repo 的 `review-reports/`，草稿由開發者手動複製。Commit 模式不連網；MR 模式只精確 Fetch 選定目標。模型沿用目前 Codex 設定。
