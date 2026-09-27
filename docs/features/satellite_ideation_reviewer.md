# satellite-ideation-reviewer 仕様・運用ガイド

## 1. 概要
`satellite-ideation-reviewer` は、Antigravity CLI ヘッドレス実行（`agys` / `agy -p`）を活用してサテライトリポジトリ（`projects/<name>/`）のコードを自律レビューし、潜在課題や改善提案を `stage:ideation` ラベル付きで GitHub Issue として自動起票する独立スキルです。

## 2. アーキテクチャと安全境界

```
[手動実行 または 定期バッチ]
           │ (サテライト名 + レビューテーマ指定)
           ▼
┌──────────────────────────────────────────────┐
│ Step 1: 情報収集 (Read-only)                  │
│  - 対象ソースコード探索 (除外ディレクトリ考慮) │
│  - 既存 Issue 全件取得 (Open/Closed 双方)      │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Step 2: agys 自律レビュー・問題点抽出          │
│  - テーマ特化プロンプト (security/edge/arch)  │
│  - Read-Only 制約 (ファイル変更を完全禁止)    │
│  - 厳格な JSON 構造化出力                     │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Step 3: 重複判定・重要度ソート・Cap           │
│  - Open Issue 重複: スキップ                 │
│  - Closed Issue 重複: 再発注記を付与して起票   │
│  - 重要度順ソート (High > Med > Low)         │
│  - 最大起票件数 (デフォルト 3 件) で切り詰め  │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Step 4: 完全自動起票 (tasks.md への影響隔離)  │
│  - gh issue create --label "stage:ideation"  │
│  - tasks.md（開発キュー）から安全に隔離      │
└──────────────────────────────────────────────┘
```

### 主要な境界ルール
1. **母艦保護**:
   - 母艦リポジトリ（`second-brain-graph`）自身はレビュー対象外（指定時は即座にエラー終了）。
2. **Read-only の厳格担保**:
   - `agys` へのプロンプト制約および JSON 出力パースにより、作業ツリーへの変更を一切防止。
3. **ステータス不問の重複チェック**:
   - 既存の Open / Closed 両方の Issue を照合。Closed の過去課題と重複する場合は、その旨（再発確認・別観点）を本文に明記。
4. **`tasks.md` への影響隔離**:
   - `stage:ideation` ラベルを付与して起票するため、オーケストレーターの開発キュー（`tasks.md`）には登録されず、勝手に自動実装が走ることはありません。

---

## 3. レビューテーマ（観点）

- **セキュリティ (`security`)**:
  - パストラバーサル、コマンドインジェクション、ハードコードされた認証情報、入力検証不備。
- **エッジケース処理 (`edge_cases`)**:
  - None/空値ハンドリング、タイムアウト、例外の握りつぶし、ネットワーク/IO耐性。
- **関心事の分離 (`architecture`)**:
  - 単一責任の原則、モジュール結合度、グローバル状態、拡張性・保守性。

---

## 4. 使用方法

### ドライラン（起票プレビュー）
```powershell
uv run python .gemini/skills/satellite-ideation-reviewer/scripts/run_review.py `
  --target env_builder `
  --theme security `
  --dry-run
```

### 本番実行（自動起票）
```powershell
uv run python .gemini/skills/satellite-ideation-reviewer/scripts/run_review.py `
  --target test_file_grep `
  --theme edge_cases `
  --max-issues 3
```
