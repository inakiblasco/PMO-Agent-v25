# PMO Agent 実装状況と課題

更新日: 2026-10-09。コード、過去の実呼出し、利用者の確認報告に基づく。今回 Azure リソースを再取得したものではない。設計は [基本設計](PMO_AGENT_DESIGN.md)、優先順位と完了条件は [実装計画](IMPLEMENTATION_PLAN.md)。

## 参照するブランチ・配備

| 対象 | 状態 |
| --- | --- |
| 統合ブランチ | terai-hackathon-dev、3910817。ADO初期実装とWorkIQ導入前計画まで |
| WorkIQ実装 | feat/pmo-workiq-toolbox、9337145。未統合、個人remoteへpush済み |
| 文書整理 | docs/workiq-design-statusで作成し、feat/pmo-workiq-toolboxへ取り込み済み |
| 直近のHosted配備 | test-hostedagent v14、Foundry Project FDE-hackathon |
| 全単体テスト | WorkIQ実装側71件成功。取り込み前の文書専用ブランチは統合ベースの59件対象だった。取り込み後の本ブランチは71件対象 |

現在の文書とWorkIQコードは同じ機能ブランチにある。統合ブランチにはまだ反映していない。配備versionとGit統合状態は別。

## 機能別の状態

| 機能 | 実装 | 検証・残る制約 |
| --- | --- | --- |
| Harness / 4 Skills / 8 PMO Tools | 実装済み | 計画・実行mode切替の引数解析エラーが検証中に発生。安定化が必要 |
| ADO単一取得・期限超過一覧 | 実Adapter済み | Hosted単一取得と2件の期限超過一覧を確認。上限200件・ページング未対応 |
| ADO作成・更新・コメント | 初期実装完了 | 利用者が書込み成功を確認。全操作のID/revision/trace記録は未完了 |
| WorkIQ取得 | 実Adapter済み | ローカル回答取得。Hosted同意・接続は利用者確認済み。関連実データとの照合が必要 |
| WorkIQ標準OAuth同意 | 実装済み | v12 APIでoauth_consent_request / response.incomplete、利用者が画面遷移・同意完了を確認 |
| 未完了callの400対策 | v14に実装 | 同意待ちfunction_resultを追加。単体テスト済み。実環境の同意直後再開は体系的に未確認 |
| 実メッセージ送信 | 未実装 | 実runtimeはdisabled。mockの宛先照合・重複・頻度・監査はテスト済み |
| Cosmos DB業務状態・監査 | 未実装 | Proposal/Audit/registryはプロセスメモリ。再起動・複数Replicaの耐久性なし |
| 意味記憶・WorkIQ結果永続化 | 未実装 | 保存目的、出典、アクセス制御、保持期間の設計が必要 |
| Teams公開・Autopilot・無人実行 | 未実装 | 認証・チャネル・identity・ライセンスを別途検証 |
| 監視・RBAC再現性 | 部分対応 | 実接続の独自JSONLは無効。永続相関ログ・IaC・SDK側収集を確認する |

## 確認済みの証拠

- ADO: Toolbox v2 のschema・実get/get_batchを確認。Hosted v4でID3/revision2、v5で期限超過2件（ID5,6）。書込みは利用者報告で確認。
- WorkIQ: 専用pmo-workiq-tools v1でWorkIQ___SendMessageを確認。ローカルazd認証でID5の合成回答を取得。
- Hosted: VNet injectionを維持した環境からToolboxへの到達・同意要求を確認。利用者から同意と接続を確認できたとの報告。
- v14: 再発話で400なしの試行は確認。ただし検索を実行しない応答もあり、同意で停止した直後の再開成功を示すE2E記録はまだない。
- テスト: 外部通信なしの単体テストでADO承認・競合・成否不明、WorkIQ契約・正規化・同意・履歴call終端・SDK標準応答を検証。

過去のtrace・導入履歴は [ADO読取り](ado-toolbox-read-setup.md)、[ADO書込み](ado-toolbox-write-setup.md)、[WorkIQ履歴](archive/workiq-toolbox-validation-history.md)。同意URLや実本文を証跡文書へ保存しない。

## 未解決の課題

| 分類 | 課題 |
| --- | --- |
| 検索品質 | 既知のM365情報との内容・リンク照合。evidence=[]、unverified_citationsで検証済み出典は未提供 |
| 会話・認証 | 同意→同じ会話の再検索、別ユーザー・未同意・権限不足、失効・再同意 |
| 認可 | WorkIQAgent.Askは読み取り専用でなく、固定取得依頼は権限による副作用禁止を保証しない |
| ADO整合性 | 操作別実証拠、同時編集、成否不明の照合、ページング・大量結果 |
| 状態耐久性 | 永続Proposal/Audit、再起動復元、原子的claim、複数インスタンス |
| UX・運用 | Harness mode切替の失敗、SDK互換性、エラー分類、監視、配備再現性 |

ADO初期実装は利用者との合意で完了。WorkIQは認証・接続まで確認済みの段階で、初期完了の判断には実検索・再開の検証が残る。全体の本番運用完了を意味しない。
