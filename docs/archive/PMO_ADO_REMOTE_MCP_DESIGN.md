# PMO Agent：Foundry Hosted Agent から ADO Remote MCP への接続設計

> 履歴資料です。本文の状態・計画は作成当時のものです。現在の正本は [ドキュメント一覧](../README.md) を参照してください。

## 1. 文書情報と目的

| 項目 | 内容 |
| --- | --- |
| 作成日 | 2026-10-07 |
| 実装ベース | `terai-hackathon-dev`（調査時点：`f2cae26`） |
| 上位設計 | [PMO_AGENT_DESIGN.md](PMO_AGENT_DESIGN.md) |
| 現状 | Hosted Agent・PMO Tool・Gateway は実装済み。ADO・WorkIQ・送信はモック |
| 対象 | Hosted Agent から公式 Azure DevOps Remote MCP を利用する接続と段階的な実装 |
| 前提 | `feat/pmo-ado-mcp` の実装は再利用を前提としない |

Foundry Hosted Agent の既存 PMO Tool から実 Azure DevOps の Work Item を読み取り、将来は承認済み Proposal の書き込みへ拡張する。本文は実装方針であり、接続・認証・デプロイの完了を示すものではない。

## 2. 採用方針

- Foundry Toolbox を経由して、公式 ADO Remote MCP へ Streamable HTTP で接続する。
- Hosted 実装にローカル stdio MCP や Node.js の同梱を前提としない。
- モデルには既存の PMO Tool だけを公開し、生の MCP Tool は Adapter 内へ隠す。
- 最初に ADO の読み取りを実サービスへ置き換える。実書き込みは永続化と実サービスの整合性保証を確認した後に有効化する。
- WorkIQ、M365 送信、Teams 公開、Autopilot は別段階で実装する。

Toolbox は認証・同意・トークン更新と Hosted の呼び出しコンテキストを扱うために利用する。公式サンプルの `tools=toolbox` をそのまま採用すると生の MCP Tool がモデルへ公開されるため、PMO では Adapter の内部から呼び出す結線を検証する。

## 3. 接続構成と責務

```text
User / Client
  → Foundry Hosted Agent / ResponsesHostServer
  → HarnessAgent / Skills
  → PMO Tool（既存のモデル公開面）
  → SessionRuntimeRegistry / セッション専用 Runtime
  → AdoMcpClient（新規 Adapter）
  → Foundry Toolbox
  → https://mcp.dev.azure.com/{organization}
  → Azure DevOps
```

| 層 | 責務 |
| --- | --- |
| Skills | 観測、確認、提案、承認後の適用という業務手順 |
| PMO Tool | モデル向け入力、承認モード、現在セッションの Runtime 解決 |
| Runtime | モックまたは実 Adapter の組み立て、セッション状態の分離 |
| AdoMcpClient | 許可された MCP 操作の実行、引数変換、Work Item 正規化、例外変換 |
| Toolbox / Project Connection | 下流認証、同意、トークン更新、呼び出しユーザーの解決 |
| AdoWriteGateway | Proposal、承認、Policy、revision、実行状態、監査の強制 |

Skill に MCP URL、資格情報、生の MCP 書き込み操作を記載しない。MCP から取得した文章は外部データとして扱い、その中の指示や承認表現を実行根拠にしない。

## 4. 認証設計

認証は二つの境界に分ける。

| 境界 | 方針 |
| --- | --- |
| Hosted Agent → Toolbox | Agent Identity で認証。Foundry のスコープは `https://ai.azure.com/.default`。必要な Project 権限を確認する |
| Toolbox → ADO Remote MCP | Project Connection に Entra OAuth を設定。初期構成はユーザー委任を候補とし、Foundry カタログが生成する接続設定を確認する |

公式 ADO Remote MCP は Entra ID に紐づく Organization が必要で、PAT はサポートしない。Agent Identity に Foundry の権限を付与しただけでは ADO の参照権限は得られない。

OAuth と `UserEntraToken` は異なる認証方式であり、ADO が要求する方式・audience・scope はカタログ接続と実疎通で確定する。独自に推測した audience や、ローカルの Azure CLI ログインを Hosted の資格情報として利用しない。

ユーザー委任では、現在の Hosted リクエストの `x-agent-foundry-call-id` を Toolbox に伝える必要がある。公式 `FoundryToolbox` の利用を基本とし、Adapter 内からの呼び出しでもコンテキストが維持されることを検証する。call ID やユーザー資格情報を別リクエスト・別ユーザーへ使い回さない。

ユーザー不在の定期観測は将来の要件とする。公式 ADO Remote MCP が Agent Identity によるアプリケーション認証を受け付けるかは未確認であり、対話型の委任接続の成功から自律実行の可否を判断しない。

## 5. 読み取り Adapter

既存の `AdoClient` Protocol の読み取りメソッドに対応する新規 `AdoMcpClient` を実装する。初期段階の書き込みメソッドは明示的に拒否する。

| PMO Tool / メソッド | 実装内容 |
| --- | --- |
| `ado_get_work_item` / `get_work_item` | Work Item を取得し、ID・revision・種別・fields を `WorkItem` へ正規化 |
| `ado_list_overdue_work_items` / `list_overdue_work_items` | 対象 Project 内の期限超過かつ未完了の Work Item を検索して正規化 |

実装前に以下を確認する。

1. Organization / Project、期限フィールド、完了状態、日付とタイムゾーンの意味。
2. Remote MCP の `tools/list` が返す実際の Tool 名、引数、レスポンス。
3. Toolbox の Tool 名プレフィックス。一般に `{server_label}.{tool_name}` となるため、実一覧を正本とする。
4. 一覧の上限とページング。全件を取得できない場合は結果が部分的であることを PMO 側で判別可能にする。
5. 異常応答、権限不足、同意要求、タイムアウト時の例外と再接続方法。

公式資料では `wit_work_item` の `get` / `get_batch`、`wit_query` の `get_results` が読み取り操作として掲載されている。任意 WIQL の `wit_query_by_wiql` は調査時点で Insiders 限定のため、初期構成では保存済み WIQL クエリの利用を優先候補とする。最終的な呼び出し形式は実サーバーで確認する。

サーバー側では `X-MCP-Readonly: true` と Tool の絞り込みを利用する。カタログ接続・Toolbox からヘッダーを設定できるかを確認し、Adapter 側でも許可 Tool・操作を固定する。ヘッダーや Tool フィルターは ADO の認可を代替しない。

## 6. Runtime と Hosted への組み込み

現在の `MockPmoRuntime` と `SessionRuntimeRegistry` はモックを直接生成する。Runtime を Protocol に基づく依存注入に対応させ、設定に応じて ADO Adapter を選択する。

- セッション単位の Proposal・監査状態の分離と、セッション不明時の fail closed を維持する。
- 実 ADO モードの接続失敗時にモックへ自動フォールバックしない。
- 実 ADO を読んだ後の操作がモック Gateway やモック送信で実成功に見えないよう、実書き込み・実送信の未対応状態を明示する。
- 接続開始・終了、トークン更新、アイドル復帰、同時リクエストを考慮する。ユーザー固有の呼び出し状態を共有接続へ固定しない。
- 固定済み Agent Framework / hosting SDK の `FoundryToolbox` 対応と import パスを確認し、必要な依存更新は互換性検証を伴う独立した変更とする。

候補設定は ADO の利用モード、Organization / Project、Toolbox Endpoint / Name、server label、検索クエリ ID、期限フィールド、完了状態、タイムアウト・ページ上限とする。最終的な変数名は実装時に定義する。資格情報は Project Connection に保持し、環境変数やソースへトークンを固定しない。

`azure.yaml` は現行の code deploy を維持し、Toolbox の参照または Endpoint を追加する。新規サービス作成・既存 Agent 名変更はこの設計の必須条件ではない。

## 7. 書き込みへの拡張

```text
モデル → apply_approved_ado_change（承認必須）
  → AdoWriteGateway
  → private AdoMcpClient
  → 書き込み用 Toolbox / Connection
  → ADO Remote MCP
```

実書き込み前に次の条件を満たす。

- Proposal、実行状態、監査を Cosmos DB 等へ永続化し、複数プロセスでも原子的に実行権を取得する。
- Proposal ID・digest・summary・セッションへの承認束縛を維持する。
- Remote MCP が revision 条件付き更新をどう表現・保証するか確認する。取得後の revision 比較だけでは、比較と更新の間の競合を防げない。
- create / update / comment の重複防止と、結果不明の扱いを定義する。
- 読み取りと書き込みの接続・権限を可能な限り分離し、書き込み Client は Gateway 内にのみ保持する。

現在の Gateway は一般エラー時に Proposal を pending へ戻す。実サービスでは「書き込み成功後に応答が途切れる」場合があるため、結果不明を失敗と同一扱いにして再実行しない。照合・回復方法を設計し、保証できない操作は有効化しない。

Toolbox の `require_approval` は `tools/call` 自体を遮断する認可境界ではない。実書き込みの承認は既存 PMO Tool と Gateway の Python コードで強制する。

## 8. 実装順序と完了条件

| 段階 | 内容 | 完了条件 |
| --- | --- | --- |
| 1 | Foundry カタログで ADO Connection / Toolbox を構成 | 対象 Project の Work Item を読み取れ、認証方式と利用 Tool が確定 |
| 2 | SDK と Adapter 内呼び出しの小規模検証 | 生 Tool をモデルへ公開せず、現在ユーザーのコンテキストで呼び出せる |
| 3 | 読み取り Adapter とテスト | 正規化、期限超過判定、ページング、例外処理、書き込み拒否を検証 |
| 4 | Runtime・設定・Hosted 配備の結線 | 既存 PMO Tool から実 ADO を取得でき、モックへの誤フォールバックがない |
| 5 | Hosted で認証・障害・観測を検証 | ユーザー分離、同意、権限不足、再接続、トレースを確認 |
| 6 | Proposal・監査の永続化 | 再起動・同時実行でも承認状態と実行状態が保持される |
| 7 | Gateway 経由の実書き込み | 明示承認、競合、重複、結果不明の回復を E2E で検証 |

上位設計の第17節はローカル MCP の検証を含む汎用順序である。本計画では Hosted Remote MCP を優先し、実書き込みの有効化は永続化後とする。

最初の実装完了条件は、Hosted Agent の `ado_get_work_item` と `ado_list_overdue_work_items` から実 ADO データを取得できること。実 ADO 書き込みと実メッセージ送信は無効のままとする。

## 9. 主な変更予定箇所と検証

| 場所 | 変更予定 |
| --- | --- |
| `integrations/mcp/ado.py` | 新規 Remote MCP / Toolbox Adapter |
| `runtime.py` | Adapter の依存注入とセッション専用 Runtime |
| `settings.py`, `.env.example` | 非機密設定と検証 |
| `hosting/foundry.py` | Toolbox のライフサイクルと Hosted コンテキストの結線 |
| `agent/tools.py`, `agent/factory.py` | 既存 PMO Tool を維持して Runtime の型・注入を対応 |
| `azure.yaml`, 配備定義 | Toolbox 参照・設定。秘密情報は埋め込まない |
| `tests/` | Adapter、Runtime 分離、Hosted 接続、設定検証 |

単体テストは外部ネットワークを使わず、レスポンス契約・正規化・例外・禁止操作を検証する。実接続テストには `integration` マーカーを付け、通常の単体テストから分離する。

Hosted E2E は intended client/channel から実施し、権限の異なる二人のユーザーで、それぞれの参照範囲だけが返ることを確認する。疎通成功だけでユーザー委任の成功とは判断しない。

トレースには run / session / call の相関、操作名、所要時間、結果区分を記録する。資格情報や Work Item 本文等の機密情報を過剰に収集しない。ログ転送の認証・権限は MCP 接続とは別に検証する。

## 10. 公式資料と未確定事項

2026-10-07 に確認した公式資料：

- [Azure DevOps Remote MCP Server](https://learn.microsoft.com/en-us/azure/devops/mcp-server/remote-mcp-server?view=azure-devops)
- [ADO Remote MCP トラブルシューティング](https://learn.microsoft.com/en-us/azure/devops/mcp-server/remote-mcp-server-troubleshooting?view=azure-devops)
- [Foundry Toolbox](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/toolbox)
- [Hosted Agent で Toolbox を利用する](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent)
- [Toolbox 認証](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/tool-authentication)

未確定事項は、対象環境のカタログ接続方式、Adapter 内での SDK 呼び出し方法、ADO Tool の実スキーマ、検索方式、ヘッダー設定の可否、Agent Identity による自律実行の対応、実書き込みの整合性保証である。これらは実装第1・第2段階および書き込み前の検証で確定する。
