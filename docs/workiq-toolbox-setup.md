# WorkIQ 接続・同意・検証手順

設計・応答契約は [WorkIQ詳細設計](WORKIQ_DESIGN_AND_IMPLEMENTATION.md)、最新の確認範囲は [実装状況](IMPLEMENTATION_STATUS.md)。本手順のCLIとOAuth実装は feat/pmo-workiq-toolbox にある。実装の参照点は9337145で、文書整理の変更も同ブランチへ取り込み済み。

## 前提と設定

既存 WorkIQ OAuth2 / RemoteA2A Connection を参照する専用 pmo-workiq-tools v1 を使用する。ツールは WorkIQ___SendMessage。実ADOのProject照合が必須で、mock ADOとの組合せを拒否する。

```dotenv
PMO_RUNTIME=foundry
WORKIQ_MODE=toolbox
WORKIQ_TOOLBOX_ENDPOINT=https://aifoundry-techenablement-fde-hackathon-dev-jpe-001.services.ai.azure.com/api/projects/FDE-hackathon/toolboxes/pmo-workiq-tools/versions/1/mcp?api-version=v1
```

Foundry endpoint・モデルと [ADO設定](ado-toolbox-read-setup.md) も指定する。ローカルは AZURE_CREDENTIAL_MODE=azd と azd auth login、Hostedは managed_identity。ユーザーOAuth・refresh tokenはConnectionに任せ、ソースやagent.yamlへ埋め込まない。

## ローカル確認

```bash
.venv/bin/python -m fde_pmo_agent.integrations.mcp.check_workiq
.venv/bin/python -m fde_pmo_agent.integrations.mcp.check_workiq --work-item-id 5
```

前者はツール契約の確認、後者は実ADO照合とWorkIQ取得を行う。IDは確認対象に置き換える。CLIは回答本文・担当者・トークンを出力しない。ローカル認証の成功はHostedのユーザー同意を代替しない。

## Hosted Playground の確認

1. 配備したversion（直近v14）を選び、新規会話で既知のADOタスクのWorkIQ検索を依頼する。
2. Harnessが計画承認を求めた場合は、検索計画を承認する。これはOAuth同意やADO変更承認とは別。
3. WorkIQが未同意なら、標準OAuth同意要求を操作して本人がサインイン・同意する。組織設定によって管理者承認が必要。
4. 同意後に同じ会話で検索を再依頼する。自動再開はまだ検証済みとしない。
5. 回答内容・参照リンク・日時を既知の実データに照合し、続けて再検索する。

APIでは同意待ちfunction_call_output、oauth_consent_request、response.incompleteを確認する。通常の回答取得では取得結果と合成回答の限界を確認する。HTTP200だけで検索・権限・出典の検証を完了としない。

## エラーの切り分け

| 症状 | 確認内容 |
| --- | --- |
| 同意要求が表示されない | Agent version、検索ツールの実行、APIの標準同意項目、既に同意済みかを確認 |
| 同意画面で失敗 | AADSTSコード・Request ID・時刻を使ってtenant、アプリ、権限、redirect、secret等を切り分ける。URL全体は記録しない |
| No tool output found の400 | v14の同意待ちtool outputを確認。旧会話は未完了callを含む可能性があるため、新規会話と分けて検証 |
| timeout・取得失敗 | Connection・ユーザー権限・到達性・応答形式を確認。空結果や成功へ置換しない |
| 接続できるが根拠がない | 対象情報・参照権限・検索キー・索引を確認。関連情報なしと断定しない |

同意画面の再撮影は未同意ユーザーかユーザー単位の解除・再同意を検討する。新規会話だけで再表示されるとは限らない。解除方法と影響は確認してから操作し、共有Connection / Toolboxは削除しない。

過去の暫定URL表示・versionごとの診断は [検証履歴](archive/workiq-toolbox-validation-history.md) に保存する。
