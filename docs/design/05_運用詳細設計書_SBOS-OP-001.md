# 運用詳細設計書（定常運用・ランブック・トラブルシューティング）
**Second Brain OS 日次サイクル・LangGraph エントリポイント・障害対応ランブック**

| 項目 | 内容 |
| :--- | :--- |
| 文書番号 | SBOS-OP-001 |
| 版数     | Rev.4.5（review_rounds 監査ログ構造 §2.1 完全整合版）|
| 改訂日   | 2026年7月29日 |
| 作成日 | 2026年7月27日 |
| 対象読者 | 運用エンジニア / プロジェクトリード / DevOpsエンジニア |
| 関連文書 | SBOS-BD-002（基本設計書 Rev.4.6）、SBOS-DD-003（詳細設計書 Rev.4.8）、SBOS-ENV-001（環境構築仕様書 Rev.4.6）、SBOS-PM-005（課題一覧 Rev.2.7） |

---

## 1. 日次・定常運用サイクル仕様

本システムの強みは、夜間や朝のバッチ処理による自動優先度計算と、人間の対話承認を組み合わせたハイブリッド運用にある。以下に標準的な日次運用サイクルを規定する。

### 1.1 朝の自動評価バッチ（cron / Task Scheduler 連携）
毎朝 07:00 JST に、母艦から全衛星のタスクを自動スキャンしてスコアリングおよびブロッカー検出を行うバッチジョブを実行する。

#### crontab 設定例 (Linux / macOS)
```bash
# m h  dom mon dow   command
0 7 * * * cd ~/second-brain && /home/user/.local/bin/uv run python tools/score-issues.py && /home/user/.local/bin/uv run python tools/check-blockers.py && /home/user/.local/bin/uv run python tools/notify.py --event daily_summary > ~/second-brain/tools/.cache/daily_batch.log 2>&1
```

#### スコアリング計算数式と判定根拠 (`score-issues.py`)
全 Issue に対し、以下の4軸数式を適用して 0〜100点 のスコアを算出する。
$$\text{Total} = (P \times 3.0) + (F \times 2.0) + (E \times 1.5) + (D \times 2.0)$$
$$\text{Score} = \frac{\text{Total}}{42.5} \times 100$$
- **優先度 ($P$, 1〜5):** `critical`/`urgent`=5, `high`=4, `medium`=3, `low`=2, `none`=1
- **鮮度 ($F$, 0〜5):** 最終更新または追加日 (`added:`) から 7日以内=5, 30日以内=3, 90日以内=1, 超=0
- **工数軽さ ($E$, 1〜5):** `estimate:Xh` メタデータから動的パース：1h=5, 4h=4, 8h=3, 16h=2, それ以上=1 (未指定は3.0フォールバック)
- **依存解決度 ($D$, 0〜5):** `blockedby` ブロッカー数：0個=5, 1個=3, 2個=1, 3個以上=0（先行タスク未完了なら自動的に順位低下）

---

### 1.2 LangGraph CLI による計画承認と Issue 実行 (`orchestrator_graph.py`)

Rev.4.0 より OpenCode CLI は廃止され、LangGraph ベースのエントリポイント `tools/orchestrator_graph.py` を用いて日次運用を起動する。

1. **実行計画の呼び出し:**
   ターミナルで以下のコマンドを実行する。システムはバッチが計算したキャッシュ（`priority-cache.json`）を読み込み、実行可能な上位3件を提示する。
   ```bash
   uv run python tools/orchestrator_graph.py orchestrate
   ```
   ```text
   【本日の実行計画 (推奨上位3件)】
   1位: [EC-012]「決済例外処理ロールバックハンドラの統合」（スコア: 94.2）
        → 理由: 優先度highであり、先行するAPI仕様書[EC-010]が完了して依存が解消されたため。
   2位: [FX-005]「LightGBMバックテスト指標推移表の追加」（スコア: 88.0）
   3位: [EC-015]「ユーザープロファイルアイコンのS3アップロード」（スコア: 81.5）

   実行するには: uv run python tools/orchestrator_graph.py execute --issue-id EC-012
   ```

2. **自律グラフの起動 (`execute` コマンド):**
   運用者が以下のコマンドを実行すると、`orchestrator_graph.py` (StateGraph) が起動し、自動的にノード間を遷移する。
   ```bash
   uv run python tools/orchestrator_graph.py execute --issue-id EC-012
   ```
   - ① `plan_node` (LiteLLM / Planner による要件指示書生成)
   - ② `code_node` (Aider による衛星コード編集 `--no-auto-commits`)
   - ③ `lint_node` (Ruff 高速静的解析、失敗時はエラーログを蓄積し `code_node` へ復帰)
   - ④ `test_node` (pytest 実行、失敗時はエラーログを蓄積し `code_node` へ復帰)
   - ⑤ `review_node` (LiteLLM / Reviewer 監査 ＋ Reviewdog アノテーション表示)
   - ⑥ `done_node` (`tasks.md` を完了 `[x]` 更新し、`execution_history.json` へ成果記録)
   
   > **注意:** `orchestrator_graph.py` は衛星内で `git commit` を自動実行しない。成果物の最終確認後、人間が手動で `git add && git commit` を行う。

---

## 2. 監査トレーサビリティとログ管理

### 2.1 実行履歴ログ (`tools/.cache/execution_history.json`)
各タスクの実行完了（または B7 エスカレーション）時にアトミックに記録される正本 JSON スキーマ (`DD-003 §4.1.1` 準拠)。
各試行回数は `lint_round` / `test_round` / `review_round` フィールドに記録され、各ラウンドのレビュー判定および指摘コメント履歴は `review_rounds: [{round, verdict, comments}]` 配列から時系列で全件参照・監査できる。

---

## 3. トラブルシューティング・ランブック（障害対応フロー）

### ケース1: LLM 応答パース失敗 (`JSON抽出失敗` / パースエラー)
- **症状:** `llm_client.py` (LiteLLM) で `JSON抽出失敗` が出力され、`changes_requested` にフォールバックする。
- **対処:**
  - `rm -f tools/.cache/priority-cache.json tools/.cache/blocked.json` でキャッシュクリア。
  - 対象 Issue の説明文が長すぎる場合は、タスクを分割して指示文を簡潔にする。

### ケース2: テスト/静的解析の継続失敗 (`max_round` 到達)
- **症状:** Aider による修復が `max_round`（デフォルト3回）連続で失敗し、`escalate_node` に遷移して `final_status: "FAILED_B7"` として記録される。
- **対処:**
  - `orchestrator_graph.py` の実行ログから直近の pytest / Ruff エラーログを確認。
  - テストコードや型定義の直接編集が必要な場合は、人間が `projects/<name>/` を編集する。

### ケース3: Aider CLI / LiteLLM 推論のタイムアウト
- **症状:** `AiderRunError: Aider実行がタイムアウトしました (timeout=600)` が発生。
- **対処:**
  - `nvidia-smi` で VRAM 使用量を確認。
  - `tools/aider_runner.py` または `tools/llm_client.py` の `timeout` パラメータを延長する。

### ケース4: Aider 差分キャンセルの手動復旧
- **症状:** Aider が意図しない広範囲の変更を行った。
- **対処:**
  - `--no-auto-commits` により変更はワーキングツリーの未コミット差分として保持されているため、対象衛星ディレクトリで以下を実行して変更を破棄する。
  ```bash
  cd projects/<target-project>
  git checkout -- .
  git clean -fd
  ```

### ケース5: レビュー/テスト/lint試行上限到達 (B7 ブロッカー)
- **症状:** 朝の自動スキャンバッチで `tools/.cache/blocked.json` に `B7` ブロッカーとして登録される。
- **監査項目:**
  - `metadata/projects/<project-key>/tasks.md` 内の該当 Issue 直下に記録されたメタデータコメント `<!-- round:3 max_round:3 status:FAILED_B7 -->` を確認。
  - `tools/.cache/execution_history.json` を参照し、`lint_round` / `test_round` / `review_round` のどれで上限に達したかを特定する。過去の試行コメントは `review_rounds: [{round, verdict, comments}]` 配列から時系列で監査・追跡する。
- **復旧手順:**
  1. 人間が原因コード・要件定義・テストコードを修復する。
  2. `max_round:3` は変更せずに、`tasks.md` 内のメタデータを `<!-- round:0 max_round:3 status:PENDING -->` へ手動リセットする。
  3. `uv run python tools/orchestrator_graph.py execute --issue-id <ISSUE_ID>` を再実行する。

---

## 4. 中長期メンテナンス・モデル定期更新ランブック

### 4.1 新モデルベンチマーク評価プロセス
1. `uv run python tools/orchestrator_graph.py` によるダミー指示書テスト。
2. Aider によるリファクタリングマージテスト。
3. Reviewer による監査厳密性テスト。

### 4.2 ロールバック（切り戻し）手順
```bash
# 1. tools/llm_client.py のモデル指定を安定版へ戻す
git checkout ~/second-brain/tools/llm_client.py

# 2. 不安定モデルの削除とキャッシュクリア
ollama rm <unstable-model-tag>
rm -f tools/.cache/priority-cache.json tools/.cache/blocked.json
```

---

## 5. リポジトリバックアップおよび災害復旧 (DR) ガイド

### 5.1 バックアップ手順

#### Linux / macOS (Bash)
```bash
#!/bin/bash
BACKUP_DIR="/mnt/backup/second-brain-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
tar --exclude="tools/.cache" --exclude=".venv" -czf "$BACKUP_DIR/second-brain-root.tar.gz" -C ~/ second-brain
```

#### Windows Native (PowerShell / 汎用パス)
```powershell
$DateStr = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = "C:\backup\second-brain-$DateStr"
New-Item -ItemType Directory -Path $BackupDir -Force
$BaseDir = "$Home\second-brain"

Compress-Archive -Path "$BaseDir\*" -DestinationPath "$BackupDir\second-brain-root.zip" -Exclude "*.venv*", "tools\.cache\*"
Get-ChildItem -Path "$BaseDir\projects" -Directory | ForEach-Object {
    if (Test-Path "$($_.FullName)\.git") {
        Compress-Archive -Path "$($_.FullName)\*" -DestinationPath "$BackupDir\proj-$($_.Name).zip" -Exclude "*.venv*", "node_modules*", "__pycache__*"
    }
}
```