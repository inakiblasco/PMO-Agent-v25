# WorkIQ 導入・同意処理の検証履歴

> v8〜v14 の導入履歴です。現在の設計は [WorkIQ 設計](../WORKIQ_DESIGN_AND_IMPLEMENTATION.md)、手順は [接続手順](../workiq-toolbox-setup.md) を参照してください。

## 実装構成

既存 `WorkIQ` Connection を参照する専用 Toolbox `pmo-workiq-tools` v1 を作成した。Toolbox は `WorkIQ___SendMessage` を直接公開する。PMO の `workiq_search_task_context` から WorkIqToolboxClient が MCP を呼び、Toolbox は WorkIQ へ OAuth2 / A2A で接続する。生の MCP Tool はモデルへ公開しない。

共通 FoundryToolboxSessionFactory は現在の request context 内で fresh session を開き、SDK の bearer 認証・call ID 転送を利用する。ADO の既存 session factory 名は互換 alias として維持した。

## 設定

```dotenv
WORKIQ_MODE=toolbox
WORKIQ_TOOLBOX_ENDPOINT=https://aifoundry-techenablement-fde-hackathon-dev-jpe-001.services.ai.azure.com/api/projects/FDE-hackathon/toolboxes/pmo-workiq-tools/versions/1/mcp?api-version=v1
```

default は disabled。mock runtime の既存モックは維持する。実 WorkIQ は実 ADO Adapter による対象照合を必須とし、ADO_MODE=mock との組合せは拒否する。ローカルは AZURE_CREDENTIAL_MODE=azd、Hosted は managed_identity。azure.yaml と agent.yaml に WorkIQ 接続設定を追加した。

## 検索と応答

検索前に ADO Work Item を実取得する。Project 照合後、ID・タイトル・担当者を上限付きの検索データとして固定の取得依頼に入れる。既存 query 引数は互換性のため残すが、自由命令として WorkIQ へ転送しない。期間14日・結果目安10件・timeout120秒・回答20000文字が初期値。

WorkIQ は A2A Task の artifacts.parts に合成回答を返す。Task が completed でない場合、空・過大・不正形式・isError は成功として返さない。task/context ID は再利用しない。明示的な -32006 は同意要求へ変換し、エラーを空結果や架空のモック根拠へ置換しない。

今回確認した応答には、独立して検証できる source record 配列の保証がない。そのため返却 record は source_type=workiq_synthesis、summary、retrieved_at、grounding_status=unverified_citations、evidence=[] とする。source_id、発生日時、confidence は生成しない。本文に URL があっても、この段階では検証済み出典とは扱わない。文章を Agent が読むことはできるが、ADO 更新の確定根拠とは区別する。完了応答は M365 関連情報が必ず見つかったことを保証しない。

既存 Port は配列型を維持しており、その1レコードに合成回答を格納する。将来 service が構造化した出典を返すケースを検証した際に、evidence の変換を追加する。

WorkIQAgent.Ask は読取り専用権限ではない。固定取得依頼・ツール非公開化は任意命令を制限するが、WorkIQ 内部の副作用を権限レベルで禁止する保証ではない。今回の実装は検索用途に限定し、PMO の実メール送信・予定作成は有効化しない。

## ローカル検証

`.env` またはプロセス環境に上記と実 ADO 設定を指定する。

```bash
.venv/bin/python -m fde_pmo_agent.integrations.mcp.check_workiq
.venv/bin/python -m fde_pmo_agent.integrations.mcp.check_workiq --work-item-id 5
```

前者は Tool 契約のみ、後者は実 ADO 照合と WorkIQ 取得を行う。出力に回答本文・担当者・トークンを含めない。

2026-10-08: 専用 Toolbox の実 schema とローカル WorkIQ 呼出しを確認。Adapter / CLI 経由で ID5 の回答697文字を取得し、grounding_status=unverified_citations を確認。単体テスト67件成功。テストは成功形式・未完了・空/過大・同意/timeout・ADO照合失敗・Hosted結線を確認する。既存 ADO Gateway の承認テストも維持する。

Hosted 検証では新規 session で `workiq_search_task_context(5, "")` を呼び、実 Tool と Toolbox HTTP 成功を確認する。別ユーザーの OAuth 同意・権限、出典の構造化、厳密な読取り権限制御、永続化は残項目。

## Hosted v8 の検証結果

2026-10-08、test-hostedagent v8 に配備成功。新規 Responses session で PMO Tool `workiq_search_task_context(5, "")` が呼ばれ、専用 Toolbox の MCP initialize / tools 呼出しが HTTP 200 を返した。WorkIQ 実取得は MCP error -32006 の同意要求で停止し、Adapter は WorkIqConsentRequiredError として報告した。取得成功とは扱わない。

Trace ID: `a7bbdd83f1910ce4876d89f856348af4`。ローカルの azd 利用者認証では取得成功だが、Hosted の呼出し元コンテキストの同意は別途必要。VNet injection 環境から Toolbox への到達は確認できたが、WorkIQ 取得完了までの経路は同意後に再検証する。

v8 は同意 URL をモデルへ転送する機能を持たなかった。この不足を v11 で修正した。admin consent、ユーザー同意、Hosted の呼出しコンテキストを混同しない。

## 同意の意味と v11 の対応

ここでの同意は、WorkIQ が呼出し元ユーザーに代わって Microsoft 365 情報へアクセスするための OAuth 認可である。Hosted Agent の managed identity による Azure 認証、ADO 更新 Proposal の一回限りの承認とは別。既存 WorkIQ Connection は delegated の `WorkIQAgent.Ask` と `offline_access` を要求する。ユーザーはサインイン画面のアプリ・権限を確認して同意する。組織のユーザー同意ポリシーにより管理者承認が必要な場合がある。

v11 は MCP -32006 の構造化された WorkIQ / CONSENT_REQUIRED エラーから同意 URL を抽出する。HTTPS、Microsoft の既知ホスト、認証情報・制御文字を含まない URL のみ許可し、エラー全文を返さない。PMO Tool は例外で終了する代わりに `status=consent_required` と `consent_link` を返し、Agent がクリック可能なリンクを表示する。リンクを取得できない場合は Connection 確認を案内し、取得成功とは扱わない。リンクを自動で開かず、同意前の自動再試行も行わない。

利用手順は v11 のプレイグラウンドで WorkIQ 検索を依頼し、返された同意リンクを本人が開いてサインイン・同意した後、同じ検索を再度依頼する。ネイティブ OAuth カードによる自動再開は今回の実装に含めず、返答中のリンクと明示的な再依頼を使う。同意 URL は一時的な認証フローの情報を含むため、ドキュメントや Git に保存しない。

単体テスト69件成功。追加テストは、ネストした MCP 同意エラーから PMO Tool の返却までリンクが維持されること、不正な URL を公開しないこと、同意要求時に結果や根拠を捏造せず再試行しないことを確認する。

Hosted v9/v10 では同意ステータスの返却を確認したが URL は表示されなかった。診断で、実際の同意ホストは `logic-apis-japaneast.consent.azure-apim.net` と確認し、v11 で Microsoft のリージョン別同意ホストを許可した。診断用ログは最終コードから除去した。

Hosted v11 の実呼出しで `consent_required` とクリック可能な同意リンクの表示を確認した。Trace ID: `4f7b961dcc168afb7dc6200526b47257`。WorkIQ 取得は同意待ちであり、取得完了の検証は利用者の同意後に行う。

## 標準 OAuth 同意応答への移行（v14）

v11 の Markdown リンク表示は廃止した。現在は次の標準 SDK 経路を使う。

1. Adapter は認証済み Toolbox の WorkIQ / CONSENT_REQUIRED 応答から URL を抽出する。
2. PMO Tool は `Content.from_oauth_consent_request` を返す。
3. `WorkIqConsentMiddleware` は Tool 実行後に `UserInputRequiredException` を発生させる。Tool 本体は正常に戻るため、SDK の Function failed ログを発生させずに同意待ちへ移行できる。
4. SDK の実行ループは同意 Content を外側へ伝播してモデルの追加呼出しを停止する。ResponsesHostServer は `oauth_consent_request`（server_label=WorkIQ、consent_link付き）を出力し、`response.incomplete` で終了する。

URL はモデルや検索結果本文から受け取らず、設定済みの認証済み Toolbox の同意エラーだけから取得する。リージョン・ホストの独自 allowlist は撤去し、固定バージョンの Foundry Host と同じ HTTPS・ホスト形式・認証情報・制御文字の検証を行う。SDK の private 関数は実装から直接呼ばず、互換性をテストで照合する。

プレイグラウンドで v14 を選択して新規会話から WorkIQ 検索を実行する。同意要求の表示・操作は Foundry UI が担当する。同意後の自動再開は未検証なので、必要なら同じ会話で検索を再依頼する。同意 URL の取得に失敗した場合のみ、通常の `consent_required` ステータスと Connection 確認案内へフォールバックする。

全71件の単体テスト成功。実 SDK のツール実行・モデルループ停止・標準応答の生成・URL検証互換性・同意待ち時にエラーログを出さないことを確認した。Hosted v12 でも標準同意応答と response.incomplete を確認した。v13 は同意による通常失敗ログも除去した版。API 応答の確認と、ブラウザーでの同意ボタン表示・利用者の同意完了は別の検証として扱う。

### 同意後の会話履歴の修正

v13 の同意要求だけを伝播する方式では、元のモデル function call に対応する tool output が欠け、次の発話で `No tool output found for function call` の400が発生した。v14 は `UserInputRequiredException.contents` に同じ call ID の `function_result`（status=consent_required、取得未完了）を先に入れ、続いて標準同意要求を返す。これにより会話履歴の呼出しを閉じてから同意待ちへ停止する。認証成功・検索成功の結果とは扱わない。

利用者から同意画面への遷移を確認した一方、同意処理の失敗が報告された。これは会話履歴の400とは別に切り分ける。Connection の authorization/token URL、offline_access と WorkIQAgent.Ask スコープ、redirectUrl を読み取り確認し、Connection の error フィールドは空だった。Entra の失敗コード・Request ID が必要で、原因未確定のままアプリ権限や redirect 設定を変更しない。

v14 の実呼出しは response.completed、次の発話も400なしを確認。ただしモデルが既存の同意待ち状態を説明して検索を実行しない試行となったため、v14で同意要求を発生させた直後の再開は実環境では未確認。SDK実行ループの単体テストでは function_result と oauth_consent_request の両方の伝播を確認済み。
