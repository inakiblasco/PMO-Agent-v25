# ドキュメント一覧

## 最初に読む3文書

| 文書 | 正本として管理する情報 |
| --- | --- |
| [基本設計](PMO_AGENT_DESIGN.md) | PMO 全体の責務、接続、認可・承認、状態管理 |
| [実装計画](IMPLEMENTATION_PLAN.md) | 今後の優先順位、作業内容、完了条件 |
| [実装状況と課題](IMPLEMENTATION_STATUS.md) | ブランチ・配備、確認済みの証拠、未検証事項 |

設計文書へ配備履歴を積み重ねず、計画へ現在の成功状態を書き込まない。機能・配備変更時は実装状況を更新し、方針・優先順位の変更時は設計・計画を更新する。

## 詳細設計・操作手順

- [WorkIQ 詳細設計と実装](WORKIQ_DESIGN_AND_IMPLEMENTATION.md): A2A 採用理由、MCP 比較、検索応答、標準 OAuth 同意処理。
- [環境変数](pmo-agent-environment.md): 有効な設定と、受け取りだけある未実装設定の区別。
- [Foundry 配備・動作確認](foundry-hosting.md)
- [ADO 読取り接続](ado-toolbox-read-setup.md)
- [ADO 書込み契約と検証](ado-toolbox-write-setup.md)
- [WorkIQ 接続・同意・再実行](workiq-toolbox-setup.md)

## 開発・プロジェクト運営

- [開発ルール](../AGENTS.md)、[貢献手順](../CONTRIBUTING.md)、[ブランチポリシー](branch-policy.md)
- [Issue Template](issue-templates.md)、[Backlog](backlog-management.md)、[ラベル](labels.md)
- [Scrum の責務](scrum-accountabilities.md)、[セレモニー](scrum-ceremonies-agenda.md)
- [GitHub セットアップ](setup.md)、[Azure 学習ガイド](learning/azure-learning-guide.md)

これらは開発・運営に用途があるため保持する。Skills 配下の SKILL.md は Agent が読み込む実行資産であり、一般ドキュメントの重複として移動・削除しない。

## 履歴資料

[archive/](archive/README.md) は旧設計・導入前計画・過去の検証記録。現在の実装・推奨設定の根拠として使用しない。重複する英語版は履歴へ退避し、日本語の基本設計を現行正本にする。
