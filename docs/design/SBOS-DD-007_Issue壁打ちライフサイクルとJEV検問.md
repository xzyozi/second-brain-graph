---
title: "Issue 壁打ちライフサイクルと JEV スクリーニング仕様書"
document_type: "detailed_design"
version: "1.5.0"
created_at: "2026-09-25"
updated_at: "2026-11-16"
author: "アーキテクチャチーム / xzyozi"
purpose: "GitHub Issues を唯一の正本 (SSOT) とする自律開発パイプラインの前段に位置する壁打ち・構想フェーズの状態管理ルール、JEVによるスクリーニング・昇格検問仕様、対話型壁打ちスキル仕様、およびラベルベース状態遷移を定義する"
related_documents:
  - "docs/design/SBOS-BD-002_基本設計書.md"
  - "docs/design/SBOS-DD-003_詳細設計書.md"
  - "docs/design/SBOS-DD-006_品質ゲート_レビュー仕様.md"
  - "metadata/templates/issue_template.md"
related_issues:
  - "#70"
  - "#116"
  - "#179"
  - "#203"
---

# 詳細設計書（Issue 壁打ちライフサイクルと JEV スクリーニング仕様）
**GitHub Issues SSOT 準拠の最上流フェーズ状態管理・重複検知・ライフサイクル遷移アーキテクチャ**

| 項目           | 内容                                                                                                                                                                     |
| :------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 文書番号       | SBOS-DD-007                                                                                                                                                              |
| ドキュメント名 | Issue 壁打ちライフサイクルと JEV スクリーニング仕様書                                                                                                                    |
| 版数           | Rev.1.5 (Issue #203: 母艦内対話型壁打ちスキル `issue-refinement` 新設、および `promote_issue.py` の母艦対応・構造チェック・JEV 出口検問統合)                           |
| 改訂日         | 2026-11-16                                                                                                                                                               |
| 作成日         | 2026-09-25                                                                                                                                                               |
| 作成者         | アーキテクチャチーム / xzyozi                                                                                                                                            |
| 対象           | `tools/screen_issues.py`, `tools/lifecycle/close_stale_issues.py`, `tools/score_issues.py`, `tools/promote_issue.py`, `tools/lifecycle/periodic_review_runner.py`, `tools/backends/jev_adapter.py`, `tools/workspace/github_issues.py`, `.agents/skills/issue-refinement/SKILL.md`, `.github/workflows/cleanup-stale-ideation.yml` |

---

## 1. 概要と目的

本仕様書は、GitHub Issues を唯一の正本（SSOT）として直接参照・更新する自律開発パイプライン（`orchestrator_graph.py` / `score_issues.py`）の前段に位置する **「最上流：壁打ち・構想フェーズ（Ideation Phase）」** の状態管理ルール、および **JEV による決定論的スクリーニング仕様** を定義します。

### 解決する課題
1. **実装キューへの混入防止**:
   未確定なアイデアやドラフト段階の Issue（`stage:ideation`）が、スコアリング（`score_issues.py`）や自律実装の対象に混入してエージェントが意図せず実装を開始してしまうリスクを完全遮断する。
2. **重複・車輪の再発明の早期検知**:
   全 Issue（Open / Closed 双方）から、類似した課題や過去の議論を JEV で検知し、重複起票を防ぐ。
3. **長期放置 Issue の自動整理**:
   構想（`stage:ideation`）のまま進展のない Issue を 30 日で自動クローズし、バックログの肥大化・陳腐化を防ぐ。
4. **二元管理の排除（GitHub Issues SSOT）**:
   ローカルの `tasks.md` や `docs/issues/<TASK_ID>.md` との二重保存・同期処理を廃止し、タスク状態・仕様・優先度メタデータを GitHub Issues に一本化する。

---

## 2. ラベル体系とステートマシン

Issue の状態を以下の 4 つの `stage:*` ラベルと Open/Closed 状態で厳格に分離管理します。

| ラベル              | 役割                                     | スコアリング / 自律実行対象    |
| :------------------ | :--------------------------------------- | :----------------------------: |
| `stage:ideation`    | 構想・壁打ち中。要件定義やコメント議論中 |          **完全除外**          |
| `stage:ready`       | 仕様確定・着手可能。受入条件(AC)確定済み | **対象（スコアリング・実装）** |
| `stage:in-progress` | エージェントまたは開発者が実装・PR作成中 |           実行中管理           |
| `stage:done`        | PR マージ完了・タスク終了                |         完了アーカイブ         |

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
        ▼ (ユーザー承認 / promote_issue.py: stage:ready 付与)
 [score_issues.py (GitHub Issues SSOT 評価)]
        │
        ▼ (着手: stage:in-progress 付与)
 [自律実装パイプライン (orchestrator_graph)]
        │
        ▼ (PR 作成 / マージ: stage:done 付与)
 [完了]
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

### 3.2 放置 Issue 自動クローズ (`tools/lifecycle/close_stale_issues.py`)
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

### 3.4 スコアリングフィルタと GitHub Issues SSOT 評価 (`tools/score_issues.py`)
- 共通取得層 `tools/workspace/github_issues.py` を経由して Open な GitHub Issues を直接取得し、ラベル（`stage:ready`、優先度、テーマ、ブロッカー等）と本文メタデータから優先度スコアを算出する。
- `stage:ideation`、`draft`、あるいは `stage:ready` が付与されていない Issue は候補選定から確実にスキップ除外する。
- テスト実行時は環境変数 `SBOS_GITHUB_ISSUES_FIXTURE` またはインメモリフィクスチャ（`use_issue_fixture`）を用いて、オフライン・モック環境で決定論的に検証可能とする。

### 3.5 agys サテライト自律レビュー＆Issue起票スキル (`satellite-ideation-reviewer`)
- **アーキテクチャ方針 (PM-058: 独立スキル化と完全自動起票)**:
  - Antigravity CLI ヘッドレス実行（`agys` / `agy -p`）を活用し、サテライトリポジトリ（`projects/<name>/`）のコードをテーマ別（セキュリティ、エッジケース処理、関心事の分離）に自律レビューする独立スキル（`.gemini/skills/satellite-ideation-reviewer/`）を運用。
  - **母艦保護**: 母艦自身（`second-brain-graph`）はレビュー対象外として厳格に遮断。
  - **Read-only 担保**: プロンプト制約と JSON 構造化出力パースにより作業ツリーへの変更を完全防止。
  - **JEV スクリーニングは据え置き**: 本書の JEV（重複・カテゴリ検知、`screen_issues.py`）は引き続き Ollama に直接接続する（SBOS-DD-005 §1.1）。
  - **ステータス不問の重複チェック**: `gh issue list --state all` で全件照合。Open 重複はスキップ、Closed 重複は再発注記を付与して例外起票。
  - **開発対象との影響隔離**: 起票する Issue には必ず `stage:ideation` を付与し、`stage:ready` が付与されるまでスコアリングおよび自律実行の対象外として安全に保留。ローカルファイル（`tasks.md` / `docs/issues/*.md`）への書き込みは行わない。
  - **起票上限 (Cap)**: 重要度順（High > Medium > Low）にソートし、1実行あたり最大3件（設定可能）に制限。

### 3.6 サテライト初期化時のラベル自動同期と自己修復ガード (`tools/add_project.py`, `run_review.py`)
- **プロジェクト登録時の自動同期**: `tools/add_project.py` の `setup_labels` をデフォルト有効化（`True`）とし、サテライト初期化時に GitHub 上へ標準ステージラベル（`stage:*`）およびテーマラベル（`theme:*`）を自動作成。新規初期化時は `docs/project.json` のみを配置し、`tasks.md` や `docs/issues/_template.md` は生成しない。
- **自己修復（Ensure Labels）ガード**: `run_review.py` において、Issue 起票直前にリポジトリ側のラベル実在を確認し、未登録の場合は即座に `gh label create` を自動実行して起票失敗を防止。

### 3.7 母艦一元管理の標準 Issue テンプレートと決定論的 ID 規則 (`metadata/templates/issue_template.md`)
- **アーキテクチャ方針 (PM-059 / Epic #179: Issue 仕様の母艦一元化と SSOT 統合)**:
  - Issue の構造を統一するため、母艦の `metadata/templates/issue_template.md` を標準テンプレートとして管理する。
  - **GitHub Issues SSOT と決定論的 ID 規則**:
    - タスク仕様・ステータス・進捗管理の正本はすべて GitHub Issue（本文・`stage:*` ラベル・Open/Closed 状態）に一元化する。
    - タスク ID は GitHub Issue 番号から決定論的に **`{PROJECT_KEY}-{issue_number:04d}`**（例: `TFG-0005`）として導出・解決する（`tools/workspace/metadata_store.py` / `tools/workspace/github_issues.py`）。
    - 起票時（`stage:ideation`）から壁打ち完了（`stage:ready`）への遷移、実装着手（`stage:in-progress`）、完了（`stage:done`）まで、すべて GitHub Issue 上の更新のみで完結する。
- **0〜8章 標準 Issue スキーマ**:
  - `## 0. メタ情報 (Scope & Impact)`: 影響範囲、既存コード依存、関連Issue
  - `## 1. 概要・背景`: タスクの背景・目的（課題詳細を含む。PRサマリーとしても抽出）
  - `## 2. 仕様および要求事項 (修正方針の検討)`: 修正方針の選択肢（案1 推奨 / 案2 代替）。合意された方針が `stage:ready` 昇格および実装タスクの input となる
  - `## 3. 段階的実装手順 (Step-by-step Execution)`: Phase 1 (本体), Phase 2 (テスト)。壁打ち昇格時は確定タスク（`concrete_tasks`）が具体的な実行ステップとして展開・反映される
  - `## 4. 編集対象ファイル (Target Files)`: 対象ファイルパス（オーケストレーターが GitHub Issue 本文から自動抽出）。壁打ち昇格時に確定方針に応じた対象ファイルリストで更新される
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
- **GitHub Issues SSOT における役割分離**:
  - **状態管理の一元化**: タスク全体のステータス（ToDo / Ready / In Progress / Done）は GitHub Issues の `stage:*` ラベルおよび Open/Closed 状態に一元化し、Issue 本文内に重複する独立進捗チェック枠は設けない。
  - **確定タスクの役割と反映先**: 壁打ちで確定した具体的な作業手順（実行ステップ）は、オーケストレーターへの実装指示情報として **`## 3. 段階的実装手順 (Step-by-step Execution)`** セクション内に展開・反映する。
  - **修正方針の決定**: Issue の `## 2. 仕様および要求事項` は「修正方針の検討・選択肢提示（案1 推奨 / 案2 代替）」とし、合意された方針が仕様確定の直接の input となる。
  - **昇格時の状態遷移 (`tools/promote_issue.py`)**: 壁打ち完了時は、選定された案のチェックボックスを `[x]` に更新し、選ばれなかった案を `## 7. 対象外 (Non-Goals)` へ退避した最新本文で GitHub Issue 本文を更新するとともに、`stage:ideation` を外して `stage:ready` ラベルを付与する。
- **2 段階の壁打ち運用 (Tiered Refinement)**:
  - **Tier 1 (Issue 内完結・定型/軽量タスク)**:
    - AI 起票ツールが最初から「修正方針の選択肢（案1: 推奨, 案2: 代替）」をチェックボックス形式（`- [ ] **案 1 (推奨)**` / `- [ ] **案 2**`）で Issue 本文に明記して起票。ユーザーは GitHub の Web 画面上で直接クリックして選択可能。
    - **デフォルト推進ポリシー**: 基本は「案 1 (推奨)」を採用して昇格・実装を進める。それでも不都合・課題が生じた場合のみ、案 2 の採用や再壁打ちを行う。
    - ユーザーは Issue 内のチェックボックスを選択、またはチャット/コメントで「案1で」と指定するだけで、`promote_issue.py` により即座に GitHub Issue 本文が確定し `stage:ready` へ昇格する。
  - **Tier 2 (個別フォロー・複雑/例外タスク)**:
    - 選択肢に該当しない要望や、根本的な設計方針の変更・アーキテクチャ再検討が必要な場合のみ、チャット（IDE/CLI環境）で人間とエージェントが個別に対話して仕様を詰める。

### 3.10 自律実行・定期巡回・環境診断の GitHub Issues SSOT 連携
1. **タスク一覧取得・実行 (`tools/core/orchestrator_graph.py`)**:
   - `get_ready_issues()` は `tools/workspace/github_issues.py` を通じて `stage:ready` の Open Issue を直接取得し、決定論的タスク ID（`{PROJECT_KEY}-{issue_number:04d}`）でタスクを構築する。
   - 実行中（`stage:in-progress` 遷移）・完了時（`stage:done` 遷移、既済コミット無しスキップ時のラベル更新）は GitHub Issues のラベル更新のみを行い、ローカル `tasks.md` には書き込まない。
   - `Target Files` 解決は GitHub Issue 本文から直接行い、`resolve_target_files_against_cwd()` でファイル名完全一致・ステム完全一致を最優先として実在パスへ解決する。
2. **定周期巡回 (`tools/lifecycle/periodic_review_runner.py`)**:
   - 各サテライトについて `evaluate_remote_issue_statuses()` で GitHub Issues (SSOT) の Open/Closed および `stage:*` 分布を集計・評価し、コード差分がある場合は `run_review.py` により `stage:ideation` Issue を直接起票する。
3. **環境診断 (`tools/doctor.py`)**:
   - `check_github_issues_access()` で GitHub CLI / Issues SSOT への疎通を診断し、`check_legacy_local_files()` で非推奨となった `docs/tasks.md` / `docs/issues/` の残存有無を検査する（ローカルファイル不在時は正常 `OK` 扱い）。

### 3.11 対話型壁打ちスキルと JEV 入口・出口検問 (Issue #203)
Tier 2（対話による要件・設計詰め）を標準化するため、母艦リポジトリに専用スキル **`.agents/skills/issue-refinement/SKILL.md`** を配置し、壁打ち工程の入口・出口に JEV 検問を統合します。

#### 1. 既存スキルとの役割分離・配置方針
| スキル | 配置パス | 実行方式・対象 | 役割 |
| :--- | :--- | :--- | :--- |
| `issue-refinement` | `.agents/skills/issue-refinement/SKILL.md` | Antigravity 標準探索パスによる対話ロード（母艦・サテライト双方） | `stage:ideation` Issue の対話壁打ち・設計精査・`stage:ready` 昇格 |
| `satellite-ideation-reviewer` | `.gemini/skills/satellite-ideation-reviewer/` | `periodic_review_runner.py` 等からのパス直指定バッチ起動（サテライト専用） | コード巡回レビューによる `stage:ideation` Issue の自律起票 |

#### 2. 壁打ち実行フロー（Phase 0〜4）
1. **Phase 0（対象リポジトリ特定・ガード）**:
   - `metadata/.project-registry.json`・サテライト `docs/project.json`・`git rev-parse --show-toplevel`・`gh repo view` を照合し、対象（母艦 `xzyozi/second-brain-graph` または登録済みサテライト）を一意特定する。曖昧な場合は作業を進めずユーザーへ確認する。
2. **Phase 1（段階的 `docs/`・規約読み込み）**:
   - **Step 1（ルート規定）**: `docs/project.json`, `README.md`, `CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`, `pyproject.toml`（存在するもの）から基本規約・テスト/CI 契約を把握する。
   - **Step 2（設計索引）**: `docs/README.md`・`docs/design/README.md` 等から目次を把握し、全件丸読みによるコンテキスト圧迫を避ける。
   - **Step 3（関連精読）**: 当該 Issue に関係する設計書および実ソース・テストのみを精読する。なお、過去の `legacy/` 資産や移行前ローカルファイル（`docs/tasks.md`, `docs/issues/`）には引きずられず、現行 GitHub Issues と現行 `docs/` を正本として扱う。
3. **Phase 2（JEV 入口検問：重複・既解決確認）**:
   - 壁打ち開始前に `tools/screen_issues.py`（`verify_duplicate_with_jev()`）で Open / Closed の既存 Issue との重複・類似・既対応有無を検査する（Ollama 不在時は既存のレキシカル Jaccard フォールバックで動作）。
4. **Phase 3（対話壁打ち・仕様確定）**:
   - `agy` 本体が論点を構造化し、案 1（推奨）／案 2（代替）を提示してユーザーと合意形成する。
5. **Phase 4（構造チェック・JEV 出口検問・`stage:ready` 昇格）**:
   - `metadata/templates/issue_template.md` 準拠（0〜8 章）に本文を確定した上で、`tools/promote_issue.py` を通じて昇格する。

#### 3. `tools/promote_issue.py` の母艦対応・構造チェック・JEV 出口検問契約
1. **母艦リポジトリ解決の閉域化**:
   - `metadata/.project-registry.json` に母艦を登録したり、サテライト判定として共用される `tools/workspace/metadata_store.py`（`resolve_project_from_cwd()`, `resolve_target_spec()`）を変更したりせず、母艦エイリアス（`second-brain-graph`, `xzyozi/second-brain-graph`, `SBOS`, および母艦配下かつ `projects/` 外 CWD フォールバック）の解決ロジックは `tools/promote_issue.py` 内に閉じて実装する。
2. **Python 決定論的構造チェック**:
   - 表記の軽微な揺れを許容しつつ、主要セクション（`## 1.`, `## 2.`, `## 3.`, `## 4.`, `## 8.`）の存在、`## 4. 編集対象ファイル` が空でないこと、およびテンプレート初期値（`path/to/file.py`, `〇〇`, `[最小限・安全な改修アプローチ` 等の未置換文字列）が残存していないことを検証する。
3. **JEV 出口検問（`verify_plan_conformance()` 共用）**:
   - **抽出マッピング**:
     - `issue_id`: 母艦は `second-brain-graph#<num>`、サテライトは `{PROJECT_KEY}-{num:04d}`（キー未解決時は `{repo}#{num}`）
     - `instruction`: `## 1. 概要・背景` ＋ `## 2.` の**採用案のみ**（非採用案や `## 7.` 退避内容を混入させない）
     - `impl_plan`: `## 3. 段階的実装手順`（および存在する場合は `## 8. 完了定義`）
     - `target_files`: `## 4. 編集対象ファイル` から抽出した実パス一覧
   - **ソフトゲート契約**:
     - デフォルトでは `REJECTED` (`is_valid=False`) 時に昇格を中断し、JEV に渡した要約（抽出 `target_files` および手順プレビュー）と `--skip-jev` による上書き手段をエラーログへ出力する。
     - `--skip-jev` 指定時は JEV 検問をスキップして昇格を許可する（構造チェックは維持）。
     - `--dry-run` 実行時も構造チェックと JEV 出口検問を実施し、判定結果（PASSED / REJECTED / bypassed）を事前確認できるようにする（GitHub Issue の実更新は行わない）。
     - Ollama 不在・接続失敗・`INCONCLUSIVE` 時は既存の fail-open 契約を維持し、作業をブロックしない。

---

## 4. 改訂履歴 (Change Log)

| 版数    | 改訂日     | 変更者               | 変更内容・変更理由 (Why)                                                                                                                                                                                                    |
| :------ | :--------- | :------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rev.1.0 | 2026-09-25 | アーキテクチャチーム | 新規作成（初版制定: stage ラベル状態マシン、JEV スクリーニング、放置 Issue 自動クローズ仕様）                                                                                                                               |
| Rev.1.1 | 2026-10-02 | xzyozi               | PM-060 追記: docs/issues/<TASK_ID>.md 自動同期・自己修復ライフサイクルの新設。3.9節/3.10節の確定タスク・Target Files・進捗管理の責務分離（SSOT）と仕様整合性の明確化、YAML Frontmatter および改訂履歴の追記 |
| Rev.1.2 | 2026-11-04 | xzyozi               | Epic #116 (agy移行) との関係、JEVスクリーニング据え置き方針を追記 (3.5節)                                                                                                                                                  |
| Rev.1.3 | 2026-11-06 | xzyozi               | Issue #70 実装完了確認: `issue_spec_manager.py`、`promote_issue.py`、`periodic_review_runner.py`、`orchestrator_graph.py` の動作検証・テスト全件合格(23件)および関連Issueを反映                                             |
| Rev.1.4 | 2026-11-14 | xzyozi               | Epic #179 (#191〜#194) 完了に伴い、`tasks.md` / `docs/issues/<TASK_ID>.md` 二元管理・`issue_spec_manager.py` を廃止し、GitHub Issues SSOT・決定論的タスク ID 規則 `{PROJECT_KEY}-{issue_number:04d}` へ整合改訂              |
| Rev.1.5 | 2026-11-16 | xzyozi               | Issue #203 に対応: `.agents/skills/issue-refinement/SKILL.md`（対話型壁打ち・段階的 `docs/` 読込・JEV 入口/出口検問）仕様と `tools/promote_issue.py` の母艦対応・構造チェック・`--skip-jev` 契約を追記、実パス整合 |
