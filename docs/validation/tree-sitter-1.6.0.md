# Tree-sitter 本機交付驗證紀錄

日期：2026-11-08。WorkflowKit 1.6.0、GitlabWorkSpace 0.44.0；僅本機交付，尚未公開發布。

實作已完成，最終受影響回歸 29 項、四個 Python ABI 合計 84 項通過。正式預設維持 **off**：真實模型的品質與效益尚未驗收，完整測試另有一項 Wiki 圖表瀏覽器清理失敗。

## 修改與來源身分

只修改 WorkflowKit 與 GitlabWorkSpace。上游 Codebase LLM Wiki、MergeReviewer、ReleaseReviewer、CommitReviewer 工作樹乾淨；原始 ZIP 與 `source-snapshots.json` 的 `sources` 與 HEAD 相同。套件自有來源使用 `--freeze-workspace` 更新，保留上游 pins。

安裝版 overlay 宣告每筆新增與替換的原始及最終雜湊；未宣告覆寫的原生檔案逐 byte 相等。原生證據、報告與發布驗證器維持原樣。Group Wiki 說明合併既有 overlay，Repository profile 有對等增強。

最終引擎：`693acd4b68c4564aedade62436ecf96eb4792b946927e6d00bf50f3b0489e0c6`。綁定完整 helper、grammar、query、版本鎖定與官方 wheel 解壓資產。執行會拒絕未受管檔案，避開額外模組與 bytecode；安裝器也會阻擋未受管內容並保留供修復。VSIX 僅含接線與驗證資訊，未內含 parser 二進位。

## 測試結果

| 驗證 | 結果 |
| --- | --- |
| WorkflowKit 完整 release discovery | 174 項已執行：171 通過、2 skip、1 Wiki 圖表失敗；三組 ID 完整且不重複 |
| 最終套件受影響回歸 | 29 項通過，含四種安裝、真實 1.5.0 升級／重裝／回退、overlay 對等、Git checkout／archive 重建及兩套 Reviewer |
| CPython 3.11.17 / 3.12.15 / 3.13.16 / 3.14.7 | Windows x64 各 21 項實際載入與解析通過，合計 84 項 |
| WorkflowKit build / verify-release / release CI | 通過；release CI 25 項 |
| GitlabWorkSpace 完整 `npm.cmd test` | 接線程式完整驗證通過；unit 1,204 / skip 3，behavior-node 255，issues 29 scenarios / 136 steps，connect 通過 |
| Extension Host / Trust / release tooling | Host 21 通過 / 4 原有 pending；Trust 通過；tooling 42 通過 |
| 更新 VSIX 內建 1.6.0 驗證器後 | 歷史 WorkflowKit 16 項通過；CommitReviewer 舊版狀態斷言修正後重跑通過；重新封裝與驗證通過 |
| 實際最終 ZIP × GWS 接線 | 離線內建 status 驗證器、完整引擎綁定、capabilities、query 篡改拒絕通過 |
| Wiki 原生 scanner → 語法 CLI | SHA / snapshot 保持一致，來源唯讀，無持久索引，仍保留未閱讀與未審查狀態 |

完整 discovery 使用補強前基準套件；最後受管載入與初始化上下文修正，以最終套件重跑 29 項受影響流程與四個 ABI。各次 ZIP / engine SHA 均記錄於機器可讀結果，沒有把不同套件結果混成同一身分。

Reviewer 使用固定 blob 完成行段讀取、髒工作目錄與移動分支驗證、merge-parent、刪除／改名、原生 step / check / finish、重試與恢復；fetch 為 0。所有來源、patch、instructions、必要版本與原生 coverage 義務保持完整。發布測試使用已知常數變更 fixture 的人工草稿，不能代表模型缺陷檢出能力。

解析涵蓋大型多函式檔、同名／overload、partial class、attributes／decorators、建構子／property／區域變數初始化、TSX／JSX、中文、CRLF、UTF-16、CP950、錯誤語法、錯誤 ABI、超限及未受管 bytecode。

## 未通過與啟用條件

既有 `test_prepared_wiki_diagram_resumes_and_publishes_in_a_later_runner_call` 在 browser-check 的程序退出與暫存 profile 清理失敗。獨立以 Chrome 及支援的 Edge 重跑均重現；原生圖表與證據驗證器未修改。原始失敗及重試紀錄隨附。另兩項 skip 是本機帳號無法建立 symlink；reparse attribute 驗證已通過。

[機械量測](../benchmarks/tree-sitter-local.json) 僅計來源 bytes 與記憶體 facts-cache 冷／暖成本，不含模型推理、outline、native framing 或補讀。真實模型的 off／auto 輸入、工具往返、總耗時、漏報／誤報，以及完整 LLM Wiki 成果均尚未配對評估。因此不能宣稱達成 20% 輸入、10% 耗時目標或品質門檻，兩項驗收旗標保持 false。

評估時可在新任務的 helper 程序環境明確設定 `WORKFLOW_KIT_SYNTAX_CONTEXT=auto`；既有 session 保留原計畫與 operation IDs。輸入格式與門檻見 [整合文件](../syntax-context.md#acceptance-evidence)，scorer 不會自動啟用套件。

## 本機檔案

| 檔案 | bytes | SHA-256 |
| --- | ---: | --- |
| `gitlab-workspace-kit-1.6.0.zip` | 35,521,993 | `a00104d22f21d8e7dfc9e7204d7000ac4d073c5b674c5a6244c00a3cc4074fa9` |
| `workflowkit-installer-1.6.0.py` | 5,263,647 | `a6d35bd64ad660360306a159574fe5a052fa22f7d53463630bb575b1c96dc48f` |
| `gitlab-workspace-0.44.0.vsix` | 2,362,831 | `898d897a55de5df140731b7c5e060cf4029388f5ea3822104aca017c0c10819c` |

完整結果：[summary.json](tree-sitter-1.6.0/summary.json)。原始紀錄：[完整測試](tree-sitter-1.6.0/full-tests-0.log)、[最終回歸](tree-sitter-1.6.0/delivery-tests.log)、[實際安裝接線](tree-sitter-1.6.0/installed-binding.json)、[Chrome 重試](tree-sitter-1.6.0/wiki-chrome-retry.log)、[Edge 重試](tree-sitter-1.6.0/wiki-edge-retry.log)。
