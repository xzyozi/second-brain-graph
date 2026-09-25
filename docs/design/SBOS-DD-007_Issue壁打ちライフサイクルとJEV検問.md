# SBOS-DD-007: Issue 壁打ちライフサイクルと JEV スクリーニング仕様書

- **バージョン**: 1.0.0
- **策定日**: 2026-09-25
- **ステータス**: 正式版 (Implemented)
- **対象**: `tools/screen_issues.py`, `tools/close_stale_issues.py`, `tools/score_issues.py`, `.github/workflows/cleanup-stale-ideation.yml`

---

## 1. 概要と目的

本仕様書は、GitHub Issues を入力とする自律開発パイプライン（`orchestrator_graph.py` / `tasks.md`）の前段に位置する **「最上流：壁打ち・構想フェーズ（Ideation Phase）」** の状態管理ルール、および **JEV による決定論的スクリーニング仕様** を定義します。

### 解決する課題
1. **実装キューへの混入防止**:
   未確定なアイデアやドラフト段階の Issue が、`tasks.md` や `score_issues.py` に混入してエージェントが意図せず自律実装を開始してしまうリスクを完全遮断する。
2. **重複・車輪の再発明の早期検知**:
   全 Issue（Open / Closed 双方）から、類似した課題や過去の議論を JEV で検知し、重複起票を防ぐ。
3. **長期放置 Issue の自動整理**:
   構想（`stage:ideation`）のまま進展のない Issue を 30 日で自動クローズし、バックログの肥大化・陳腐化を防ぐ。

---

## 2. ラベル体系とステートマシン

Issue の状態を以下の 4 つの `stage:*` ラベルで厳格に分離管理します。

| ラベル | 役割 | `tasks.md` / スコアリング対象 |
| :--- | :--- | :---: |
| `stage:ideation` | 構想・壁打ち中。要件定義やコメント議論中 | **完全除外** |
| `stage:ready` | 仕様確定・着手可能。受入条件(AC)確定済み | **対象（スコアリング・実装）** |
| `stage:in-progress` | エージェントまたは開発者が実装・PR作成中 | 実行中管理 |
| `stage:done` | PR マージ完了・タスク終了 | 完了アーカイブ |

### 状態遷移フロー
```text
[新規起票 (手動/自動)]
        │
        ▼
 (stage:ideation 付与)
        │
        ├─────────────────────────────┐
        │ JEV 重複・カテゴリ検査      │ (30日未更新)
        ▼                             ▼
 [コメント欄で壁打ち・寝かせ]    [自動クローズ (Actions)]
        │
        ▼ (ユーザー承認: stage:ready 付与)
 [score_issues.py / tasks.md 同期]
        │
        ▼
 [自律実装パイプライン (orchestrator_graph)]
```

---

## 3. コンポーネント仕様

### 3.1 JEV Issue スクリーニング (`tools/screen_issues.py`)
- **役割**:
  - 全 Issue（Open / Closed 双方）を取得し、重複・類似 Issue の検知と領域カテゴリの推論を行う。
- **JEV 重複検知ポリシー (`DUPLICATE_CHECK_POLICY`)**:
  - 2 つの Issue を比較し、本質的な課題・目的・仕様が実質的に重複しているかを JEV `NoulTask`（またはレキシカル Jaccard 類似度）で判定。
- **カテゴリ自動推論**:
  - タイトル・本文のキーワードから `area:orch`, `area:jev`, `area:ci`, `area:safety`, `area:docs` 等を推薦。
- **反映オプション (`--apply`)**:
  - Issue にスクリーニング結果をコメント投稿し、推奨カテゴリラベルを自動付与。

### 3.2 放置 Issue 自動クローズ (`tools/close_stale_issues.py`)
- **役割**:
  - `stage:ideation` のまま最終更新日（`updatedAt`）から 30 日以上経過した Issue を検索し、警告なしで即座に Close する。
- **実行オプション**:
  - `--days <N>`: 放置判定日数（デフォルト: 30）
  - `--dry-run`: 実際のクローズを行わずシミュレーション表示

### 3.3 GitHub Actions 自動クリーンアップ (`.github/workflows/cleanup-stale-ideation.yml`)
- **スケジュール**: 毎日深夜 UTC 00:00 (日本時間 09:00) 定期実行。手動実行（`workflow_dispatch`）にも対応。
- **認証**: 外部 API キー不要。標準の `GITHUB_TOKEN`（`issues: write`）のみで動作。

### 3.4 スコアリングフィルタ更新 (`tools/score_issues.py`)
- `tasks.md` のメタデータに `stage:ideation` や `draft` が設定されている場合、`process_scoring` の候補選定から確実にスキップ除外するガードを追加。
