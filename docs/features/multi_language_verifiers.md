# 多言語対応コード品質・構文検証基盤 (`tools/lang/`) 仕様書

## 概要

`tools/lang/` は、LLM Coder (Aider 等) が生成または編集したソースコードの品質・構文・構造・ビルド整合性を言語横断で検証するための共通解析モジュール群です。

パーサー基盤として **Tree-sitter** (CST / AST 構文解析エンジン) を導入しており、正規表現やトークンスキャンに頼らない 100% 正確な構文エラー検出・識別子抽出を実現しています。

単体の pytest 用テスト検証にとどまらず、自律エージェント基盤 (`tools/orchestrator_graph.py`) の `review_node` や `code_node` から呼び出すことで、コード生成直後の自動フィードバックループを実現します。

---

## パッケージ構成

```
tools/lang/
├── __init__.py           # パッケージパブリックAPIエクスポート
├── base.py               # 抽象基底クラス, Tree-sitter パーサー・エラー・識別子抽出コア
├── python_verifier.py    # Python用 (ast解析, py_compile, Tree-sitter Python AST)
├── rust_verifier.py      # Rust用 (cargo check, Tree-sitter Rust AST)
└── ts_verifier.py        # TypeScript/JS用 (tsc --noEmit, Tree-sitter TS/JS AST)
```

---

## 共通 API

### `VerificationResult`

```python
@dataclass
class VerificationResult:
    is_valid: bool                # 検証に合格したか
    errors: list[str]             # 検出されたエラーメッセージリスト
    ast_tree: Optional[Any]       # 解析された Tree-sitter / Python AST オブジェクト
    identifiers: set[str]         # 抽出された識別子 (関数名, クラス名, インポート名)
```

### `get_verifier(language: str) -> BaseLanguageVerifier`

ファクトリ関数。言語名 (例: `"python"`, `"rust"`, `"typescript"`, `"js"`) を指定して対応する Verifier インスタンスを取得します。

---

## 各言語の実装仕様

### 1. Python (`PythonLanguageVerifier`)
- **構文検証**: `ast.parse` / `py_compile.compile` および `tree-sitter-python` パーサーによる構文エラーノード (`ERROR`, `MISSING`) の二重検出
- **構造検証**: Python AST および Tree-sitter AST ノードを巡回して関数・クラス・モジュール識別子を自動抽出
- **追加機能**: `has_try_except_block()` でエラーハンドリングの存在を確認

### 2. Rust (`RustLanguageVerifier`)
- **構文検証**: Cargo プロジェクト存在時は `cargo check` を実行。単体ファイル時は `tree-sitter-rust` による正確な構文木エラー評価
- **構造検証**: Tree-sitter CST から `function_item`, `struct_item`, `enum_item`, `trait_item`, `identifier` 等を抽出し、Rust キーワードを除外
- **ビルド検証**: `cargo check --message-format=short` によるネイティブコンパイル判定

### 3. TypeScript / JavaScript (`TypeScriptLanguageVerifier`)
- **構文検証**: `tree-sitter-typescript` (TS/TSX) および `tree-sitter-javascript` (JS/JSX) による全アノテーション・ネスト構造・型定義のパーサー評価。JSファイルは `node --check` と併用
- **構造検証**: Tree-sitter CST から `function_declaration`, `class_declaration`, `interface_declaration`, `type_alias_declaration` 等の識別子を抽出
- **ビルド検証**: `tsc --noEmit` による型チェック

---

## ライセンス・依存関係

本基盤で使用している Tree-sitter パーサーパッケージは、商用およびオープンソース利用に極めて親和性の高いライセンスです。

- **`tree-sitter`**: MIT License
- **`tree-sitter-python`**: MIT License
- **`tree-sitter-rust`**: MIT License
- **`tree-sitter-typescript`**: MIT License

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
3. `tools/lang/base.py` の `get_tree_sitter_parser` に対応する Tree-sitter パッケージバインディングを追加
4. `verify_syntax`, `verify_identifiers`, `check_build` を実装
5. `tools/lang/__init__.py` でインポート・再エクスポート

