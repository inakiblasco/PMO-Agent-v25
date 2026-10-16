# PMO Agent

Azure DevOps の期限超過タスクを観測し、WorkIQ で Microsoft 365 の関連情報を調べ、状況確認と承認付きの Work Item 更新を支援する Foundry Hosted Agent。

## 設計・計画・現在の状態

- [基本設計](docs/PMO_AGENT_DESIGN.md): 構成、責務、認証、承認・状態管理の境界。
- [今後の実装計画](docs/IMPLEMENTATION_PLAN.md): 次の作業、優先順位、完了条件。
- [実装状況と課題](docs/IMPLEMENTATION_STATUS.md): 実装済み、確認済み、未検証を区別した一覧。
- [ドキュメント一覧](docs/README.md): 接続・配備手順、WorkIQ 詳細設計、開発ルール、履歴資料。

2026-10-09 時点では ADO 初期実装が統合済み、WorkIQ 実装は `feat/pmo-workiq-toolbox` の `9337145` にある。Hosted の直近配備は `test-hostedagent` v14。ブランチごとの差は実装状況を参照する。

## ローカル開発

Python 3.11 以上を使用する。現在の Hosted runtime は Python 3.14。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python -m unittest discover -s tests -q
```

実接続には [環境変数](docs/pmo-agent-environment.md)、[ADO 読取り](docs/ado-toolbox-read-setup.md)、[WorkIQ 接続](docs/workiq-toolbox-setup.md) を確認する。実 ADO 書込みは個別承認の Gateway を経由する。実メール送信、Cosmos DB 永続化、Teams 公開は未実装。

開発・レビューは [AGENTS.md](AGENTS.md)、[CONTRIBUTING.md](CONTRIBUTING.md)、[ブランチポリシー](docs/branch-policy.md) に従う。
