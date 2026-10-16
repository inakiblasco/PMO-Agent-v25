# ブランチポリシー

## ルール

- Squash マージのみ許可（マージコミット・リベースマージは無効）
- マージ済みブランチは自動削除
- `main` へのすべての変更はプルリクエスト経由
- 1ブランチでは1つの目的だけを扱う
- ローカルコミットは許可するが、push は利用者の明示的な依頼がある場合だけ行う

## 開発統合ブランチ

- `main` は安定版として維持する
- `terai-hackathon-dev` を日常開発の統合先とする
- 目的別ブランチは `terai-hackathon-dev` から作成し、検証後に同ブランチへ Squash マージする
- `main` へは、利用者が明示的に依頼したリリース時だけ Pull Request 経由で反映する

## ブランチ命名

ブランチ名は `<type>/<issue-or-topic>` とする。

| type | 用途 | 例 |
| --- | --- | --- |
| `feat` | 機能追加 | `feat/pmo-domain-gateway` |
| `fix` | 不具合修正 | `fix/ado-revision-conflict` |
| `test` | テストのみ | `test/workiq-contract` |
| `docs` | 文書・ルール | `docs/pmo-agent-development-rules` |
| `refactor` | 振る舞いを変えない整理 | `refactor/proposal-store` |
| `chore` | 依存・ビルド・ホスティング | `chore/pmo-hosting` |
| `spike` | 破棄可能な技術検証 | `spike/workiq-message-send` |

Issue 番号がある場合は `feat/123-pmo-domain-gateway` のように topic の先頭へ含める。

## 開発フロー

1. `terai-hackathon-dev` のベースラインテストを実行する
2. `terai-hackathon-dev` から目的別ブランチを作成する
3. 1つの変更と対応テストを1コミットにまとめる
4. 対象テスト、全単体テスト、`git diff --check` を実行する
5. ローカルコミットを作成する
6. 利用者の依頼がある場合だけ push と Pull Request 作成を行う
7. `terai-hackathon-dev` へローカル Squash マージ後、更新された同ブランチから次のブランチを作成する

未マージブランチを基点にした積み重ねブランチは原則使用しない。必要な場合は依存元とマージ順を明記する。

## 原因切り分けのためのルール

- Conventional Commits 形式を使用する
- 各コミットを単独でテスト可能にする
- バグ修正では再現テストと修正を対応付ける
- 複数の原因仮説を同じコミットで試さない
- 無関係な整形、リネーム、依存更新を混ぜない
- 通常の共有コミットはテストが成功する状態にする

PMO Agent は次のブランチへ分割し、前段を取り込んでから次段へ進む。

```text
feat/pmo-domain-gateway
    ↓
feat/pmo-agent-skills
    ↓
feat/pmo-mcp-adapters
    ↓
chore/pmo-hosting
```

## `main` ブランチルールセット

| ルール | 値 | 理由 |
|---|---|---|
| 直接 push | ブロック | すべての変更をレビュー経由にするため |
| 強制 push | ブロック | 履歴の書き換えを防ぐため |
| ブランチ削除 | ブロック | `main` を誤って削除しないようにするため |
| 必要レビュアー数 | 1人 | Copilot が書いたコードを必ず人間がレビューするため |
| 新コミット後のレビュー破棄 | 有効 | 承認後の変更を見落とさないようにするため |
| 最終 push した本人による承認 | 不可 | 自分の変更を自分で承認できないようにするため |
| レビューコメントの解決 | 必須 | 指摘事項を放置したままマージできないようにするため |
| 線形履歴 | 必須 | コミット履歴を読みやすく保つため |

## ポリシーの適用方法

1. **Settings → Rules → Rulesets** を開く
2. **New ruleset → Import a ruleset** をクリック
3. [`.github/branch-policy-template.json`](../.github/branch-policy-template.json) をアップロード
4. 設定を確認して **Create** をクリック
