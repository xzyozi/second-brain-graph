# YAMLベース共通設定基盤仕様書 (`models.yaml`, `prompt.yaml`, `tag.yaml`)

- **作成日**: 2026-09-19
- **対象コンポーネント**: `tools/config_loader.py`, `config/*.yaml`
- **関連要件**: Issue #39 (`[config] YAMLベースの共通設定基盤および Pydantic Config ローダーの構築`)
- **検証テスト**: `tests/test_config_loader.py` (全16ケースパス)

---

## 1. 概要と背景

従来の JSON 形式設定（`config/models.json`）では、設定パラメータの意図や VRAM マージンの選定理由に関するコメントを残すことができませんでした。
また、LLM ノードのシステムプロンプトや、タスク種別判定（`[bug]`, `fix:` 等）のルールが Python コード内にハードコードされており、保守性・他プロジェクトへの適応性の課題となっていました。

本機能により、設定ファイルを **YAML 形式（コメント記述可能）** に統一し、以下の 3 領域に責務を分離した共通設定基盤を構築しました。

---

## 2. 構成ファイルと責務分離

| 設定ファイル | 主な管理対象 | 提供されるメリット |
| :--- | :--- | :--- |
| **`config/models.yaml`** | ・モデルハイパーパラメータ (`temperature`, `max_tokens`)<br>・Aider 自動編集エンジン設定 (`timeout`, `edit_format`)<br>・GPU 排他リース (`mode: exclusive`)<br>・バックエンドプロファイル (`ollama` / `llama_server`) | ・各モデルの推奨コンテキスト長や VRAM 消費量の根拠をコメントとして永続化<br>・既存 `models.json` からの完全移行（後方互換フォールバック機能付き） |
| **`config/prompt.yaml`** | ・`planner`: 実装計画立案 (`spec_draft_system`)<br>・`coder`: 出力規則・Read-only制約・2段階実装戦略<br>・`advisor`: テスト失敗分析 (`test_feedback_system`)<br>・`reviewer`: コード監査・テスト自作自演重点レビュー | ・コードを変更することなく、プロンプトの調整・改善が可能<br>・エージェントの行動規約やフォーマット規約を一元管理 |
| **`config/tag.yaml`** | ・タスク種別 (`read_only_test_tasks`, `feature_tasks`)<br>・GitHub ラベル正規化マッピング (`label_mappings`)<br>・フォールバック用シグナルリスト (`fallback_keyword_signals`)<br>・アサーション監視パターン (`protected_assertion_patterns`, `forbidden_skip_patterns`) | ・プロジェクトごとのラベル差異（例: `defect` や `patch`）を設定ファイルで吸収<br>・Python コード内のハードコードを完全根絶 |

---

## 3. Pydantic ベースの型安全ローダー (`tools/config_loader.py`)

すべての設定は Pydantic V2 の `BaseModel`（`model_config = ConfigDict(extra="forbid")`）により厳格に検証されます。未知のキーや型不一致はロード時に即時検知（Fail-closed）されます。

### 公開 API 関数
```python
from tools.config_loader import (
    get_config,              # 統合 AppConfig (models, prompt, tag)
    load_model_config,       # ModelConfig (models.yaml)
    load_prompt_config,      # PromptConfig (prompt.yaml)
    load_tag_config,         # TagConfig (tag.yaml)
    get_model_params,        # 特定ロール (planner/coder/reviewer) のパラメータ
    get_backend_execution_config,  # GPU リースおよびルーティング設定
    get_aider_config,        # Aider 実行パラメータ
)
```

- **プロセス内キャッシュ**: 各ローダー関数は `@lru_cache(maxsize=1)` により結果がキャッシュされ、高速に動作します。
- **後方互換性**: `models.yaml` が存在しない場合は自動的に `models.json` をロードするフェイルセーフ機構を備えています。

---

## 4. 検証実績 (`tests/test_config_loader.py`)

以下の単体テストにより、YAML ロードおよび Pydantic バリデーションの完全性を保証しています（全 16 ケース合格）：

1. `test_load_model_config_loads_yaml`: `models.yaml` の妥当性検証
2. `test_load_prompt_config_loads_yaml`: `prompt.yaml` の各ロールプロンプト取得検証
3. `test_load_tag_config_loads_yaml`: `tag.yaml` のタスク分類タグ・ガード設定取得検証
4. `test_get_config_returns_unified_app_config`: 統合 `AppConfig` の取得検証
5. `test_profile_*`: 不正なポート、欠損エンドポイントの拒否検証 (Fail-closed)
6. `test_backend_config_*`: ルーティング不整合および未定義プロファイル参照の拒否検証
