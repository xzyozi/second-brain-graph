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

### 3.3 配下リポジトリ専用 GitHub Actions ワークフロー (`.github/workflows/issue-auto-tag.yml`)
- **アーキテクチャ方針 (PM-057: 母艦純化 ＆ サテライトIssue自律運用)**:
  - 母艦リポジトリ（`second-brain-graph`）はフレームワーク・基盤コードのみを管理し、プロダクト固有のIssue自動タグ付けワークフローは母艦には配置しない。
  - プロダクト開発現場である各サテライト（配下リポジトリ `projects/<name>/`）の `.github/workflows/issue-auto-tag.yml` として配備し、Issue起票時に自動で `stage:ideation` およびカテゴリラベル（`enhancement`, `bug` 等）を付与する。
  - 新規プロジェクト登録ツール `tools/add_project.py` により、未存在時に自動生成・初期配備される。
- **認証**: 外部 API キー不要。標準の `GITHUB_TOKEN`（`issues: write`）のみで動作。

### 3.4 スコアリングフィルタ更新 (`tools/score_issues.py`)
- `tasks.md` のメタデータに `stage:ideation` や `draft` が設定されている場合、`process_scoring` の候補選定から確実にスキップ除外するガードを追加。

### 3.5 agys サテライト自律レビュー＆Issue起票スキル (`satellite-ideation-reviewer`)
- **アーキテクチャ方針 (PM-058: 独立スキル化と完全自動起票)**:
  - Antigravity CLI ヘッドレス実行（`agys` / `agy -p`）を活用し、サテライトリポジトリ（`projects/<name>/`）のコードをテーマ別（セキュリティ、エッジケース処理、関心事の分離）に自律レビューする独立スキル（`.gemini/skills/satellite-ideation-reviewer/`）を新設。
  - **母艦保護**: 母艦自身（`second-brain-graph`）はレビュー対象外として厳格に遮断。
  - **Read-only 担保**: プロンプト制約と JSON 構造化出力パースにより作業ツリーへの変更を完全防止。
  - **ステータス不問の重複チェック**: `gh issue list --state all` で全件照合。Open 重複はスキップ、Closed 重複は再発注記を付与して例外起票。
  - **tasks.md 影響隔離**: 起票する Issue には必ず `stage:ideation` を付与し、オーケストレーターの開発キュー（`tasks.md`）には混入させず安全に保留。
  - **起票上限 (Cap)**: 重要度順（High > Medium > Low）にソートし、1実行あたり最大3件（設定可能）に制限。

### 3.6 サテライト初期化時のラベル自動同期と自己修復ガード (`tools/add_project.py`, `run_review.py`)
- **プロジェクト登録時の自動同期**: `tools/add_project.py` の `setup_labels` をデフォルト有効化（`True`）とし、サテライト初期化時に GitHub 上へ標準ステージラベル（`stage:*`）およびテーマラベル（`theme:*`）を自動作成。
- **自己修復（Ensure Labels）ガード**: `run_review.py` において、Issue 起票直前にリポジトリ側のラベル実在を確認し、未登録の場合は即座に `gh label create` を自動実行して起票失敗を 100% 防止。

### 3.7 母艦一元管理の標準 Issue テンプレートと tasks.md 責務分離 (`metadata/templates/issue_template.md`)
- **アーキテクチャ方針 (PM-059: Issue 仕様の母艦一元化とプロンプト依存解消)**:
  - Issue の構造をプロンプト依存や起票者の自由記述から脱却させるため、母艦の `metadata/templates/issue_template.md` を唯一の正本（SSOT）として配置・管理する。
  - 配下サテライトリポジトリの `.github/ISSUE_TEMPLATE/` 等への個別散在を禁止し、母艦で統一的に管理する。
  - **`tasks.md` と Issue の責務境界**:
    - `tasks.md`: プロジェクトの開発キュー・進捗管理台帳（1行1タスクのメタデータリスト。`score_issues.py` の入力）。
    - `Issue`: 1つの課題に対する詳細仕様書・要件定義書（0〜8章から成る Markdown ドキュメント）。
    - 起票時（`stage:ideation`）は `tasks.md` には一切触れず、壁打ちを経て `stage:ready` に昇格した段階で `tasks.md` へ同期・登録される。
- **0〜8章 標準 Issue スキーマ**:
  - `## 0. メタ情報 (Scope & Impact)`: 影響範囲、既存コード依存、関連Issue
  - `## 1. 概要・背景`: タスクの背景・目的（課題詳細を含む。PRサマリーとしても抽出）
  - `## 2. 仕様および要求事項 (修正方針の検討)`: 修正方針の選択肢（案1 推奨 / 案2 代替）。合意された方針が `tasks.md` のタスク登録 input となる
  - `## 3. 段階的実装手順 (Step-by-step Execution)`: Phase 1 (本体), Phase 2 (テスト)。壁打ち昇格時は確定タスク（`concrete_tasks`）が具体的な実行ステップとして展開・反映される
  - `## 4. 編集対象ファイル (Target Files)`: 対象ファイルパス（オーケストレーターが自動抽出）。壁打ち昇格時に確定方針に応じた対象ファイルリストで更新される
  - `## 5. ドメイン知識・技術上の落とし穴 (Domain Knowledge & Technical Pitfalls)`: 仕様、落とし穴、推奨パターン
  - `## 6. 設計制約・アンチパターンの禁止 (Architecture Constraints & Forbidden Actions)`: 単一責任、ハック禁止
  - `## 7. 対象外 (Non-Goals)`: スコープ外の明記（非採用案の退避先）
  - `## 8. 完了定義 (Definition of Done)`: 受入条件、動作確認、CI運用指針

### 3.8 完了定義 (DoD) における CI / 自動検査の運用指針
- **CI 依存の排除とプロジェクト成熟度に応じた柔軟性**:
  - 完了定義に特定ツール（`Ruff` や `pytest`）を固定でハードコードすることはアンチパターンとし、プロジェクトの環境・検証基盤に応じた柔軟な運用を規定する。
  - **CI / 静的解析が未整備のプロジェクト**:
    - 自動検査ツールの実行は強制せず、ローカルでの動作確認コマンドや手動検証スクリプトの正常終了をもって完了とする。
  - **CI / 静的解析が整備済みのプロジェクト**:
    - プロジェクト側の CI 設定（GitHub Actions / `pyproject.toml` 等）に準拠し、テスト全件通過・Linter エラー 0 件・CI Checks (All Green) を完了条件とする。

### 3.9 修正方針の選択肢提示と 2 段階壁打ちフロー (Tiered Refinement)
- **tasks.md と Issue 仕様書の進捗管理の責務分離（SSOTの確立）**:
  - **進捗管理の一元化**: タスク全体の進捗・完了ステータス（ToDo / In Progress / Done）はサテライトの `tasks.md` に一元化し、Issue 本文内に重複する独立進捗チェック枠（旧 `### 確定実装タスク (Task Checklist)` 等）は設けない（存在する場合は昇格時に削除・一元化）。
  - **確定タスクの役割と反映先**: 壁打ちで確定した具体的な作業手順（Sub-tasks / 実行ステップ）は、独立した進捗チェック枠として重複させるのではなく、オーケストレーターへの実装指示情報として **`## 3. 段階的実装手順 (Step-by-step Execution)`** セクション内に展開・反映する。
  - **修正方針の決定**: Issue の `## 2. 仕様および要求事項` は「修正方針の検討・選択肢提示（案1 推奨 / 案2 代替）」とし、合意された方針が `tasks.md` へのタスク登録および仕様確定の直接の input となる。
  - **昇格時の状態遷移**: 壁打ち完了（`stage:ready` 昇格時）は、選定された案のチェックボックスを `[x]` に更新し、選ばれなかった案は `## 7. 対象外 (Non-Goals)` へ退避・記録する。サテライトの `tasks.md` に既存の `stage:ideation` 行が存在する場合はインラインで `stage:ready` へ置換・昇格し、存在しない場合は `stage:ready` タスク行を新規追加する。
- **2 段階の壁打ち運用 (Tiered Refinement)**:
  - **Tier 1 (Issue 内完結・定型/軽量タスク)**:
    - AI 起票ツールが最初から「修正方針の選択肢（案1: 推奨, 案2: 代替）」をチェックボックス形式（`- [ ] **案 1 (推奨)**` / `- [ ] **案 2**`）で Issue 本文に明記して起票。ユーザーは GitHub の Web 画面上で直接クリックして選択可能。
    - **デフォルト推進ポリシー**: 基本は「案 1 (推奨)」を採用して `tasks.md` に登録し実装を進める。それでも不都合・課題が生じた場合のみ、案 2 の採用や再壁打ちを行う。
    - ユーザーは Issue 内のチェックボックスを選択、またはチャット/コメントで「案1で」と指定するだけで、昇格ツール（`promote_issue.py`）により即座に `tasks.md` へ同期され `stage:ready` へ昇格。
  - **Tier 2 (個別フォロー・複雑/例外タスク)**:
    - 選択肢に該当しない要望や、根本的な設計方針の変更・アーキテクチャ再検討が必要な場合のみ、チャット（IDE/CLI環境）で人間とエージェントが個別に対話して仕様を詰める。

### 3.10 サテライトタスク仕様書 (docs/issues/<TASK_ID>.md) のライフサイクル自動同期と自己修復
- **アーキテクチャ方針 (PM-060: tasks.md / docs/issues / GitHub Issue の 3 者 1:1 同期保証)**:
  - 自律実装パイプラインにおいて、オーケストレーターがタスクの要件・編集対象ファイル（Target Files）を正確に把握できるよう、サテライトの `docs/issues/<TASK_ID>.md` をローカル作業ツリーに永続化する。
  - これにより、夜間バッチ実行時に LLM が推測で無関係なファイル（`ports.py`, `history.py` 等）をルート直下に捏造（ハルシネーション）して空ファイルを作成する問題を恒久遮断する。
- **ライフサイクル連携ポイント**:
  1. **起票時 (`run_review.py`)**:
     - agys レビューによる Issue 起票および `tasks.md` 追記と同時に、初期仕様書（案1/案2含む）を `docs/issues/<TASK_ID>.md` として自動初期配置。
  2. **壁打ち昇格時 (`promote_issue.py`)**:
     - 採用案（案1）の確定仕様を反映し、確定タスク（`concrete_tasks`）を **`## 3. 段階的実装手順 (Step-by-step Execution)`** へ展開、編集対象ファイルを **`## 4. 編集対象ファイル (Target Files)`** へ置換・反映した最新本文で `docs/issues/<TASK_ID>.md`（および GitHub Issue 本文）を自動更新。
     - ※ 3.9節の原則に基づき、独立した重複進捗管理枠（旧 `### 確定実装タスク (Task Checklist)`）は削除し、タスク進捗は `tasks.md` へ一元化する。
  3. **定周期巡回時 (`periodic_review_runner.py`)**:
     - `tasks.md` 内に記載された全タスクを走査し、`docs/issues/<TASK_ID>.md` が欠落しているタスクを検知した場合、GitHub API から Issue 本文を取得して自動インポート（欠落自己修復）。
  4. **Target Files パス解決ガード (`orchestrator_graph.py`)**:
     - `resolve_target_files_against_cwd` において、ファイル名（拡張子込み）完全一致、ステム完全一致を最優先とし、非テストファイルがテストファイル（`tests/test_...`）へ安易に部分一致マッピングされる誤爆を厳格に防止。





