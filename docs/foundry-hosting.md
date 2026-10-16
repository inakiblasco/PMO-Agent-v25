# Foundry Hosted Agent 設計・運用

## 対象と最新状態

HarnessAgentをResponsesHostServerで公開するFoundry Hosted Agent。最新の配備はtest-hostedagent v14で、ADO読取り・承認付き書込みとWorkIQを利用する。配備の確認範囲・Gitとの差は [実装状況](IMPLEMENTATION_STATUS.md) を参照する。

## 実行構成

```text
Foundry Responses endpoint
        │
        ▼
main.py                         code deploy entry point
        │
        ▼
fde_pmo_agent.hosting.foundry
        │
        ├─ ManagedIdentityCredential
        ├─ FoundryChatClient ── gpt-5.6-terra
        └─ ResponsesHostServer :8088
                    │
                    ▼
                HarnessAgent
                    │
          Skills + approved Tools
```

主な配備値は次のとおり。

| 項目 | 値 |
| --- | --- |
| Agent名 | `test-hostedagent` |
| Runtime | `python_3_14` |
| Protocol | Responses 2.0 |
| Entry point | `main.py` |
| Dependency resolution | `remote_build` |
| CPU / Memory | 0.5 / 1 GiB |
| Model deployment | `gpt-5.6-terra` |
| Azure認証 | Managed Identity |

## 配備ファイル

- `azure.yaml`: 現行azdの統一配備定義。通常のデプロイではこれを正本とする。
- `main.py`: code deploy用bootstrap。`src/`をimport pathへ加えてHosted Serverを起動する。
- `requirements.txt`: Foundry remote build用の固定依存。
- `.agentignore`: `.env`、Git情報、仮想環境、ローカルログ、テスト等をアップロードから除外する。
- `deploy/foundry/agent.yaml`: 単体Agent定義。スキーマ確認や代替フローに使用する。
- `deploy/foundry/agent.manifest.yaml`: 再利用可能なAgent manifest。
- `deploy/foundry/Dockerfile`: コンテナイメージ配備へ切り替える場合の代替。

## 環境変数と認証

`azure.yaml`からHosted Agentへ以下を注入する。

```text
PMO_RUNTIME=foundry
PMO_SKILLS_DIR=skills
PMO_TRACE_ENABLED=false
PMO_TRACE_DIR=/tmp/test-hostedagent-log
AZURE_CREDENTIAL_MODE=managed_identity
FOUNDRY_PROJECT_ENDPOINT=<Foundry project endpoint>
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-5.6-terra
```

AgentのManaged Identityには、対象Foundry Project scopeで`Foundry User`を割り当てる。これによりProject参照とモデル推論に必要なデータアクションを与える。資格情報やAPIキーをソース、`.env.example`、`azure.yaml`へ保存しない。

ローカル実行時は`.env`で`AZURE_CREDENTIAL_MODE=azd`を指定し、`azd auth login`済みユーザーを使用する。cliはAzure CLI認証を選ぶ場合の代替。

## ローカル起動とreadiness

```bash
cd /home/terai/work_terai/fde-hackathon
source .venv/bin/activate
pip install -e .
fde-pmo-host
```

別ターミナルで確認する。

```bash
curl -i http://127.0.0.1:8088/readiness
```

正常時はHTTP 200と`{"status":"healthy"}`を返す。

## Foundryへのデプロイ

統一`azure.yaml`を使用する。拡張の版は実環境で確認し、以下のbeta.15/16の記載は過去の障害記録として参照する。

```bash
az login
azd auth login
azd deploy test-hostedagent --no-prompt
```

新しいAgent Identityを作成した場合は、対象Project scopeへ`Foundry User`を付与する。ロール割り当ては現在手動であり、今後IaC化する。

## 動作確認

```bash
source .venv/bin/activate
azd ai agent show test-hostedagent
azd ai agent invoke test-hostedagent \
  --version <deployed-version> \
  --new-session \
  'Skillsや外部Toolは呼び出さず、PMO Agentとして一文で自己紹介してください。'
```

確認ポイントはHTTP 200、`response.completed`、`agent_reference.name=test-hostedagent`、期待したテキスト応答である。書込み検証ではないため、最初のスモークテストではADO更新Toolを呼ばせない。

## トレース

mockモードでtraceを有効にした場合、`log/`等へrun単位のJSONLを出力する。実ADOモードではこの独自traceを生成せず、現在のHosted設定も無効。記録対象はquery、Skill/Tool呼出しと結果、最終応答、例外であり、機微値をマスクし長大な値を切り詰める。

Hostedの`/tmp`はReplicaローカルの一時領域であり、再起動やスケールアウトをまたぐ監査保管には使えない。Application Insights等への転送は未実装である。

## 過去の配備障害と現在の制約

- `session_not_ready`は、Hostedコンテナの`/readiness`が期限内にHTTP 200を返していないことを示す。
- 旧`azure.ai.agents` beta.15の直接`agent deploy`では環境変数がAgent versionへ登録されず、バージョン1が`session_not_ready`になった。
- beta.16の`azure.yaml` + `azd deploy`では環境変数登録工程が実行され、バージョン2で解消した。
- ローカル`/readiness`が成功しHostedだけ失敗する場合は、Agent versionの`environment_variables`、runtime、entry point、アップロードZIP、Managed IdentityのRBACを順に確認する。
- 現在のProposal・監査はプロセスメモリ。承認付きADO対話操作は有効だが、再起動・複数Replicaの耐久性を保証しない。本番の耐久実行にはCosmos DB永続化・照合が必要。
