# 多言語対応コード品質・構文検証基盤 (`tools/lang/`) 仕様書

## 概要

`tools/lang/` は、LLM Coder (Aider 等) が生成または編集したソースコードの品質・構文・構造・ビルド整合性を言語横断で検証するための共通解析モジュール群です。

単体の pytest 用テスト検証にとどまらず、自律エージェント基盤 (`tools/orchestrator_graph.py`) の `review_node` や `code_node` から呼び出すことで、コード生成直後の自動フィードバックループを実現します。

---

## パッケージ構成

```
tools/lang/
├── __init__.py           # パッケージパブリックAPIエクスポート
├── base.py               # 抽象基底クラス (BaseLanguageVerifier), 結果モデル (VerificationResult)
├── python_verifier.py    # Python用 (ast解析, py_compile, 識別子検査)
├── rust_verifier.py      # Rust用 (cargo check, cargo test, 語彙/構造解析)
└── ts_verifier.py        # TypeScript/JS用 (tsc --noEmit, node --check, 語彙解析)
```

---

## 共通 API

### `VerificationResult`

```python
@dataclass
class VerificationResult:
    is_valid: bool                # 検証に合格したか
    errors: list[str]             # 検出されたエラーメッセージリスト
    ast_tree: Optional[Any]       # 解析されたASTオブジェクト (対応言語のみ)
    identifiers: set[str]         # 抽出された識別子 (関数名, クラス名, インポート名)
```

### `get_verifier(language: str) -> BaseLanguageVerifier`

ファクトリ関数。言語名 (例: `"python"`, `"rust"`, `"typescript"`, `"js"`) を指定して対応する Verifier インスタンスを取得します。

---

## 各言語の実装仕様

### 1. Python (`PythonLanguageVerifier`)
- **構文検証**: `ast.parse` および `py_compile.compile` で文法チェック
- **構造検証**: AST を巡回して Name, Attribute, FunctionDef, ClassDef, Import ノードを抽出
- **追加機能**: `has_try_except_block()` でエラーハンドリングの存在を確認

### 2. Rust (`RustLanguageVerifier`)
- **構文検証**: Cargo プロジェクト存在時は `cargo check` を実行。単体ファイル時は括弧（`{}`, `()`, `[]`）の対応・ネスト深さをチェック
- **構造検証**: 正規表現パターンによる `fn`, `struct`, `enum`, `trait`, `use` トークン抽出
- **ビルド検証**: `cargo check --message-format=short` によるネイティブコンパイル判定

### 3. TypeScript / JavaScript (`TypeScriptLanguageVerifier`)
- **構文検証**: JSファイルは `node --check`、TSプロジェクトは `tsc --noEmit`
- **構造検証**: `function`, `class`, `interface`, `type`, `enum`, `export` 識別子の抽出

---

## テストコードでの使用例

```python
from pathlib import Path
from tools.lang import get_verifier

def test_code_output(tmp_path: Path):
    file_path = tmp_path / "app.rs"
    # LLMがコードを生成...
    
    verifier = get_verifier("rust")
    syntax_res = verifier.verify_syntax(file_path)
    assert syntax_res.is_valid, f"Syntax errors: {syntax_res.errors}"

    idents_res = verifier.verify_identifiers(file_path, ["OrderProcessor", "process"])
    assert idents_res.is_valid
```

---

## 他言語の追加方法 (拡張手順)

1. `tools/lang/` 配下に `<language>_verifier.py` を作成
2. `BaseLanguageVerifier` を継承し、`@register_verifier("言語名")` デコレータを付与
3. `verify_syntax`, `verify_identifiers`, `check_build` を実装
4. `tools/lang/__init__.py` でインポート・再エクスポート
