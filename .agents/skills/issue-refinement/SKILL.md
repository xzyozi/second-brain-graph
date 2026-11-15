---
name: issue-refinement
description: >
  second-brain-graph（母艦）および登録済みサテライトリポジトリの stage:ideation Issue を対象に、
  リポジトリ特定・段階的 docs 読み込み・JEV 入口/出口検問・対話による論点整理を経て
  0〜8章テンプレート形式で仕様確定し stage:ready へ昇格させる壁打ち専用スキル。
---

# Skill: issue-refinement（対話型 Issue 壁打ち・仕様確定・JEV 検問昇格）

本スキルは、`second-brain-graph`（母艦）および `tools/add_project.py` により登録されたサテライトリポジトリの `stage:ideation` Issue を人間との対話（`SBOS-DD-007` §3.9 Tier 2 / §3.11）によって仕様確定し、`stage:ready` へ安全に昇格させるための手順を定義します。

※ 本スキルは**要件確定・昇格フェーズ専用**です。実装パイプライン（`tools/core/orchestrator_graph.py` / `tools/run_task.py`）の起動や、サテライトプロダクトコードの無断改変は行いません。

---

## 実行手順

### Phase 0: 対象リポジトリ特定・ガード
1. 現在のワークスペースが母艦または登録済みサテライト配下であることを確認する（`git rev-parse --show-toplevel`、`metadata/.project-registry.json` または `docs/project.json` の存在チェック）。該当しない無関係なリポジトリの場合は案内して停止する。
2. ユーザーの指定（Issue URL / タスク ID 例: `TFG-0005` / `--project` + `#番号` / 番号のみ）から対象リポジトリを一意特定する：
   - **母艦自身**: `xzyozi/second-brain-graph`（母艦ルート直下での指定・明示指定時）
   - **サテライト**: `metadata/.project-registry.json` および `projects/<name>/docs/project.json` を照合
   - **曖昧な場合**: 番号のみで母艦／サテライトが切り分けられない場合は、推測せずユーザーへ確認する。

### Phase 1: 段階的コンテキスト読み込み（`docs/`・規約・関連コード）
対象リポジトリが特定できたら、全件丸読みでコンテキストを圧迫しないよう以下の順で段階的に読む：
1. **ルート規定（存在するもののみ）**:
   - `docs/project.json`（`base_branch`, `test_command`, `allowed_new_file_globs`, `language`）
   - `README.md`, `CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`, `.agent/rules/`, `pyproject.toml`
2. **ドキュメント索引**:
   - `docs/README.md`, `docs/design/README.md` や `docs/` 配下のファイル一覧を確認し、全体構成と設計ルールを把握する。
3. **Issue 関連の設計書・コード精読**:
   - 対象 Issue のテーマに関係する設計書（例: `docs/design/SBOS-DD-007_Issue壁打ちライフサイクルとJEV検問.md`, `docs/ARCHITECTURE_OVERVIEW.md` 等）および対象モジュール・関連テストのみを精読する。
   - **ノイズ除外原則**: 仕様・状態管理の正本（SSOT）は現行の GitHub Issues と現行 `docs/`・`docs/project.json` とし、`legacy/` 配下や過去の移行前ローカルファイルには引きずられない。

### Phase 2: JEV 入口検問（重複・既解決事前チェック）
壁打ちを始める前に、`tools/screen_issues.py` を用いて Open / Closed 双方の既存 Issue との重複・既解決有無を確認する（Dry-run / コメント反映なし）：
```powershell
uv run python tools/screen_issues.py --issue <ISSUE_NUM> --repo <OWNER/REPO>
```
- Ollama 未起動時は既存のレキシカル Jaccard フォールバックで動作する。
- 重複候補や既解決済みの類似 Issue が検出された場合は、壁打ち開始前にユーザーへ提示し、続行・統合・クローズの判断を仰ぐ。

### Phase 3: 対話壁打ち・仕様確定（`agy` 本体）
1. 対象 Issue 本文と調査した設計書・実コードのギャップを洗い出し、判断が必要な**論点**を絞って提示する。
2. 各論点について、既存の設計制約と整合する **案 1（推奨）** と **案 2（代替）**、および実コード上の落とし穴（対象ファイル・境界条件・既存テストへの影響）を整理し、人間と対話して方針を合意する。
3. 合意結果を `metadata/templates/issue_template.md`（0〜8 章構成）に沿って整理する：
   - `## 1. 概要・背景`: 背景・目的を明確化
   - `## 2. 仕様および要求事項`: 採用案を `[x]`、非採用案や論点ごとの確定内容・理由を明記
   - `## 3. 段階的実装手順`: 具体的な実装ステップ・検証項目へ展開
   - `## 4. 編集対象ファイル`: 調査済みの正確な相対パスのみを列挙
   - `## 5. ドメイン知識・技術上の落とし穴` / `## 6. 設計制約`: 実コードから判明した制約を反映
   - `## 7. 対象外 (Non-Goals)`: 非採用案とスコープ外事項を退避
   - `## 8. 完了定義`: プロジェクトの実情に応じた検証・CI 条件を記載

### Phase 4: 構造検証・JEV 出口検問・`stage:ready` 昇格
1. 確定した本文案を GitHub Issue へ反映する前に、まずプレビュー＆検問を実行する：
   ```powershell
   uv run python tools/promote_issue.py --project <PROJECT_OR_REPO> --issue <ISSUE_NUM> --dry-run
   ```
   （※必要に応じて `gh issue edit <ISSUE_NUM> --repo <OWNER/REPO> --body-file <確定本文>` で 0〜8 章を最新化した後、`tools/promote_issue.py` の `--approach` / `--task` / `--target-file` を指定して最終昇格・JEV 出口検問を通す）
2. `tools/promote_issue.py` による **Python 構造チェック** と **JEV 出口検問 (`verify_plan_conformance`)** の結果を確認する：
   - **構造チェック NG**: 欠落セクション、空の Target Files、またはテンプレート未置換文字列を修正する。
   - **JEV REJECTED**: 検問に出力された抽出要約と対象ファイルを確認し、スコープ逸脱・YAGNI 違反があれば修正する。誤検知であり人間が明示的に承認した場合のみ `--skip-jev` を使用する。
3. 問題なければ `--dry-run` を外して実行し、`stage:ideation` → `stage:ready` へ昇格して完了報告を行う。

---

## 常時制約
- 対象外の別リポジトリに対して昇格・編集操作を行わない。
- `tools/core/orchestrator_graph.py` および `tools/run_task.py` を自動起動しない。
- サテライト側のプロダクトコード（`src/`, `tests/` 等）は壁打ち中に編集しない（調査読込のみ）。
- 認証情報・トークン・秘密情報を出力・Issue 本文へ記載しない。
- Ollama / JEV 未起動時でも、既存の fail-open / フォールバック契約を破壊しない。
