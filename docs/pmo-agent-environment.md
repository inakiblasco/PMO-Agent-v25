# PMO Agent 環境変数

## ローカル設定

プロジェクト直下の [`.env.example`](../.env.example) を `.env` としてコピーし、必要な値を設定する。

```bash
cp .env.example .env
```

`.env` は Git の管理対象外である。トークン、接続文字列、ユーザー情報を `.env.example`、Skill、ソースコード、ログへ保存してはならない。

[`fde_pmo_agent.settings.load_settings`](../src/fde_pmo_agent/settings.py) は、ローカルでは `python-dotenv` を使って `.env` を読み込む。Foundry上では、既に注入されている環境変数を優先し、`.env` で上書きしない。`PMO_RUNTIME=foundry` の場合は、`FOUNDRY_PROJECT_ENDPOINT` と `AZURE_AI_MODEL_DEPLOYMENT_NAME` を必須として検証する。

## 変数一覧

Cosmos、M365 Gateway、Application Insightsの値はSettingsで読み取るが、実Store・実送信・ログ転送にはまだ結線されていない。値を指定するだけでは機能が有効にならない。WorkIQ固有設定は本書と同じ機能ブランチにあり、統合ブランチへは未反映。

| 変数 | 用途 | 必須になる条件 |
| --- | --- | --- |
| `PMO_RUNTIME` | `mock` または `foundry` を選ぶ | 常に。初期値は `mock` |
| `LOG_LEVEL` | アプリケーションログの出力レベル | 任意 |
| `PMO_SKILLS_DIR` | Skill配置先。ローカル既定はソースツリー、code deployでは`skills` | Hosted Agent |
| `PMO_TRACE_ENABLED` | JSONL実行トレースの有効化 | 任意。初期値は`true` |
| `PMO_TRACE_DIR` | JSONLトレース保存先 | 任意。ローカルは`log`、Hostedは`/tmp/test-hostedagent-log` |
| `PMO_TRACE_MAX_CHARS` | トレース値の最大文字数 | 任意。初期値は`20000` |
| `FOUNDRY_PROJECT_ENDPOINT` | Azure AI Foundry project endpoint | Foundry Hosted Agent / Foundry Chat Client |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | 使用するチャットモデルのデプロイ名 | Foundry Hosted Agent / Foundry Chat Client |
| `AZURE_CREDENTIAL_MODE` | `default`、`cli`、`azd`、`managed_identity` からAzure認証方式を選ぶ | 任意。初期値は `default` |
| `COSMOS_ENDPOINT` | Azure Cosmos DB account endpoint | 永続StoreまたはCosmos Memory |
| `COSMOS_DATABASE_NAME` | PMO Agent用Cosmos database名 | Cosmosを使う場合 |
| `COSMOS_PROPOSALS_CONTAINER` | Proposal・状態遷移の保存先 | 永続Proposal Store |
| `COSMOS_AUDIT_CONTAINER` | 監査イベントの保存先 | 監査を永続化する場合 |
| `COSMOS_MESSAGE_DELIVERY_CONTAINER` | メッセージの重複・送信間隔の保存先 | 実メッセージ送信 |
| `ADO_MCP_SERVER_URL` | 将来用。現Adapterは使用しない | 読取りだけある予約設定 |
| `WORKIQ_MCP_SERVER_URL` | 将来用。現WorkIQはToolbox endpointを使用 | 読取りだけある予約設定 |
| `M365_MESSAGE_GATEWAY_URL` | Autopilot / Microsoft 365メッセージGateway endpoint | 実送信adapter |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Application Insightsへのテレメトリー送信 | 監視を有効にする場合 |

## 認証情報

ローカルでAzure CLIのログインユーザーを使う場合は `AZURE_CREDENTIAL_MODE=cli`、Foundry上では `AZURE_CREDENTIAL_MODE=managed_identity` を指定する。`default` は `DefaultAzureCredential` の標準チェーンを使用する。本番ではManaged IdentityとRBACを優先する。Cosmosキー、MCPアクセストークン、Application Insights接続文字列など、キー形式の値が避けられない場合だけ、Foundryのシークレット設定またはKey Vault参照を使う。`.env` はローカル開発だけに限定する。

## 実 Adapter の設定

| 変数 | 用途・必須条件 |
| --- | --- |
| ADO_MODE | mock / toolbox_readonly / toolbox。書込みを使う場合はtoolbox |
| ADO_TOOLBOX_ENDPOINT | 実ADO読取り用MCP endpoint |
| ADO_WRITE_TOOLBOX_ENDPOINT | toolbox時に必須。書込み用v3 |
| ADO_PROJECT | 対象Project。現在PMO-Agent |
| ADO_SERVER_LABEL | schemaのラベル。現在AzureDevOpsMCPServer |
| ADO_QUERY_ID | 保存済みクエリ。任意、空なら固定Project WIQL |
| ADO_DUE_DATE_FIELD | 期限超過判定で必須。現在Custom.DueDate |
| ADO_COMPLETED_STATES | 期限超過判定で必須。現在Done |
| WORKIQ_MODE | disabled / toolbox。default disabled。実ADOを必須とする |
| WORKIQ_TOOLBOX_ENDPOINT | toolbox時に必須。現在pmo-workiq-tools v1 |

Tool名・WorkIQ期間・件数・timeout・回答上限はWorkIqToolboxConfigの初期値。WORKIQ_TIMEOUT_SECONDS等の環境変数はまだ実装されていない。

## 現在の配備と認証

ローカル実接続はAZURE_CREDENTIAL_MODE=azd、Hostedはmanaged_identity。PMO_RUNTIME=mockはデモ・テスト用。実配備はADO_MODE=toolbox、WORKIQ_MODE=toolbox、PMO_TRACE_ENABLED=false。配備定義の正本はazure.yamlで、versionとGit差は [実装状況](IMPLEMENTATION_STATUS.md) を参照する。

手順は [ADO読取り](ado-toolbox-read-setup.md)、[ADO書込み](ado-toolbox-write-setup.md)、[WorkIQ接続](workiq-toolbox-setup.md)、[Hosted配備](foundry-hosting.md)。
