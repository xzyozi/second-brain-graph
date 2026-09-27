---
name: satellite-ideation-reviewer
description: >-
  サテライトリポジトリ（projects/<name>/）のコードを agys（Antigravity CLI ヘッドレス実行）で自律レビューし、
  既存 Issue との重複チェック（Open/Closed 全件）を経て、stage:ideation ラベル付きで GitHub Issue を自律起票するスキル。
  セキュリティ、エッジケース処理、関心事の分離（アーキテクチャ境界）などのテーマ別レビューに対応。
---

# Satellite Ideation Reviewer

サテライトリポジトリ（`projects/<name>/` 配下）のコードベースに対して、`agys`（`agy.exe --dangerously-skip-permissions`）を活用した自律レビューを実施し、抽出された改善提案や潜在課題を `stage:ideation` ラベル付きの GitHub Issue として自動起票するスキルです。

## 主な特徴と安全境界

1. **母艦保護（母艦はレビューしない）**:
   - レビュー対象は常にサテライトリポジトリ（`projects/<name>/`）に限定され、母艦リポジトリ（`second-brain-graph`）は対象外です。
2. **Read-only の厳格担保**:
   - `agys` の実行時はコードの読み取りと分析のみを指示し、ファイル作成・編集・削除ツールは一切実行させません。
3. **ステータス不問の重複チェック**:
   - 対象リポジトリの全 Issue（Open / Closed の双方）を `gh issue list --state all` で取得・照合します。
   - 既存の Closed な Issue と類似している場合は、再発または別観点であることを Issue 本文に明記した上で例外的に起票します。
4. **`tasks.md` への影響隔離（完全自動起票の安全性）**:
   - 起票される Issue には必ず `stage:ideation` ラベルを付与します。
   - オーケストレーターは `stage:ideation` の Issue を `tasks.md`（開発キュー）に登録しないため、勝手に自動実装が進むことはなく、人間の確認・壁打ちまで安全に保留されます。
5. **起票上限（Cap）によるスパム防止**:
   - 1回のレビュー実行で起票される Issue は、重要度順に最大 3 件（設定可能）までに制限されます。

---

## レビューテーマ（観点）

| テーマ名 | キーワード | レビューの主眼 |
| :--- | :--- | :--- |
| **セキュリティ** | `security` | 入力バリデーション、パストラバーサル、秘密情報の漏洩、パーミッション、安全でないAPI呼び出し |
| **エッジケース処理** | `edge_cases` | None/空値ハンドリング、タイムアウト、ネットワーク/IOエラー耐性、境界値条件の欠落 |
| **関心事の分離** | `architecture` | 単一責任の原則、モジュール境界の歪み、循環依存、密結合、再利用性・保守性の課題 |

---

## 使用手順

### 1. 手動実行（ドライラン・起票テスト）

`--dry-run` オプションを付けることで、実際の Issue 起票を行わずに検知結果と Issue 本文をターミナルで確認できます。

```powershell
# サテライト env_builder に対してセキュリティレビューを実行（ドライラン）
uv run python .gemini/skills/satellite-ideation-reviewer/scripts/run_review.py --target env_builder --theme security --dry-run
```

### 2. 本番実行（完全自動起票）

```powershell
# サテライト test_file_grep に対してエッジケースレビューを実行して Issue 起票
uv run python .gemini/skills/satellite-ideation-reviewer/scripts/run_review.py --target test_file_grep --theme edge_cases --max-issues 3
```

### 3. オプション一覧

- `--target <name>`: 対象サテライト名（`projects/<name>/` のフォルダ名。必須）
- `--theme <theme>`: レビューテーマ（`security`, `edge_cases`, `architecture`。必須）
- `--max-issues <int>`: 1回の実行で起票する最大 Issue 数（デフォルト: `3`）
- `--path <relative_path>`: レビュー対象を特定ディレクトリやファイルに絞り込む（デフォルト: サテライトルート）
- `--dry-run`: 実際の Issue 起票を行わず、検知結果とプレビューのみを出力する
- `--verbose`: 詳細ログ（agys の生の応答など）を出力する

---

## 起票される Issue のフォーマット

```markdown
## 検出テーマ: [セキュリティ / エッジケース / 関心事の分離]
- **対象ファイル**: `src/xxx.py#L42-L68`
- **重要度**: [High / Medium / Low]

### 課題・懸念点 (What & Why)
現状の実装における潜在リスクや設計の歪み。

### 改善提案 (Suggested Approach)
推奨されるアプローチまたは修正イメージ。

### 過去の関連 Issue
- #12 (Closed: 類似課題だが別観点で再発のため起票) / 該当なし

---
*※ 本 Issue は `agys` レビューにより自動起票されました（`stage:ideation`）。壁打ち後に `stage:ready` へ昇格してください。*
```
