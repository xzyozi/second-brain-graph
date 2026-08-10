# 詳細設計書（機能・モジュール制御仕様）
**[サブタイトル・担当機能の制御仕様]**

| 項目 | 内容 |
| :--- | :--- |
| 文書番号 | SBOS-DD-[NUMBER] （例: SBOS-DD-008） |
| 版数 | Rev.1.0（新規作成） |
| 改訂日 | YYYY年MM月DD日 |
| 作成日 | YYYY年MM月DD日 |
| 関連文書 | [SBOS-BD-002](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-BD-002_%E5%9F%BA%E6%9C%AC%E8%A8%AD%E8%A8%88%E6%9B%B8.md)（基本設計書）、[SBOS-DD-003](file:///c:/Users/xzyoi/Desktop/python/second-brain-graph/docs/design/SBOS-DD-003_%E8%A9%B3%E7%B4%B0%E8%A8%AD%E8%A8%88%E6%9B%B8.md)（詳細設計書正本） |
| 対象読者 | 開発実装エンジニア / コードレビューエンジニア |

---

## 1. 概要とSSOT境界

### 1.1 モジュールの目的
[本モジュール・機能の詳細ロジック、呼び出し経路、責務範囲を明記]

### 1.2 正本範囲 (SSOT)
[本書が直接管轄する処理と、外部の別詳細設計書（Backend、品質、排他制御など）への参照リンクを整理]

---

## 2. インターフェースと関数シグネチャ

### 2.1 API / 関数定義
```python
def example_node_function(
    state: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """[ノード・関数の機能概要]

    Args:
        state: 現在の GraphState
        config: オプション設定項目

    Returns:
        更新後の State パッチ

    Raises:
        CustomExecutionError: 処理失敗時
    """
    pass
```

### 2.2 入力パラメータと検証ルール
| パラメータ名 | 型 | 必須 | デフォルト値 | バリデーションルール |
| :--- | :--- | :---: | :--- | :--- |
| `issue_id` | `str` | ○ | - | カッコなし英数連番 (例: `EC-0001`) |

---

## 3. 処理フローと状態遷移ロジック

### 3.1 処理ステップ
1. [ステップ1: 事前状態確認・ロック検証]
2. [ステップ2: 外部コマンド呼び出し・パラメータ解決]
3. [ステップ3: 結果の判定と後処理]

### 3.2 状態遷移判定テーブル (Routing Rules)
| 現在のノード | 実行結果 / 評価値 | 次のノード | 判定関数 / 条件 |
| :--- | :--- | :--- | :--- |
| `code_node` | `LINT_PASSED` | `run_pytest_node` | `route_after_lint()` |
| `code_node` | `LINT_ERROR` (試行内) | `code_node` | `retry_count < max_round` |

---

## 4. エラー処理・失敗契約

### 4.1 エラー分類と対応契約
| エラーカテゴリ | 判定基準 | 再試行上限 | 終端ステータス | 副作用・保持動作 |
| :--- | :--- | :---: | :--- | :--- |
| `LINT_ERROR` | Ruff 非ゼロ終了 | 3回 | `ESCALATED_NEEDS_REVISION` | 差分を保持して停止 |
| `SYSTEM_ERROR` | 未捕捉例外 | 0回 | `FAILED_SYSTEM` | エラーログ保存 |

---

## 5. テスト・検証要件

### 5.1 単体テスト実行コマンド
```bash
uv run pytest tests/test_module_name.py
```
