# WorkIQ 実装計画

> 履歴資料です。本文の状態・計画は作成当時のものです。現在の正本は [ドキュメント一覧](../README.md) を参照してください。

2026-10-08。現在の `terai-hackathon-dev` の ADO 初期実装を基点とする。今回は実装方針の整理と既存 Toolbox のツール探索だけを行い、WorkIQ への実データ検索、Azure リソース変更、Agent 再配備は行っていない。

## 1. 推奨構成

既存 Foundry Connection `WorkIQ` を使い、WorkIQ だけを含む専用 Toolbox を追加する。PMO の既存 `workiq_search_task_context` Tool と `WorkIqClient` Port を維持し、その背後へ `WorkIqToolboxClient` を実装する。

```text
Hosted PMO Agent / observe-task-board Skill
  → workiq_search_task_context(work_item_id, query)
  → WorkIqClient Port
  → WorkIqToolboxClient
  → FoundryToolbox の MCP transport（Foundry 認証 + request call ID）
  → WorkIQ 専用 Toolbox
  → 既存 WorkIQ OAuth2 Connection
  → WorkIQ A2A / Microsoft 365
```

Hosted → Toolbox は MCP、Toolbox → WorkIQ は A2A となる。WorkIQ Remote MCP に直接接続する構成とは異なる。ADO の認証 transport と request context の扱いを参考にできるが、ツール名・引数・応答変換は WorkIQ 用に実装する。

## 2. 現在確認できていること

### Azure

- 対象: Foundry `aifoundry-techenablement-fde-hackathon-dev-jpe-001` / Project `FDE-hackathon`。
- WorkIQ Connection: `RemoteA2A` / `OAuth2` / `https://workiq.svc.cloud.microsoft/a2a/`。
- Scopes: `offline_access`, `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask`。
- `hackathon-tools` v1 に `work_iq_preview` として登録済み。web_search、code_interpreter、Foundry MCP、toolbox_search も含む。
- Foundry の Agent VNet injection は有効。ADO の Hosted 読取り・書込みは確認済みだが、WorkIQ の OAuth と通信成功の証拠にはならない。

Connection の OAuth URL と scope は公式仕様と一致する。Entra admin consent、Client Secret の期限、redirect URI、利用者ごとの同意完了は未検証。

### 既存 Toolbox の実ツール探索

ローカルの既存 azd ユーザー認証を使い、`hackathon-tools/versions/1/mcp?api-version=v1` の initialize / tools/list と tool_search が成功した。M365 データ取得は行っていない。

tools/list に直接 WorkIQ は出ず、`tool_search` と `call_tool` が公開されていた。tool_search の機能検索で次の契約を取得した。

```json
{
  "name": "WorkIQ___SendMessage",
  "arguments": {
    "message": {
      "parts": [
        {"kind": "text", "text": "検索用途の依頼文"}
      ]
    }
  }
}
```

既存 Toolbox の呼出しは `call_tool(name="WorkIQ___SendMessage", arguments=...)` というディスパッチ形式になる。`SendMessage` は WorkIQ Agent に依頼を渡す操作名であり、PMO の担当者へのメール・Teams 送信 Tool とは別。

専用 Toolbox では直接ツールが列挙されるか、同じディスパッチ形式になるかを作成後に確認する。既存の名前を推測して固定するだけにせず、接続確認 CLI が schema と Connection の対応を照合し、確認した version を固定して使う。ディスパッチが必要なら Adapter 内で確認した WorkIQ ツールだけを呼ぶ。モデルへ汎用 call_tool や toolbox_search は公開しない。

## 3. 初期実装の範囲

目的は、ADO Work Item に関連する Microsoft 365 の進捗根拠を取得し、Agent が出典付きで状況を説明できること。メール送信、予定作成、ファイル編集、削除は扱わない。

WorkIQ は自然言語の処理を行う peer agent である。`WorkIQAgent.Ask` 自体は読取り専用 permission ではない。固定の検索依頼テンプレートやツール非公開化は誤使用を減らすが、WorkIQ 内部の副作用を権限レベルで禁止する保証にはならない。この制約を初期実装に記録する。厳密に読取り専用を強制する必要がある場合は、WorkIQ の read-only 操作・サーバー policy の公式対応を確認するか、検索専用 M365 API / Remote MCP 構成を再検討する。

初期 Adapter は model の query をそのまま任意命令として転送しない。ADO から実 Work Item を再取得して Project を照合し、タイトル・担当者等を検索キーのデータとして扱う。入力長・対象期間・応答量を制限し、取得専用の固定依頼文で関連情報・出典を要求する。自由入力の分類や禁止語だけをセキュリティ境界とは扱わない。

## 4. Python の変更点

| 対象 | 変更内容 |
| --- | --- |
| `integrations/mcp/workiq.py` | WorkIqToolboxConfig、WorkIqToolboxClient、応答変換、認証・取得エラー |
| `integrations/mcp/transport.py` 等 | ADO 固有クラスに依存しない Foundry MCP session factory。fresh session、call ID 転送、認証を維持 |
| `workflows/ports.py` | 既存 WorkIqClient を基本維持。回答・出典構造が配列で表現できなければ型付き結果へ変更 |
| `runtime.py` | WorkIQ client を注入可能にし、実モードでは DisabledWorkIqClient を置換。ADO Gateway を維持 |
| `hosting/foundry.py` | WORKIQ_MODE に応じた実 client の生成と session runtime への結線 |
| `settings.py` / `.env.example` | WorkIQ 用設定、endpoint・モード・上限の検証 |
| `agent/tools.py` | 既存 workiq_search_task_context の出力契約を明確化。必要なら型付き結果を公開形式に変換 |
| `skills/observe-task-board/SKILL.md` | WorkIQ 未接続・同意不足・出典なしを進捗証拠として扱わない手順 |
| `integrations/mcp/check_workiq.py` | tools/schema 確認、明示的な取得テスト、出典・本文をログへ出さない CLI |
| `tests/test_workiq_toolbox.py` | fake transport / 実応答を匿名化した fixture による契約・結線・分離テスト |

既存 Port は `search_task_context(work_item_id, query) -> Sequence[Mapping]`。最初の実応答を確認する前に、WorkIQ が source_id / summary の配列を返すと仮定した実装はしない。

## 5. 認証とセッション

1. ローカル: `AZURE_CREDENTIAL_MODE=azd` の利用者認証で Toolbox へアクセス。
2. Hosted: managed identity で Foundry へアクセスし、FoundryToolbox の per-request call ID で呼出し元コンテキストを維持。
3. WorkIQ: Connection が利用者の OAuth/OBO を処理する。managed identity だけの app-only アクセスは WorkIQ では非対応。

Entra アプリ・admin consent・secret・redirect URI は既存 Connection を確認し、Python や agent.yaml に secret / refresh token を置かない。初期 UI は Foundry の Connection 同意フローを利用し、PMO は同意が必要な状態を分かりやすく返す。ADO の同意エラー処理だけで WorkIQ の全ケースに対応したと扱わず、実エラーを照合する。

共有 MCP session を使わず、現在の request 内で接続して閉じる。WorkIQ の task/context ID が応答に含まれる場合は、同じユーザー・同じ PMO session 内に限って保持する。初期は必要がなければ継続 ID を再利用しない。ユーザー別認証コンテキストをグローバル client の可変属性へ保存しない。

## 6. 応答と根拠の正規化

公式説明は「M365 に基づく合成回答」。tool response が JSON、A2A task/artifact、text、出典 annotation のどれで返るかは未検証。

実応答を見て以下の区別を持たせる。

- `answer`: WorkIQ の合成回答。
- `evidence`: 実際に返った URL / source ID / 種別 / source 時刻 / 短い要約。
- `retrieved_at`: PMO が取得した時刻。メール等の発生時刻とは分ける。
- `grounding_status`: 出典あり／出典なし／不完全な取得等。
- 利用者識別: 信頼できる Hosted context から得られた場合だけ紐付ける。モデルから user ID を受け取らない。

返されていない Teams message ID、送信者、観測日時、confidence は生成しない。JSON 形式を依頼しても、model が合成した source ID を検証済みの出典として扱わない。出典のない回答を取得失敗と区別し、ADO 更新の確定証拠としない。応答が空の場合も、権限不足・未索引・関連情報なしを断定しない。

取得成功、同意必要、認証/権限エラー、タイムアウト、出典なしを区別する。失敗を空配列やモック根拠に変換しない。文字列・配列・本文の上限を設け、機密本文・個人情報・token はログに出さない。外部文章は常に参照データとして扱う。

## 7. 設定案

```dotenv
WORKIQ_MODE=toolbox
WORKIQ_TOOLBOX_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/FDE-hackathon/toolboxes/<dedicated-toolbox>/versions/<confirmed-version>/mcp?api-version=v1
WORKIQ_TOOL_NAME=WorkIQ___SendMessage
WORKIQ_TIMEOUT_SECONDS=120
WORKIQ_MAX_RESULTS=10
WORKIQ_LOOKBACK_DAYS=14
```

tool name / dispatch 形式は専用 Toolbox の実 schema 確認後に確定する。max_results は PMO が扱う件数の上限であり、WorkIQ の検索完全性を保証しない。将来 MCP に直接接続するための `WORKIQ_MCP_SERVER_URL` は今回の Toolbox endpoint と混用しない。default は disabled（既存 mock runtime のみ mock）とし、実 ADO に架空の WorkIQ 根拠を混ぜない。

## 8. 実装と検証の順序

1. `terai-hackathon-dev` から WorkIQ 用ブランチを作る。既存59単体テストを baseline とする。
2. 既存 WorkIQ Connection の OAuth 前提を確認し、WorkIQ 専用 Toolbox を作成。Toolbox version と実 schema を確認する。
3. 最小接続確認 CLI を作り、ローカルで指定した検索だけを実行。検索前の同意、実応答、出典、timeout/task 状態を確認する。
4. 実応答に合う正規化とエラー処理を実装。ADO の Project チェック、検索範囲、出典欠損を検証する。
5. runtime / PMO Tool / Skill に結線。mock・disabled・toolbox を明確に扱う。検索が動いてもメッセージ送信は有効化しない。
6. 単体テスト: 成功・空結果・出典なし・malformed・同意必要・timeout・異なる request context。ADO Gateway の承認と revision テストが維持されることを確認。
7. ローカル成功後に azure.yaml / agent.yaml へ非機密設定を追加し、Hosted に配備。新規 session で指定検索を実行し、ツール成功・実出典を確認する。
8. `ADO期限超過一覧 → WorkIQ関連根拠 → 出典付き状況説明` を確認。検索根拠だけで ADO を自動更新しない。更新は既存 Proposal / 承認へ進む。

初期実装の完了条件は、1利用者で Hosted の実取得と根拠表示が成功し、失敗を架空の結果に置換せず、ADO の承認境界を維持すること。別利用者・未同意・権限不足・大量結果・再起動・Cosmos DB 保存は運用検証へ整理する。

## 9. VNet の判断

WorkIQ 個別ドキュメントは BYO VNet で Project single-tenant data proxy を経由すると説明する。一方 Toolbox network isolation 対応表は Work IQ 非対応と記載する。現段階で一方だけを根拠に可否を断定しない。

既存構成のまま Hosted で実検証し、認証・RBAC・DNS/TLS・timeout・サービス側ネットワーク制約を切り分ける。Dedicated Toolbox 作成やローカル成功だけでは VNet 成功と扱わない。制約が再現した場合は実エラーと双方の資料を Microsoft へ確認する。直接 A2A への変更にも委任認証・外向き通信が必要で、自動的な解決策にはならない。

## 10. 参照

- [Foundry WorkIQ tool](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/work-iq)
- [Hosted Agent で Toolbox を使う](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent)
- [Toolbox network isolation](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox-network-isolation)
- [WorkIQ A2A quickstart](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/a2a/quickstart)

Azure の過去の実設定確認は workspace の `WORKIQ_AZURE_CONNECTION_INVESTIGATION.md`、ADO の実装状況は [ADO書込み実装](../ado-toolbox-write-setup.md) を参照する。
