# [ドキュメントタイトル]（例：○○機能詳細設計書）
**[サブタイトル・要約説明]**

| 項目 | 内容 |
| :--- | :--- |
| 文書番号 | SBOS-[TYPE]-[NUMBER] （例: SBOS-DD-008） |
| 版数 | Rev.1.0（新規作成） |
| 改訂日 | YYYY年MM月DD日 |
| 作成日 | YYYY年MM月DD日 |
| 対象読者 | [開発エンジニア / アーキテクト / DevOps 等] |
| 関連文書 | SBOS-BD-002（基本設計書）、[SBOS-DD-003](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-DD-003_%E8%A9%B3%E7%B4%B0%E8%A8%AD%E8%A8%88%E6%9B%B8.md)（詳細設計書）、SBOS-PM-005（課題一覧） |

---

## 1. 概要と目的 (Overview)

### 1.1 背景と目的
[このドキュメントが定義するコンポーネント・機能の背景と目的を記述]

### 1.2 単一責任原則 (SSOT) と対象範囲
[本書が正本（Single Source of Truth）として管理する範囲および、他ドキュメントとの境界を明記]

---

## 2. コンポーネント定義とシステム境界 (Component Boundaries)

### 2.1 責務と非機能要件
* **担当範囲**: [このコンポーネントが担保する処理]
* **非対象範囲**: [他のコンポーネントに委任する処理]

### 2.2 入力・出力インターフェース
| 区分 | 項目名 / データ型 | 説明・仕様 |
| :--- | :--- | :--- |
| **入力** | `param_name: str` | [引数や入力データの仕様] |
| **出力** | `return_val: Dict` | [戻り値や出力データの構造] |

---

## 3. 詳細仕様と制御フロー (Detailed Specifications)

### 3.1 主要処理フロー
```text
[処理A] ──► [処理B] ──► (条件判定)
                            ├─ 成功 ─► [処理C]
                            └─ 失敗 ─► [例外ハンドリング]
```

### 3.2 モジュール・関数シグネチャ
```python
def example_function(
    param1: str,
    param2: int = 10,
) -> bool:
    """関数の概要説明.

    Args:
        param1: パラメータ1の説明
        param2: パラメータ2の説明

    Returns:
        処理結果 (True: 成功, False: 失敗)

    Raises:
        ValueError: パラメータ不正時
    """
    pass
```

---

## 4. 例外・エラーハンドリング契約 (Error Handling & Failures)

### 4.1 エラー分類と対処方針
| エラー種別 | 発生条件 | 影響度 | 自動復旧 / フォールバック動作 | 終端ステータス |
| :--- | :--- | :---: | :--- | :--- |
| `INVALID_INPUT` | 引数フォーマット不正 | 🟡 中 | エラーログ出力後、即時 `ValueError` を送出 | - |
| `TIMEOUT` | 外部呼出の応答遅延 | 🔴 高 | 1回再試行後、安全停止処理を実行 | `FAILED_SYSTEM` |

---

## 5. 永続化・データ整合性・副作用 (Persistence & Side Effects)

### 5.1 ファイル保存仕様
* **保存パス**: `metadata/projects/<PROJECT_KEY>/filename.json`
* **書き込み契約**: `fsync` + 一時ファイルからの原子置換 (`os.replace`) を保証する。

---

## 6. 検証・品質ゲート (Verification & Testing)

### 6.1 自動テスト要件
以下のテストコマンドを実行し、全テストが通過することを確認する。

```bash
uv run pytest tests/test_example.py
```
