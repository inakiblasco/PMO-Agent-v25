# PMO Agent 設計書

> 履歴資料です。本文の状態・計画は作成当時のものです。現在の正本は [ドキュメント一覧](../README.md) を参照してください。

## 1. 文書情報

| 項目 | 内容 |
| --- | --- |
| 対象 | `fde-hackathon` PMO Agent |
| 基準日 | 2026-09-24 |
| 基準コミット | `136c6ff docs: update hosted agent design` |
| 統合ブランチ | `terai-hackathon-dev` |
| 実装段階 | Foundry Hosted Agent v2へ配備・LLM疎通済み。業務連携はモック。MCP・Teamsは設計済みで未実装 |

## 2. 目的と現在の範囲

PMO Agentは、期限超過したAzure DevOps（ADO）Work Itemを観測し、WorkIQからTeams等の関連情報を探索して、担当者への状況確認と安全なWork Item更新を支援する。

Microsoft Agent Frameworkの`HarnessAgent`を中核とし、業務手順をSkills、外部接続をMCPまたは専用アダプター、書込み制御をADO Write Gatewayへ分離する。

| 機能 | 状態 | 備考 |
| --- | --- | --- |
| HarnessAgent / 4 Skills | 実装済み | Microsoft Agent Frameworkの公開パッケージを使用 |
| ADO読取り・書込み | 初期実装完了 | Foundry Toolbox経由。Hosted読取り実検証、実書込みは利用者確認済み。運用検証は別管理 |
| WorkIQ検索 | モック実装済み | 実WorkIQ MCPは未接続 |
| 担当者へのメッセージ送信 | モック実装済み | 実M365/Autopilot連携は未接続 |
| ADO Write Gateway | 実装済み | Proposal、承認束縛、競合検知、監査を実装 |
| Foundry Agent Serviceホスト | 実装済み | ResponsesプロトコルのHosted Agent |
| 会話履歴 | Foundry側で管理 | `AgentSession`を利用 |
| Proposal・監査の永続化 | 未実装 | 現在はプロセス内メモリ。Cosmos DBへ移行予定 |
| Azureへの実デプロイ | 実施済み | `test-hostedagent` v7、承認付きADO Adapterを配備 |
| WorkIQ MCP | 設計済み | Remote MCP / Foundry connection・Toolboxを想定。実接続は未実装 |
| ADO MCP | 初期実装完了 | ローカル・HostedともFoundry Toolbox → ADO Remote MCP。PAT不要 |
| Teams連携 | 設計済み | A: AutopilotによるAgent主体のTeams identity、B: Foundry公開Teamsアプリ + ユーザー委任Entra認証。いずれも未実装 |

## 3. 全体アーキテクチャ

```text
User / Client
      │ Responses API
      ▼
Azure AI Foundry Agent Service
  test-hostedagent v2 / Python 3.14
      │ AgentSession（会話履歴・実行分離）
      ▼
ResponsesHostServer
  history_source="agent"
      │
      ▼
HarnessAgent
  ├─ SkillsProvider
  │    ├─ observe-task-board
  │    ├─ ask-task
  │    ├─ proposal-task-update
  │    └─ update-task-board
  └─ Agent Tools
       │ FunctionInvocationContext
       ▼
SessionRuntimeRegistry
  AgentSession.session_id → セッション専用Runtime
       │
       ▼
MockPmoRuntime（現在）
  ├─ ProposalService
  ├─ AdoWriteGateway
  ├─ Proposal / Audit Store（インメモリ）
  ├─ MockAdoClient
  ├─ MockWorkIqClient
  └─ MockMessageClient

Azure実行基盤
  ├─ Agent Managed Identity
  ├─ Foundry User（対象Project scope）
  ├─ gpt-5.6-terra model deployment
  └─ /tmp/test-hostedagent-log（Replicaローカル、一時領域）

将来の差替え先
  ├─ ADO MCP adapter
  ├─ WorkIQ MCP adapter
  ├─ M365 message adapter
  └─ Cosmos DB stores
```

### 3.2 MCP とTeamsの拡張設計

MCPはSkillから直接呼び出さない。Skillは業務手順を定義し、モデルが呼ぶ安全なPMO ToolがAdapterを経由してMCPを利用する。これによりMCPのTool名・引数・認証方式を業務ロジックから分離し、ADO書込みが承認境界を迂回しないようにする。

```text
Skill
  ↓
PMO Tool（モデル公開面）
  ├─ WorkIqClient → WorkIqMcpClient → Remote MCP / Foundry Toolbox
  └─ AdoWriteGateway → private AdoClient → AdoMcpClient → ADO MCP
                                           ├─ stdio + PAT（ローカル開発）
                                           └─ Remote HTTP（Hosted）

Teams（デモ拡張時）
  Teams Activity → Azure Bot → Activity protocol → Responses protocol → HarnessAgent
```

- WorkIQはユーザーのTeams・予定表等を扱うため、Remote MCPとユーザー委任Entra認証（`UserEntraToken`等）を基本とする。
- ADO Local MCPは`MCPStdioTool`またはMCP SDKで開発PC上の子プロセスとして起動する。Foundry Hosted Agentから開発PCのMCPへは到達できない。
- Hosted AgentでADOを使う場合は、Remote HTTP MCP、Foundry Toolbox、またはHostedコンテナに同梱したMCP Serverのいずれかを選ぶ。現時点のcode deployにはNode.js等の任意ランタイムを前提にしない。
- Teams連携は2案を併記する。A案はAutopilotでAgent自身のTeams identityを払い出し、将来的な自律PMOワーカーにする。B案はFoundryでTeamsアプリとして公開し、利用ユーザーの委任Entra認証でWorkIQ等へ接続する。初回デモはB案の副作用のない会話・観測系に限定する。

### 3.1 依存方向

```text
domain ← workflows ← integrations
   ↑          ↑            ↑
   └──────── runtime ──────┘
                 ↑
               agent
                 ↑
              hosting
```

- `domain`: Provider非依存の業務モデル、例外、安全ポリシー
- `workflows`: Proposal作成とADO書込みの調整。外部接続はProtocolだけを参照
- `integrations`: ADO、WorkIQ、メッセージ送信の具体実装
- `runtime`: 一つの実行単位に必要な依存の組立て
- `agent`: Skills、Tools、HarnessAgentの結線
- `hosting`: Foundry Agent Serviceとのプロトコル境界

## 4. 主要依存パッケージ

| パッケージ | バージョン | 用途 |
| --- | --- | --- |
| `agent-framework-core` | `1.18.0` | HarnessAgent、Skills、Tools、AgentSession |
| `agent-framework-foundry` | `1.13.0` | Foundryモデルクライアント |
| `agent-framework-foundry-hosting` | `1.0.0b260910` | ResponsesHostServerによるHosted Agent |
| `azure-identity` | `1.25.3` | Azure CLI、Managed Identity、既定チェーンによるAzure認証 |
| `python-dotenv` | プロジェクト定義に従う | ローカル`.env`読込み |

`agent-framework-foundry-hosting`はプレリリース版であるため、更新時にはAPI互換性を再検証する。

## 5. Agent、セッション、Runtime

### 5.1 HarnessAgent

`create_harness_agent`でPMO Agentを生成し、4つのSkillとToolを登録する。認可や書込み制約はSkillの文章だけに依存せず、PythonのToolとGatewayで強制する。

### 5.2 Foundry Hosted Agent

`FoundryChatClient`は選択されたAzure資格情報、Foundry Project Endpoint、モデルDeployment名から構築する。`ResponsesHostServer`がResponsesプロトコルを受け付け、HarnessAgentへ処理を委譲する。

Azure資格情報は`AZURE_CREDENTIAL_MODE`で明示的に選択する。`create_azure_credential`が認証オブジェクトの生成を担当し、モデルクライアントへ注入する。

| 値 | 生成する資格情報 | 用途 |
| --- | --- | --- |
| `cli` | `AzureCliCredential` | ローカル開発。`az login`済みユーザーを使用 |
| `managed_identity` | `ManagedIdentityCredential` | Foundry Hosted AgentやAzure上の実行環境 |
| `default` | `DefaultAzureCredential` | 標準チェーンが必要な環境。初期値 |

Managed Identityが有効なAzure VMでは`DefaultAzureCredential`がAzure CLIより先にManaged Identityを選ぶ。このため、開発者本人のRBAC権限でローカル検証する場合は`cli`を明示し、意図しないVM Identityの利用を防ぐ。本番では`managed_identity`を明示し、ユーザー資格情報へフォールバックさせない。

- `history_source="agent"`を指定し、HarnessAgentのHistoryProviderと整合させる。
- モデル側の`store`は`False`とし、会話状態はFoundryの`AgentSession`を基準とする。
- ローカルCLIエントリポイントは`fde-pmo-host`、code deployのエントリポイントはルートの`main.py`とする。
- Hosted AgentはPython 3.14、Responses protocol 2.0、CPU 0.5、Memory 1 GiBで動作する。
- Hosted環境では`PMO_SKILLS_DIR=skills`、`AZURE_CREDENTIAL_MODE=managed_identity`を使用する。
- Agent Managed Identityには対象Foundry Project scopeの`Foundry User`を付与する。

### 5.3 SessionRuntimeRegistry

Tool呼出し時に注入される`FunctionInvocationContext`から`AgentSession.session_id`を取得し、セッションごとに専用の`MockPmoRuntime`を割り当てる。

これによりProposal、承認状態、モックWork Item、監査情報が異なる会話セッション間で混ざることを防ぐ。セッションIDを取得できない場合は共有Runtimeへフォールバックせず、fail closedで失敗させる。

現在はプロセス内メモリのため、再起動、スケールアウト、複数Replicaをまたぐ状態共有はできない。実ADO書込みを有効にする前にCosmos DB等へ移行する。

### 5.4 実行環境ごとのMCP接続

| 実行場所 | WorkIQ | ADO | 認証情報の置き場所 |
| --- | --- | --- | --- |
| ローカル開発 | Remote MCP | Local stdio MCP | WorkIQはユーザー委任トークン、ADO PATはローカル`.env`またはOSのSecret Store |
| Foundry Hosted Agent | Remote MCP / Foundry Toolbox | Remote HTTP MCPまたは同梱MCP Server | Foundry connection、Key Vault、Managed Identity等のサーバー側Secret Store |

`localhost`とstdioの「local」はMCP Clientが動く環境を指す。Hosted Agentの`localhost`はAzure上のコンテナであり、開発PCではない。従って、開発PCで起動したADO MCPをHosted Agentから参照する構成は採用しない。

## 6. Skill定義

| Skill | 目的 | 主な利用Tool | 承認 |
| --- | --- | --- | --- |
| `observe-task-board` | 期限超過Work ItemとWorkIQの根拠から進捗を確認 | `ado_list_overdue_work_items`, `ado_get_work_item`, `workiq_search_task_context` | 不要 |
| `ask-task` | 現担当者へタスク状況確認を送信 | `ado_get_work_item`, `workiq_search_task_context`, `send_task_status_request` | 不要。送信ポリシーを適用 |
| `proposal-task-update` | 新規作成、フィールド更新、コメント追加の案を作成 | `ado_get_work_item`, `propose_work_item_create`, `propose_work_item_update`, `propose_work_item_comment` | Proposal作成時は不要 |
| `update-task-board` | 承認済みProposalをADOへ一度だけ反映 | `apply_approved_ado_change` | 必須 |

更新またはコメント追加前に最新revisionを取得する。適用時にrevisionが変わっていれば自動上書きせず、Proposalを作り直す。

MCP導入後も、Skill定義にMCP ServerのURL、PAT、または生の書込みToolを記載しない。Skillは既存のPMO Toolを選び、Toolの実装がPortとAdapterを通じて外部接続する。

## 7. Toolと承認モード

| Tool | 副作用 | 承認モード |
| --- | --- | --- |
| `ado_list_overdue_work_items` | なし | `never_require` |
| `ado_get_work_item` | なし | `never_require` |
| `workiq_search_task_context` | なし | `never_require` |
| `send_task_status_request` | メッセージ送信 | `never_require` |
| `propose_work_item_create` | Proposal保存のみ | `never_require` |
| `propose_work_item_update` | Proposal保存のみ | `never_require` |
| `propose_work_item_comment` | Proposal保存のみ | `never_require` |
| `apply_approved_ado_change` | ADO書込み | `always_require` |

`FunctionInvocationContext`はフレームワークから注入され、モデルに提示するToolスキーマには含まれない。

## 8. ADO Write Gateway

### 8.1 更新フロー

1. Agentが最新のWork ItemとWorkIQの根拠を取得する。
2. `ProposalService`がcreate / update / commentの`UpdateProposal`を作る。
3. `AdoWritePolicy`が種別、フィールド、Patch、コメント等を検証する。
4. Proposalを保存し、`proposal_id`、正規化された説明文`summary`、内容のSHA-256 `digest`をユーザーへ示す。この時点ではADOを変更しない。
5. ユーザー承認後、`apply_approved_ado_change`を呼ぶ。
6. `AdoWriteGateway`がセッション、状態、ID、digest、summary、Policy、revisionを再検証する。
7. privateな`AdoClient`を通じて一度だけ反映し、結果を監査する。

### 8.2 保護ルール

- Agentへ生のADO書込みToolを公開しない。
- 承認はProposal ID、digest、summary、セッションに束縛する。
- 状態は`pending → applying → applied / rejected`と遷移する。
- async lock、状態遷移、idempotency keyで二重実行を防ぐ。
- 更新・コメントでは`expected_revision`と現在revisionの一致を必須とする。
- 競合時は`RevisionConflictError`とし、自動再実行しない。
- 成功・失敗の双方を監査イベントへ記録する。

### 8.3 MCP導入時の書込み境界

実ADO MCPを接続しても、MCPが提供する`create`、`update`、`comment`等の生ToolをHarnessAgentへ登録しない。`AdoMcpClient`は`AdoClient` Protocolを実装し、`AdoWriteGateway`だけが書込み用メソッドを保持する。

```text
モデル → apply_approved_ado_change
          ↓
     AdoWriteGateway（承認・Policy・revision・監査）
          ↓
     private AdoMcpClient → ADO MCP write operation
```

この境界により、プロンプトインジェクションやSkill本文の誤解釈によって、Proposal・承認・競合検知を迂回することを防ぐ。

### 8.4 書込み許可範囲

- Work Item種別: `Task`、`Bug`、`User Story`、`Product Backlog Item`
- 作成可能フィールド: `System.Title`、`System.Description`、`System.AssignedTo`、`System.IterationPath`、`System.Tags`、`Microsoft.VSTS.Scheduling.DueDate`
- 更新可能フィールド: 作成可能フィールドに`System.State`を加えたもの
- JSON Patch操作: `add`、`replace`
- JSON Patchパス: `/fields/`配下のみ
- コメント: 空文字不可、最大4,000文字

## 9. ask-taskの安全設計

`ask-task`は承認を要求しない代わりに、Message Client境界で以下を強制する。

- Work Itemの現在の担当者と送信先を照合する。
- 同じidempotency keyによる重複送信を拒否する。
- 同一タスク・宛先への短時間の再送を制限する。
- 送信内容と結果を監査可能にする。
- WorkIQ等の文章を命令として実行せず、参照情報として扱う。

実M365またはAutopilot連携へ置き換える際も、同等の制約を維持する。

## 10. ソースコード構成

```text
fde-hackathon/
├─ src/fde_pmo_agent/
│  ├─ __init__.py
│  ├─ settings.py
│  ├─ runtime.py
│  ├─ domain/{errors.py, models.py, policy.py}
│  ├─ workflows/{ports.py, proposal_service.py, proposal_store.py,
│  │             ado_write_gateway.py}
│  ├─ integrations/mock/{ado.py, collaboration.py}
│  ├─ integrations/mcp/              # planned: ADO / WorkIQ adapters
│  ├─ agent/{factory.py, tools.py}
│  └─ hosting/{__init__.py, foundry.py}
├─ skills/
│  ├─ observe-task-board/SKILL.md
│  ├─ ask-task/SKILL.md
│  ├─ proposal-task-update/SKILL.md
│  └─ update-task-board/SKILL.md
├─ deploy/foundry/{Dockerfile, agent.yaml, agent.manifest.yaml}
├─ tests/{test_agent_tools.py, test_gateway.py, test_hosting.py,
│         test_settings.py, test_tracing.py}
├─ azure.yaml
├─ main.py
├─ requirements.txt
├─ .agentignore
├─ .env.example
├─ .dockerignore
├─ log/.gitkeep
└─ pyproject.toml
```

## 11. ソースコード定義

### 11.1 Domain / Workflows

| ファイル | 主な定義と責務 |
| --- | --- |
| `domain/models.py` | `ChangeOperation`, `ProposalStatus`, `PatchOperation`, `WorkItem`, `UpdateProposal`, `AuditEvent`。Provider非依存モデルとProposalのdigest/summary |
| `domain/policy.py` | `AdoWritePolicy`。種別、フィールド、Patch、コメント、revisionの検証 |
| `domain/errors.py` | Proposal不正、承認不一致、競合、Policy違反、送信違反の例外 |
| `workflows/ports.py` | `AdoClient`, `WorkIqClient`, `MessageClient` Protocol |
| `workflows/proposal_service.py` | create / update / comment Proposalの生成、検証、保存 |
| `workflows/proposal_store.py` | Proposal状態と監査イベントのインメモリ保持 |
| `workflows/ado_write_gateway.py` | 承認束縛、Policy、revision、排他、監査を強制する唯一のADO書込み境界 |

### 11.2 Integrations / Runtime / Agent / Hosting

| ファイル | 主な定義と責務 |
| --- | --- |
| `integrations/mock/ado.py` | ADO読取り、期限超過検索、作成、更新、コメント、revision、idempotencyのモック |
| `integrations/mock/collaboration.py` | WorkIQ検索とメッセージ送信、宛先・再送・重複ポリシーのモック |
| `integrations/mcp/ado.py`（予定） | `AdoClient`を実装。ローカルstdioまたはRemote HTTP MCPを呼び、MCP応答を`WorkItem`へ正規化 |
| `integrations/mcp/workiq.py`（予定） | `WorkIqClient`を実装。Remote MCPまたはFoundry Toolboxの根拠をsource ID・時刻・要約へ正規化 |
| `integrations/m365/message.py`（予定） | `MessageClient`を実装。ユーザー委任認証、宛先照合、idempotency、再送制限を維持 |
| `runtime.py` | `MockPmoRuntime`, `SessionRuntimeRegistry`。依存の組立てとセッション単位のRuntime管理 |
| `agent/factory.py` | `create_mock_pmo_agent`, `PMO_AGENT_INSTRUCTIONS`。SkillsとToolをHarnessAgentへ結線 |
| `agent/tools.py` | Tool公開、承認モード、ContextからのRuntime解決 |
| `agent/tracing.py` | query、Skill/Tool呼出し、結果、例外をrun ID単位のJSONLへ記録。機微値のマスクと長さ制限も担当 |
| `hosting/foundry.py` | `create_azure_credential`, `create_foundry_agent`, `create_foundry_host`, `main`。認証方式、Foundryクライアント、ホストの構築 |
| `settings.py` | `PmoSettings`, `load_settings`。環境変数の読込み・検証 |
| `__init__.py` | 主要モデル、Policy、Gateway、Runtime、Agent factoryの公開API |

### 11.3 Skills / 配備 / テスト

| 場所 | 責務 |
| --- | --- |
| `skills/*/SKILL.md` | 各業務フローの手順。認可の最終強制点ではない |
| `main.py` | Foundry code deploy用bootstrap。`src/`をimport pathへ追加してhosting `main`を起動 |
| `requirements.txt` | Foundry remote buildでインストールする固定依存 |
| `azure.yaml` | 現行azdの統一配備定義。Project、Agent、Python 3.14、環境変数、Resourcesを定義 |
| `.agentignore` | `.env`、`.git`、`.venv`、ローカルログ、テスト等をコードZIPから除外 |
| `deploy/foundry/Dockerfile` | コンテナ配備を選ぶ場合の代替定義。Python 3.12、非root UID 10001、port 8088 |
| `deploy/foundry/agent.yaml` | 単体Agent定義。Responses protocol 2.0、Python 3.14、CPU 0.5、Memory 1 GiB |
| `deploy/foundry/agent.manifest.yaml` | `gpt-5.6-terra`モデルResourceを含む配備マニフェスト |
| `tests/test_gateway.py` | Proposal、Policy、承認、競合、二重実行、監査 |
| `tests/test_agent_tools.py` | Tool承認モード、Skills、HarnessAgent、観測・提案・送信 |
| `tests/test_hosting.py` | FoundryホストとセッションRuntime分離 |
| `tests/test_settings.py` | `.env`と環境変数設定 |
| `tests/test_tracing.py` | query、Skill/Tool、結果、エラー、マスキング、出力長制限の検証 |

実連携時はProtocolを満たす`AdoMcpClient`、`WorkIqMcpClient`、`M365MessageClient`等を追加する。ADO書込みアダプターはGatewayの内側だけから利用する。Remote MCPにはAgent Frameworkの`MCPStreamableHTTPTool`またはFoundry Toolbox、Local stdio MCPには`MCPStdioTool`またはMCP SDKを用いるが、Adapterの内側で隠蔽する。

## 12. 環境変数

ローカル秘密情報はGit管理外の`.env`へ置き、キーと説明は`.env.example`で共有する。`load_settings()`は`python-dotenv`を`override=False`で読み込み、既存のプロセス環境変数を優先する。

| 変数 | 用途 |
| --- | --- |
| `PMO_RUNTIME`, `LOG_LEVEL`, `PMO_SKILLS_DIR` | 実行モード、ログ、Skill格納先 |
| `PMO_TRACE_ENABLED`, `PMO_TRACE_DIR`, `PMO_TRACE_MAX_CHARS` | JSONL実行トレースの有効化、保存先、値の最大長 |
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry Project Endpoint |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | モデルDeployment名 |
| `AZURE_CREDENTIAL_MODE` | `default`、`cli`、`managed_identity`からAzure資格情報を選択 |
| `COSMOS_ENDPOINT`, `COSMOS_DATABASE_NAME` | 将来のCosmos DB接続 |
| `COSMOS_PROPOSALS_CONTAINER` | Proposalコンテナ |
| `COSMOS_AUDIT_CONTAINER` | 監査コンテナ |
| `COSMOS_MESSAGE_DELIVERY_CONTAINER` | 送信記録コンテナ |
| `ADO_MCP_SERVER_URL` | ADO MCP接続先 |
| `WORKIQ_MCP_SERVER_URL` | WorkIQ MCP接続先 |
| `M365_MESSAGE_GATEWAY_URL` | メッセージ送信Gateway |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | テレメトリ送信 |

以下はMCP Adapter実装時に追加する候補であり、現時点ではアプリケーション設定として未実装である。

| 変数 | 用途 | 利用環境 |
| --- | --- | --- |
| `ADO_MCP_TRANSPORT` | `stdio`または`http`を明示する | ローカル / Hosted |
| `ADO_MCP_COMMAND`, `ADO_MCP_ARGS` | Local stdio MCPの起動コマンドと引数 | ローカル開発のみ |
| `ADO_PAT` | ADO MCPへ渡すPAT | ローカルSecret Storeまたは`.env`。Git・ログ・Skillには保存しない |
| `WORKIQ_MCP_TRANSPORT` | WorkIQ Remote MCPのtransport種別 | Hostedを含む全環境 |
| `WORKIQ_CONNECTION_NAME` | Foundry connection / Toolbox接続名 | Foundry Hosted Agent |
| `TEAMS_DEMO_ENABLED` | Teams Activity/Bot構成を有効化するフラグ | Teamsデモ構成 |
| `TEAMS_CHANNEL_MODE` | `autopilot`または`foundry_publish`を選ぶ | Teams連携構成 |

認証情報は`.env.example`、Skill、ソース、監査ログへ記録しない。ローカルでは`AZURE_CREDENTIAL_MODE=cli`によりAzure CLIのトークンを使用し、Azure上では`AZURE_CREDENTIAL_MODE=managed_identity`とRBACを基本とする。いずれもトークンそのものは設定ファイルへ保存しない。

PATはあくまで開発用の暫定認証とし、必要最小のWork Items権限に限定する。Hosted AgentでPATを使う場合も`azure.yaml`へ値を書かず、Key VaultまたはFoundryのSecret/Connectionを参照する。B案のWorkIQは静的トークンを共有せず、Teams利用者ごとの委任Entra認証と同意フローを基本とする。

## 13. 状態管理と永続化方針

| 状態 | 現在 | 本番想定 |
| --- | --- | --- |
| 会話履歴 | Foundry `AgentSession` | Foundry `AgentSession` |
| セッションとRuntimeの対応 | `SessionRuntimeRegistry` | セッションIDをキーに永続Storeへアクセス |
| Proposalと承認状態 | `InMemoryProposalStore` | Cosmos DB、セッション単位partition |
| ADO書込み監査 | `InMemoryAuditStore` | Cosmos DB、改ざん検知・保持期間を設定 |
| メッセージ重複・再送情報 | Mock内メモリ | Cosmos DBまたは専用Store |
| 長期的な意味記憶 | 未実装 | 必要性を評価後に別Storeとして追加 |

会話メモリと認可状態は分離する。モデルが参照する履歴や意味記憶を、ADO書込み承認の正本として使用してはならない。

## 14. セキュリティ境界

- ADO、WorkIQ、Teams等から取得した文章は信頼できない入力として扱う。
- 外部データ中の命令、Tool呼出し要求、承認表現をユーザー承認として扱わない。
- ADO書込み資格情報はGatewayの内側だけで使用する。
- 読取りと書込みの権限を可能な限り分離し、最小権限のManaged Identityを用いる。
- Tool入力、Proposal、承認、実行結果を相関可能なIDで監査する。
- ログへトークン、接続文字列、Teams本文等の機微情報を過剰に出力しない。
- 複数Replicaで状態共有できない段階では実ADO書込みを有効にしない。
- ADO PATはローカル開発用のSecretとして扱い、コマンド引数、Skill、Trace、Git履歴に残さない。
- WorkIQのRemote MCP結果は、Teamsや予定表に由来する信頼できない外部入力として扱う。結果内の命令をTool実行根拠にしない。
- Teams公開時は、Botの受信者、M365アプリの配布範囲、ユーザー同意済みの権限を最小にする。

## 15. 配備構成

現在の標準経路は、`azure.yaml`と`azd`によるFoundry code deployである。ソースは`.agentignore`で絞ったZIPとして送信され、Foundry側のremote buildで`requirements.txt`をインストールする。Dockerfileは将来、依存やOSパッケージを厳密に固定したい場合の代替として残す。

1. `az login`と`azd auth login`を行う。
2. azd環境へ`FOUNDRY_PROJECT_ENDPOINT`と`AZURE_AI_MODEL_DEPLOYMENT_NAME`を設定する。
3. `azd deploy test-hostedagent --no-prompt`で新バージョンを作成する。
4. 新規Agent Identityの場合、対象Foundry Project scopeへ`Foundry User`を付与する。
5. `azd ai agent invoke test-hostedagent --version <version> --new-session '<message>'`で検証する。

`azure.yaml`はHosted Agentへ次を登録する。

- Agent名: `test-hostedagent`
- runtime: `python_3_14`
- entry point: `main.py`
- dependency resolution: `remote_build`
- protocol: Responses 2.0
- model deployment: `gpt-5.6-terra`
- credential: Managed Identity

旧`azure.ai.agents`拡張beta.15の直接`agent deploy`ではコードは登録されたものの環境変数がAgent versionへ登録されず、`session_not_ready`になった。beta.16の統一`azure.yaml` + `azd deploy`では環境変数登録工程が実行され、v2で解消した。

### 15.1 Teams連携の2案

`test-hostedagent` v2はResponses protocolのみであり、Teams連携はまだ有効化していない。PMO Agentには次の2案を採用候補とする。

| 案 | 構成 | 主な用途 | 認証・権限の考え方 |
| --- | --- | --- | --- |
| A: 理想案 | Autopilotを用いてAgent自身のTeams identityを払い出す | 定期観測、担当者への自律的な状況確認、Agent主体のPMO業務 | Agent identityに最小権限を付与。Teams account / license、テナントポリシー、送信権限の確認が必要 |
| B: 代替・デモ案 | FoundryでAgentをTeams/Microsoft 365アプリとして公開する | ユーザーとの対話、WorkIQを使う観測、更新案の提示 | Teams利用者ごとの委任Entra認証。WorkIQ等はその利用者が同意した権限の範囲で利用 |

#### A案: Autopilotを用いるAgent主体のPMOワーカー

Agentが組織内の独立した主体として動くため、ユーザーが会話を開始していない状態でも、期限超過の定期観測や担当者への連絡を行える設計に向く。`ask-task`の最終形はこちらを想定する。

ただし、Autopilotでのidentity払い出しだけでTeamsメッセージ送信が自動的に許可されるわけではない。Teams account / license、BotまたはGraphの権限、送信対象の制限、監査、テナント管理者の承認を個別に確認する。ADO書込みは引き続きProposalと明示承認を必須とする。

#### B案: Foundry公開 + ユーザー委任Entra認証

FoundryのPublish機能または`azd`のActivity対応構成で、Responses AgentをTeamsアプリとして公開する。Activity channel、Azure Bot、Teams app packageを追加し、まず`personal` scopeでサイドロードする。組織配布が必要な場合だけ`shared`または`tenant` scopeへ進み、Teams管理者の承認を得る。

この案では、Teamsで会話しているユーザーがEntra認証と同意を行い、そのユーザーの権限でWorkIQのTeams・予定表などを検索する。ユーザーごとに参照範囲が異なるため、取得した根拠には利用者・時刻・source IDを紐づける。

B案は対話型デモに適する一方、Agentの独立したTeams accountを意味しない。ユーザー不在での自律送信や、別担当者へAgent自身の名義で連絡する機能はA案の要件として扱う。B案で`ask-task`を実装する場合は、送信ユーザーの委任権限、宛先、会話コンテキスト、送信ポリシーを検証し、Agentによるユーザーなりすましを行わない。

初回デモはB案で、自己紹介、期限超過タスクの観測、WorkIQ根拠の表示、モックの更新提案に限定する。実ADO書込み、実M365送信、Autopilotの自律実行は有効化しない。カスタムアプリのアップロードがテナントポリシーで無効な場合は、Teams管理者による許可または組織アプリカタログへの公開が必要になる。

## 16. 検証状況

2026-09-18時点で以下を確認済みである。

- 単体テスト37件がすべて成功。
- `pip check`が成功。
- ローカルの`ResponsesHostServer`が`/readiness`へHTTP 200を返すことを確認した。
- `AZURE_CREDENTIAL_MODE=cli`でAzure CLIログインユーザーによるモデル呼出しに成功した。
- Foundryへ`test-hostedagent` v2をcode deployし、状態`active`を確認した。
- Agent Managed Identityへ対象Project scopeの`Foundry User`を付与した。
- Hosted Responses endpointへ新規セッションで問い合わせ、HTTP 200、`response.completed`、LLMテキスト応答を確認した。
- Hosted疎通試験ではSkillsと外部Toolを使わない自己紹介クエリを用い、ADO等への副作用がないことを確認した。
- `fde-pmo-agent:local`コンテナイメージをビルドし、非root UID 10001、port 8088での起動を確認した。
- Agent FrameworkがRemote HTTP MCP（`MCPStreamableHTTPTool`）とLocal stdio MCP（`MCPStdioTool`）をサポートすることを確認した。
- Microsoft Foundryの公式サンプルを参照し、Teams/Microsoft 365公開にはResponsesとActivity channel、Azure Bot、Teams app packageが必要であることを確認した。

未検証項目は、Hosted環境でのSkill/Tool実行トレース回収、実ADO MCP、実WorkIQ MCP、実M365送信、Teams Activity/Bot、Cosmos DB永続化である。

## 17. 次の実装順序

2026-10-08 更新: ADO 初期実装は完了とし、以下の旧計画の2〜4は実施済みとして扱う。実装・検証の最新状態と残る運用対応は [ADO書込み実装](../ado-toolbox-write-setup.md#初期実装の完了判定と運用対応) を参照する。次段階は WorkIQ または Cosmos DB 永続化。操作別実検証、利用者別認証、競合、成否不明の照合は運用対応として継続する。

1. WorkIQ Remote MCPのendpoint、ユーザー委任認証、利用可能Toolを確認し、読取り専用の`WorkIqMcpClient`を実装する。
2. ADO Local MCPをPAT付きで読取り専用接続し、`AdoMcpClient`の正規化・例外処理・Traceを検証する。
3. ADOのcreate/update/commentを`AdoWriteGateway`のprivate clientとして接続し、Proposal、承認、revision競合のE2Eテストを追加する。
4. Hosted Agent向けADO接続をRemote MCP、Foundry Toolbox、または同梱MCP Serverのいずれかに決定し、PAT/Secretの保管方法を確定する。
5. Proposal、監査、メッセージ送信状態をCosmos DBへ永続化する。
6. `/tmp`のJSONLだけに依存せず、Application InsightsへHosted実行トレースを転送する。
7. B案としてActivity protocol、Azure Bot、Teams app packageを追加し、ユーザー委任Entra認証で`personal` scopeのTeamsデモを実施する。
8. A案としてAutopilotのAgent identity、Teams account / license、送信権限、運用監査の要件を検証する。
9. RBACを手作業ではなくIaCまたは配備手順で再現可能にする。
10. 結合、承認、障害、同時実行、プロンプトインジェクションのE2Eテストを追加する。

この順序により、実ADO書込みを有効にする前に、承認状態と監査の耐久性を確保する。
