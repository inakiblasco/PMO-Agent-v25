# ADO Remote MCP 読み取り接続の設定・検証

実装は `PMO Tool → AdoMcpClient → Foundry Toolbox → ADO Remote MCP` の順に接続する。既存8個の PMO Tool を維持し、生の MCP Tool はモデルへ公開しない。本書は読み取りの手順。現在の配備は ADO_MODE=toolbox で承認付き書込みも利用する。WorkIQ は機能ブランチで接続済み、実メッセージ送信は無効。最新状態は [実装状況](IMPLEMENTATION_STATUS.md)。Proposal / Audit はインメモリ。

## 必要な環境設定

今回の Azure 環境には Connection `AzureDevOpsMCPServer` と Toolbox `pmo-agent-tools` v2 が既にある。新規作成せず、下記の endpoint と server label を使用する。

1. Entra tenant に紐づく ADO Organization と検証用 Project を用意する。
2. Foundry の Azure DevOps MCP カタログ接続で `https://mcp.dev.azure.com/{organization}` に接続する。下流認証はカタログが要求する Entra OAuth / 同意フローを使う。PAT は公式 Remote MCP に利用できない。
3. Connection を参照する Toolbox を用意する。読み取り用 `wit_work_item` と `wit_query` のみに絞り、対応可能なら `X-MCP-Readonly: true` を設定する。Toolbox の server label を確認する。
4. 保存済みクエリを使う場合は、`System.TeamProject = @project` を条件に含む flat なクエリの参照権限を確認する。未指定なら Adapter の固定 Project-scoped WIQL を使う。
5. Hosted Agent Identity の Foundry Project / Toolbox 権限と、下流ユーザーの ADO 権限を別々に確認する。

## アプリケーション設定

```dotenv
PMO_RUNTIME=foundry
AZURE_CREDENTIAL_MODE=managed_identity
FOUNDRY_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<foundry-project>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<deployment>
ADO_MODE=toolbox_readonly
ADO_TOOLBOX_ENDPOINT=https://aifoundry-techenablement-fde-hackathon-dev-jpe-001.services.ai.azure.com/api/projects/FDE-hackathon/toolboxes/pmo-agent-tools/versions/2/mcp?api-version=v1
ADO_PROJECT=PMO-Agent
ADO_QUERY_ID=
ADO_DUE_DATE_FIELD=Custom.DueDate
ADO_COMPLETED_STATES=Done
ADO_SERVER_LABEL=AzureDevOpsMCPServer
PMO_TRACE_ENABLED=false
```

実 Project の期限フィールドと完了状態を確認して設定する。接続トークンを環境変数やソースに固定しない。`.env` はローカル設定用であり、Hosted には自動転送されない。上記は書込みを無効にして読むための設定例。現在の配備定義は ADO_MODE=toolbox と書込み用 v3 endpoint も設定し、独自 trace を無効化している。期限フィールド `Custom.DueDate` と完了状態 `Done` を確認して配備定義に追加済み。保存済みクエリは任意で、未指定なら固定 WIQL を使う。

FoundryToolbox の bearer 認証と Hosted call ID 転送を利用する。各 PMO 読取りの開始時にそのリクエスト内で MCP transport / session を開き、完了時に閉じる。共有した MCP session に以前のユーザーコンテキストを残さないための初期実装であり、接続の往復コストが発生する。

### ローカルでの接続確認

ローカルでは `AZURE_CREDENTIAL_MODE=azd` で既存 `azd auth login` の利用者認証を明示的に使える。`cli` は `az` の認証を使う。この作業環境の `az` は VM identity のため、実接続で成功した `azd` 認証を使用する。Hosted では `managed_identity` にする。

最初の確認には endpoint / Project / server label / credential mode を設定する。クエリ・期限・完了状態は、単一 Work Item 取得には不要。期限超過一覧を呼ぶ場合は、期限フィールドと完了状態を必須として通信前に検証する。保存済みクエリ ID は任意。

```bash
.venv/bin/python -m fde_pmo_agent.integrations.mcp.check_ado
.venv/bin/python -m fde_pmo_agent.integrations.mcp.check_ado --work-item-id <known-id>
.venv/bin/python -m fde_pmo_agent.integrations.mcp.check_ado --board
```

最初は tools/list と必要な引数の存在を確認する。`--work-item-id` は Adapter 経由で実取得と Project/ID/revision の検証を行う。`--board` は保存済みクエリ、未指定なら固定 WIQL から期限超過一覧を取得する。出力は接続結果・ID・revision・件数に限定し、タスク本文や担当者を出さない。通常の単体テストからは実行されない明示的な接続確認 CLI である。

## 呼び出し契約と制限

実装が使用する契約は以下。Remote MCP の更新で変わる可能性があるため、対象 Toolbox の `tools/list` で照合する。

- `<label>___wit_work_item`：`action=get`, `project`, `id`。
- `<label>___wit_query`：`action=get_results`, `project`, `id`, `top=200`。
- `<label>___wit_work_item`：`action=get_batch`, `project`, `ids`, `fields`。

区切り `___` と引数は 2026-10-08 に実 Toolbox の tools/list で確認した。`responseType` は公開 schema にないため送らない。

保存済みクエリまたは固定 WIQL の `workItems` を get_batch で展開し、Project、ID、revision、期限、state を検証する。返却数が上限200件に達した場合、継続トークンや打切り表示がある場合は、全件取得と見なさずエラーにする。ページングは初期実装では未対応。閾値未満でもサーバーが打切り情報を隠す場合の完全性は保証できないため、実サーバーの契約とクエリ結果件数を検証する。

通常の読み取り失敗はサニタイズした例外として返し、モックへフォールバックしない。同意エラー `-32006` は同意が必要な旨を返す。初期実装はアプリ内で OAuth 同意 URL を表示・再開する UI を持たないため、Foundry の接続画面で同意を完了して再試行する。エラー応答の正確なネスト形式は実接続で確認が必要。

実 ADO モードでは内容を含む独自 JSONL trace を生成しない。SDK / Hosting 側の telemetry 収集設定は別途確認し、機密情報・メッセージ本文収集を無効にする。

## 検証履歴

以下の「未検証」「今回」は各versionの検証時点を示す。現在の判定は [実装状況](IMPLEMENTATION_STATUS.md) を参照する。

単体テストは外部通信を使わず、既存 PMO Tool からの Runtime 結線、レスポンス検証、期限超過判定、禁止操作、SDK auth と異なる call ID の転送を確認する。

実接続では、権限の異なる二人のユーザーから intended client/channel を使い、既知の Work Item の取得と期限超過一覧を実行する。ADO UI / クエリ結果と一致し、別 Project の Work Item を拒否し、各ユーザーの参照範囲が守られることを確認する。ローカルの `az login` だけでは Hosted のユーザー委任検証を代替できない。

2026-10-08 に既存 v2 Toolbox の接続・tools/list、PMO-Agent の WIQL 読取り、Work Item get / get_batch、実レスポンスの正規化が成功した。保存済みクエリは今回の利用者に見える一覧に存在しなかったため、クエリ選定・期限フィールド・完了状態の確認、get_results を含む期限超過一覧の実検証は残る。Hosted 配備と利用者別委任認証も未検証。デプロイ、実書き込み、実送信は行っていない。

修正後の `azd` credential mode と接続確認 CLI の処理を使い、tools/list の契約照合と実 Adapter の `get_work_item` を再検証した。PMO-Agent の Work Item ID 3 / revision 2 を取得し、Project / ID / revision の検証が成功した。通常の単体テストは48件成功。

## Hosted v4 実接続結果（2026-10-08）

`azd deploy test-hostedagent -e fde-hackathon-dev --no-prompt` で v4 を配備した。既存 Foundry の Agent VNet injection を維持して、Responses protocol の新規セッションから `ado_get_work_item(3)` を実行した。

- 戻り値: ID 3 / revision 2 / System.TeamProject PMO-Agent。
- Hosted console: `Function name: ado_get_work_item` と `Function ado_get_work_item succeeded.` を確認。
- 同じ console で既存 Toolbox v2 MCP endpoint への HTTP 200、MCP protocol negotiation を確認。
- 実行 Trace ID: `4d12821828860a0e9291953c644d7497`。
- Hosted 認証は managed identity。今回の呼出しにおける Toolbox 経由の ADO 読取りが成功した。

Harness の初回応答は計画承認を求めたため、同じセッションで読取り計画を承認して実行した。モード切替パラメーターの再試行後に ADO Tool が成功した。読取りにも計画承認が挟まる挙動は今後の UX 改善項目。

起動時にプラットフォームの任意 A365/OpenAI Agents instrumentation が `No module named 'agents'` で警告を出したが、readiness・Responses・ADO Tool 実行は成功した。今回の接続修正に無関係な依存追加はしていない。

期限超過一覧、別利用者の権限差、未同意ユーザーの同意・再開、書込み・送信・WorkIQ は未検証。今回の1利用者での成功を、全ユーザーの委任認証検証完了とは扱わない。

## プレイグラウンドの期限超過一覧への対応

v4 は単一 Work Item 読取り用の設定だったため、期限超過一覧で設定不足エラーが発生した。実 Project の Work Item type 定義から、Task の期限フィールド `Custom.DueDate` と Completed category の状態 `Done` を確認し、配備定義に追加した。

`ADO_QUERY_ID` は任意に変更した。指定があれば従来どおり保存済みクエリを使う。未指定なら Adapter が固定 WIQL `SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project` を実行し、get_batch 後に期限・完了状態を検証する。生の WIQL をモデルへ公開しない。上限200件・不完全結果の拒否は維持する。Custom.DueDate がない Epic / Issue、期限未設定 Task は期限超過判定から除外する。空一覧を全件の正常判定として説明しないよう Agent 指示を追加した。

ローカルの実期限超過一覧は2件の取得に成功。単体テスト50件成功。ADO のクエリ作成や Work Item 更新は実施していない。

修正版を Hosted `test-hostedagent` v5 に配備し、Responses の新規セッションから期限超過一覧を実行した。2件（ID 5, 6）が返り、設定不足エラーが解消した。実行 Trace ID は `4db24b2b30ab32526a8e98c560e33837`。プレイグラウンドでは v5 を選び、新しいセッションで検証する。
