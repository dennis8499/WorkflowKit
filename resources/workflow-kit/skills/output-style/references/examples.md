# Output Style examples

These examples show presentation choices, not new workflow or artifact schemas.

## Routine completion — concise

Request: 「修正分頁後告訴我結果。」

Response after actual verification:

> 已修正換頁後保留前一頁資料的問題，相關三個測試通過。
> 修改位於 `src/orders.ts`；尚未執行瀏覽器驗證。

Include an actual outstanding action when one is required. Preserve the full
verification record where the development workflow requires it.

## Explain a failure — explanatory

Request: 「為什麼重試付款會產生兩筆訂單？」

> 建單入口沒有以付款識別碼去重，同一個成功通知重送時會再次建立訂單。
> 目前的檢查只在前端停用按鈕，因此無法攔下 webhook 重送。應在後端以付款
> 識別碼建立唯一約束，並讓重試回傳已存在的訂單。

Attach the inspected source evidence and distinguish this explanation from an
actually reproduced failure. Explain alternatives only when they affect the fix.

## Complete the work while teaching — learning

Request: 「教我理解這段去重邏輯，並幫我完成修正。」

Explain the duplicate request, the identity used for deduplication, and why an
atomic uniqueness check handles concurrent requests. Then implement the requested
change, run the required checks and report the result. A small worked example can
show two requests receiving the same order ID. An exercise is optional follow-up;
the user does not need to complete it before the authorized fix proceeds.

## Review examples — author the draft, then render the report

The following scenarios illustrate wording in existing draft fields and chat
replies. They are not complete reports or ready-to-publish findings. Replace the
illustrative IDs, paths and facts with the actual review's fixed evidence. Follow
the selected Skill's own draft schema, validate with `check`, and publish with
`finish`; the helper supplies all required sections, finding blocks and evidence
metadata. Replace each `〈報告連結〉` below with the clickable local report path
returned by `finish`. Keep the generated report unchanged after publication.

Both reports retain these five H2 sections, in order: `審查結論`, `問題總攬`,
`問題詳情（工程師參考）`, `範圍與限制`, `技術審查紀錄（工程師參考）`.
The plain summary and title help PMs and QA understand the issue; precise
engineering fields, complete citations and editable confirmations remain in
their existing places. `P0`–`P3`, status values and report judgments keep their
workflow-defined meanings.

### 1. Merge finding — formal report and concise delivery

Request: 「審查 Orders 的 main 與 feature/payment，產出 Merge Report。」

Evidence in this example: the changed handler inserts an order on every payment
notification; the fixed schema has no uniqueness check for the payment ID. The
reviewer judged this conditional defect P1. It was inferred from code, not run.

Earlier wording: 「缺少冪等性保護，重試導致重複副作用。」

Draft prose using the same facts:

- Summary: 「暫不建議合併。付款成功通知重送時，系統可能為同一筆付款建立兩筆
  訂單，讓客服與出貨人員重複處理。請先讓相同付款只建立一筆訂單，再驗證重送
  與同時送達的情境。」
- Title: 「付款成功通知重送時，可能重複建立訂單」
- Impact: 「同一筆付款可能產生多筆訂單，客服與出貨人員可能重複處理同一筆交易。」
- Operation scenario: 「付款平台因未收到回應而再次傳送同一筆成功通知時，後端
  會再次建立訂單。這是依程式推導的情境，尚未實際執行。」
- Expected / actual: 「相同付款只對應一筆訂單。」／「每收到一次成功通知就新增
  一筆訂單，沒有先檢查該付款是否已處理。」
- Recommendation: 「在後端保證相同付款只建單一次，並驗證同一通知重送及兩次
  通知同時送達時，均只留下同一筆訂單。」
- Engineering explanation / fix: 「處理 `payment_id` 的建單入口每次都執行新增，
  資料表也沒有唯一約束。相同請求重送仍只執行一次的保護（idempotency）應由
  資料庫唯一約束與重複鍵處理共同保證，重試回傳既有訂單。」

Attach the inspected handler and schema as fixed evidence, with their actual
Repo, path, line range, source, full ref and content hash. Keep the report's
code-derived marker; the example does not establish an execution result.

Progress:

> 已確認建單入口與資料表都沒有擋下同一筆付款重複建單；這是依程式推導的問題。
> 接下來會核對出貨端如何使用訂單，確認影響範圍後再完成報告。

Delivery after the required review and publication finish:

> 暫不建議合併：付款通知重送時可能重複建立訂單，已列為 1 項 P1 問題。
> 請先修正並驗證重送情境；本次未實際重現。〈報告連結〉

### 2. Release dependency — a concrete deployment checklist

Request: 「檢查 Billing 的 main 與 release/billing-v2，產出上版報告。」

Evidence in this example: the change starts using `BILLING_URL`; the previous
version did not. The code and configuration definition were reviewed, but no
target-environment deployment record or connectivity result was supplied. There
is no confirmed direct code blocker. This is a pending deployment dependency.

Earlier wording: 「新增外部服務依賴，需核對環境配置與連通性。」

Draft prose:

- Summary: 「已檢查的程式變更未發現可確認的直接上版阻擋，但還不能確認部署
  已準備好。新版開始透過 `BILLING_URL` 連到帳務服務，目標環境的設定與連線
  尚待確認；請部署人員完成核對並留下驗證紀錄。」
- Dependency description: 「新版需要連到帳務服務；若目標環境未提供這個設定，
  使用帳務功能時可能無法連到服務。這是待確認條件，尚未證實目標環境有問題。」
- Recommendation for completing the generated checklist: 「請確認目標環境已提供 `BILLING_URL`，且應用程式可從
  執行環境連到指定帳務服務。完成後附部署設定紀錄與連線測試結果，省略實際
  設定值及認證內容。」
- Next action: 「由部署人員確認設定與連線，將核對人、日期及驗證證據填入人工
  Checklist，再依團隊流程決定是否上版。」

The helper generates the checklist questions; put these concrete instructions in
the dependency's existing description/recommendation and next steps. Keep its ID
and type, code/configuration citations, coverage records and editable checklist
markers. Each checklist row stays `待確認`; filling it does not recompute the
report's generated assessment.

Delivery:

> 已檢查範圍未發現可確認的直接上版阻擋，但帳務服務的環境設定與連線仍待核對。
> 請部署人員補上驗證紀錄，再決定是否上版。〈報告連結〉

### 3. No confirmed defects — keep the pending condition visible

Request: 「沒有找到程式問題，可以直接說能上版嗎？」

Facts: all required code coverage is complete and no direct code blocker was
confirmed, but the added database migration has no target-environment completion
record. The migration dependency and its checklist remain pending.

Earlier wording: 「靜態檢查通過。」

Draft summary:

> 本次已檢查的程式變更未發現可確認的直接上版阻擋；資料庫更新是否已在目標
> 環境完成仍待確認。請部署人員提供更新紀錄及資料表檢查結果，再決定是否上版。

Deployment recommendation accompanying the generated checklist:

> 請確認本次版本需要的資料庫更新已在目標環境完成，並附 migration 執行紀錄
> 與更新後資料表的檢查結果；省略連線資訊與敏感資料。

Chat answer:

> 目前還不能確認可以上版。程式檢查沒有發現直接阻擋，但仍缺少目標環境的
> 資料庫更新紀錄；請先完成這項核對。〈報告連結〉

Keep the generated assessment, dependency record, pending count and manual fields.
Zero confirmed defects does not establish that the environment is ready.

### 4. Missing evidence — explain what is still unknown

Request: 「審查到哪裡？是不是沒有問題？」

Facts: the entry Repo changes an API response field. The required caller's fixed
source could not be read, so the effect on that caller is unresolved. This is an
evidence gap, not a confirmed defect or completed review.

Earlier wording: 「consumer coverage unresolved，待補 supporting evidence。」

Draft summary / limitation:

> 審查尚未完成。這次變更調整了 API 回傳欄位，但還沒有讀到使用這個欄位的
> 呼叫端程式，無法判斷它是否仍能正常處理回應。請先取得該呼叫端的固定版本
> 原始碼並完成核對，再給出合併建議。

Progress:

> 已看完 API 的欄位變更，還缺呼叫端的固定版本原始碼，目前無法確認相容性。
> 取得資料後，會繼續核對呼叫端是否能處理新的回應。

Retain the gap, unresolved coverage and actual failed-read record. Resume the
same frozen review using its native workflow. If it cannot publish yet, report
that state without inventing a report link or marking the review complete; when
the workflow permits an incomplete report, deliver its actual link and limitation.

### 5. Explicit concise style — shorten prose, preserve the work

Request: 「`$output-style style=concise`，用前面的付款問題產出 Merge Report。」

Use exactly the facts, severity and verification state from scenario 1. Author
shorter prose in each existing field, then render the complete report:

- Summary: 「暫不建議合併：付款通知重送時可能重複建單，影響客服與出貨處理。
  請先保證同一筆付款只建單一次，再驗證重送及同時送達的情境。」
- Title: 「付款通知重送時可能重複建單」
- Impact: 「同一筆付款可能產生多筆訂單，造成客服與出貨重複處理。」
- Operation scenario: 「付款平台重送同一筆成功通知，後端再次新增訂單。」
- Expected / actual: 「相同付款只留一筆訂單。」／「每次通知都新增訂單。」
- Recommendation: 「用付款識別碼保證只建單一次，驗證重送與同時送達只產生一筆。」
- Engineering explanation / fix: 「`payment_id` 沒有唯一約束，建單入口也未處理
  重複通知。新增資料庫唯一約束，重複鍵時回傳既有訂單。」

Keep the P1 finding, its ID, affected scope, full evidence, code-derived marker,
all five sections and any confirmations or coverage limitations. Concise changes
the prose density, not the report schema, result JSON or completion gates.

Delivery:

> 暫不建議合併：付款通知重送時可能重複建單，請先修正並驗證。
> 本次為程式推導，未實際重現。〈報告連結〉

Request: 「`$output-style style=explanatory`，解釋剛才的審查結論。」

> 同一筆付款的成功通知可能送達多次，但目前每次收到通知都建立新訂單。
> 前端停用按鈕無法攔住付款平台重送，因此需要在後端與資料庫保證只建單一次。
> 這個結論來自固定版本的程式與資料表檢查，尚未實際執行重送測試。

An explanation after publication describes the existing conclusion; it does not
rewrite the generated assessment or turn a pending environment condition into proof.
