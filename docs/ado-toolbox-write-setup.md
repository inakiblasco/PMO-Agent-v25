# ADO Remote MCP 書込み実装

読取りは既存 Toolbox v2、書込みは追加した v3 を使う。v3 には wit_work_item / wit_query / wit_work_item_write / wit_work_item_comment_write があり、実 tools/list で仕様を確認した。モデルには生 MCP Tool を公開しない。

## 設定と経路

`ADO_MODE=toolbox` と `ADO_WRITE_TOOLBOX_ENDPOINT=<pmo-agent-tools/versions/3/mcp?api-version=v1>` を設定する。`toolbox_readonly` は従来の書込み無効モード。読取り endpoint / Project / server label / Custom.DueDate / Done は既存設定を使う。azure.yaml と agent.yaml は toolbox モードに更新した。

`PMO propose Tool → session-owned Proposal Store → always_require apply Tool → AdoWriteGateway → private AdoWriteMcpClient → Foundry Toolbox → ADO` の順に呼ぶ。実メッセージ送信は無効。WorkIQ は機能ブランチで接続済み。全体の状態・課題は [実装状況](IMPLEMENTATION_STATUS.md) を参照する。

## 操作契約

- 作成: `wit_work_item_write(action=create, project, workItemType, fields=[{name,value}])`。Gateway の許可フィールド・type 制限を通す。承認 summary は全作成フィールドを含める。
- 更新: `wit_work_item_write(action=update, project, id, updates)`。直前読取りで Project/revision を検証し、`Test /rev` を先頭に付けた PATCH で競合をサーバー側でも防ぐ。
- コメント: 専用 comment MCP は revision 条件を提供しないため、同じ `Test /rev` と `Add /fields/System.History` で Discussion に追記する。専用 comments API の Markdown コメント ID / mention 変換と同一とは扱わない。実 UI 表示は実書込みテストで確認する。

書込み直前に tools/list の引数を照合する。バッチ更新・削除・リンク・親子作成は実装しない。Proposal の session、digest、summary、許可フィールドを Gateway で検証する。Task の `Custom.DueDate` は構成された期限フィールドとして policy に追加する。

## 成否不明と再実行

Remote MCP が idempotency key を保存して重複排除する契約は確認できない。Proposal ID をサーバーの冪等性保証と呼ばない。Gateway が1 Proposalを原子的に claim して、成功後は再実行を拒否する。

dispatch 後の timeout / tool error / 不正レスポンスは WriteOutcomeUnknownError にし、Proposal を rejected にして再利用を禁止する。サーバーが書いてから切断した可能性があるため、ADO と監査を確認し、新しい Proposal が本当に必要か判断する。明示的な revision conflict は dispatch 前に拒否する。サーバー側競合エラーも現在は保守的に成否未確認として扱う。

キャンセルも監査に requires_reconciliation=true を残し、再利用を禁止する。自動 retry やモック fallback はない。成功レスポンスは Project、ID、revision、作成 type/title、一部更新フィールドを検証する。

Proposal / Audit はインメモリ。プロセス再起動時は未適用 Proposal が失われ、復元・承認再開はできない。クラッシュ直後の成否照合・複数インスタンスの永続監査は Cosmos 段階で実装する。現段階は承認付き対話利用の実 Adapter であり、無人の永続ジョブとして完了保証しない。

## 検証

単体テストで Gateway 経由の3操作、revision Test、競合、成否不明・cancel後の再実行禁止、read/write client 分離、always_require 承認を確認する。実書込みは任意の既存タスクへ行わず、具体的な作成・更新・コメント Proposal に対する「今回のみ」の承認後に行う。

検証用作成案: PMO-Agent に Task を1件作成、System.Title=`PMO ADO MCP write verification`、System.Description=`Temporary task for verifying approval-bound ADO MCP writes.`、System.Tags=`pmo-mcp-verification`。作成後に返った ID を対象として次の更新・コメント案を提示し、各操作を別に承認する。テストデータの削除は実装・実行しない。

2026-10-08: 単体テスト59件成功。Hosted v7 の配備成功と、toolbox モードで Work Item ID 3 / revision 2 の読取りを確認した（Trace ID `63eec674ccacc401073e12db43eb70ba`）。Toolbox v3 の書込み schema は実取得済み。その後、利用者から実書込み成功の報告を受けた。操作種別・対象 ID・revision・実行 trace は報告されていないため、全操作の実検証済みとは扱わない。

## 初期実装の完了判定と運用対応

2026-10-08、利用者との合意により **ADO 初期実装を完了**とする。Foundry Toolbox 経由の読取り、承認付き作成・更新・コメントの実 Adapter、Gateway の検証・競合防止・再送抑止を実装済み。Hosted 読取りは実検証済み、実書込み成功は利用者確認済み。次の機能実装へ進める。

以下は本番運用へ向けた残項目として別管理する。初期実装完了は本番運用の検証完了を意味しない。

| 残項目 | 完了条件 |
| --- | --- |
| 操作別の実検証記録 | 作成・更新・コメントそれぞれの ID / revision / trace と ADO UI の結果を記録。History コメントの表示も確認 |
| 利用者別の権限・同意 | 別ユーザー、未同意ユーザー、権限不足ユーザーで意図した参照・書込み範囲と同意再開を確認 |
| 同時編集 | Proposal 後の外部変更、直前読取り後の変更を起こし、更新が競合で止まり新規承認が必要になることを確認 |
| 成否不明の照合 | dispatch 後の通信失敗を再現し、ADO・監査との照合手順と重複防止を検証 |
| Cosmos DB 永続化 | Proposal / Audit の保存、再起動時の復元・照合、複数インスタンスの排他、保存期間を実装・検証 |

現在の運用範囲はユーザーが承認する対話操作。WorkIQ は機能ブランチで実装済み、メッセージ送信と無人実行の耐久性は別段階である。
