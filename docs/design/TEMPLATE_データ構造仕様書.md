# データ構造・状態設計書（スキーマ・永続化・状態定義）
**[サブタイトル・管理データ構造と永続化仕様]**

| 項目 | 内容 |
| :--- | :--- |
| 文書番号 | SBOS-DS-[NUMBER] または SBOS-DD-[NUMBER] （例: SBOS-DD-007） |
| 版数 | Rev.1.0（新規作成） |
| 改訂日 | YYYY年MM月DD日 |
| 作成日 | YYYY年MM月DD日 |
| 関連文書 | [SBOS-BD-002](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-BD-002_%E5%9F%BA%E6%9C%AC%E8%A8%AD%E8%A8%88%E6%9B%B8.md)（基本設計書）、[SBOS-DD-003](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-DD-003_%E8%A9%B3%E7%B4%B0%E8%A8%AD%E8%A8%88%E6%9B%B8.md)（詳細設計書正本） |
| 対象読者 | 開発実装エンジニア / データ設計者 / 運用エンジニア |

---

## 1. 概要とデータ管理方針

### 1.1 管理対象データの目的
[本設計書が定義するデータ構造（State、JSONスキーマ、メタデータ、ファイル配置、キャッシング）の目的を明記]

### 1.2 ディレクトリ階層と配置ルール
```text
metadata/
  ├── .project-registry.json       # 全衛星管理中央台帳
  └── projects/
      └── <PROJECT_KEY>/
          ├── project.json         # プロジェクト定義
          ├── state.json           # タスク実行状態正本
          └── .lock                # 排他制御ロックファイル
```

---

## 2. データ構造・型・JSONスキーマ定義

### 2.1 Pydantic / TypedDict モデル定義
```python
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class TaskStateModel(BaseModel):
    """タスクステートの正本スキーマ定義."""
    status: str = Field(..., description="状態タクソノミー")
    review_round: int = Field(0, ge=0, description="現在のレビュー周回数")
    max_round: int = Field(3, description="最大再試行周回数")
    error_category: Optional[str] = Field(None, description="失敗時のエラー分類")
    updated_at: str = Field(..., description="最終更新日時 (ISO8601 UTC)")
```

### 2.2 JSON実効構造サンプル (`state.json`)
```json
{
  "EC-0001": {
    "status": "ESCALATED_NEEDS_REVISION",
    "review_round": 1,
    "max_round": 3,
    "error_category": "LINT_ERROR",
    "updated_at": "2026-08-08T10:30:12.518004+00:00"
  }
}
```

---

## 3. 永続化・原子置換契約・排他制御

### 3.1 原子的書き込みフロー (Atomic Write Contract)
データ破壊を防ぐため、状態ファイル・メタデータの書き込みは以下の順序で行う。

1. 同一ディレクトリ内に一時ファイル (`.tmp_xxxx`) を作成・書き出し。
2. `fsync` を実行してディスクへの物理書き込みを保証。
3. `os.replace()` を呼び出し、原子的（Atomic）に対象ファイルを置換。

### 3.2 排他制御仕様 (FileLock)
* **ロックファイル位置**: `metadata/projects/<PROJECT_KEY>/.lock`
* **タイムアウト**: `timeout=0` （競合時は即時 `SKIPPED_LOCKED` とし、ノンブロッキングでスキップ）

---

## 4. データ生命周期と互換性保全

### 4.1 フォーマット移行 (Migration Strategy)
* フラット形式から階層型 JSON への移行ロジック（旧キー検出時の自動互換変換）
* 互換破壊が発生した場合のスキーマバージョン管理方針
