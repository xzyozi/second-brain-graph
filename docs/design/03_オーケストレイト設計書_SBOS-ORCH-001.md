# オーケストレイト設計書（ステートマシン・レビュー自己修復・ASTマージ・差分検証）
**Python Orchestrator 内部制御ロジックおよびアルゴリズム設計**

| 項目 | 内容 |
| :--- | :--- |
| 文書番号 | SBOS-ORCH-001 |
| 版数 | Rev.3.6（PM-036 ブランチ・PR自動化方針反映） |
| 改訂日 | 2026年7月29日 |
| 作成日 | 2026年7月27日 |
| 対象読者 | コアエンジン開発者 / アルゴリズム設計者 / 品質管理エンジニア |
| 関連文書 | SBOS-BD-002（基本設計書）、SBOS-DD-003（詳細設計書）、SBOS-PM-005（課題一覧） |

---

> [!IMPORTANT]
> **【重要・アーキテクチャ移行に関する注記 (Rev.4.0以後の位置づけ)】**
> 本書（SBOS-ORCH-001）は、自前実装時代の制御アルゴリズム解説およびフォールバック参考資料です。
> 本書のB7判定、再試行、Git復旧に関する記述は参考情報であり、現行仕様ではありません。現行の正本は **『詳細設計書 SBOS-DD-003』** の状態管理・失敗時契約とします。
> Rev.4.0 以降の新OSSスタック（LangGraph `StateGraph`, LiteLLM, Aider, Reviewdog）における現行の正本仕様は **『基本設計書 SBOS-BD-002』** および **『詳細設計書 SBOS-DD-003』** を参照してください。

---

## 1. 自己修復ステートマシン構造（Rev.3.1 拡張版）

> [!WARNING]
> **【参考資料・非規範】**
> 本セクションに記載されているステートマシン仕様は旧自前実装時代のレガシーアーキテクチャであり、現行システムでは使用されていません。

`tools/orchestrator.py` に実装されている有向ステートマシンは、レビュー工程（`REVIEW_PASSED`）の追加とエラー再試行上限管理により、自律的な自己修復ループを形成する。

### 1.1 `State` Enum 遷移図
```
                      +───────────────────────────────────────────────────+
                      │                (再試行 / 差し戻し)                  │
                      ▼                                                   │
 [開始] ──► DRAFT ──► SANITIZED ──► L1_PASSED ──► L2_PASSED ──► L3_PASSED ──+
             │            │             │             │             │
             │            │             │             │             ▼
             │            │             │             │       [Reviewer監査]
             │            │             │             │             │
             │            │             │             │       (changes_requested)
             │            │             │             │       [REVIEW_REJECTED]
             │            │             │             │             │
             ▼            ▼             ▼             ▼             │
          FAILED ◄─── FAILED ◄───── FAILED ◄───── FAILED ◄──────────+
          (上限到達時は B7 ブロッカーとして人間へエスカレーション)
                                                                    │
                                                              (verdict: LGTM)
                                                                    ▼
                                                              REVIEW_PASSED ──► [完了・コミット承認待ち]
```

### 1.2 状態定義と遷移トリガー仕様
| 状態名 | 意味・概要 | 次状態への遷移条件 |
| :--- | :--- | :--- |
| **`DRAFT`** | 実行初期状態。要件収集および指示書生成完了。 | サニタイズ処理（文字コード、BOM除去）が正常終了で `SANITIZED` へ。 |
| **`SANITIZED`** | 不正制御文字の除去完了。 | AST構文解析および Linter（Ruff check）通過で `L1_PASSED` へ。 |
| **`L1_PASSED`** | 静的構文チェック通過。 | 型検証および静的セキュリティ解析通過で `L2_PASSED` へ。 |
| **`L2_PASSED`** | 高次静的検証通過。 | `pytest` / `jest` による自動テストすべて通過で `L3_PASSED` へ。 |
| **`L3_PASSED`** | 決定論的テスト全通過。**（従来の実装における最終成功状態）** | ⭐NEW：Reviewer Agent の推論監査を開始。LGTM で `REVIEW_PASSED` へ。 |
| **`REVIEW_PASSED`** | ⭐NEW：人間並みの客観的監査をクリア。 | メインループ終了。変更ファイルを Git ステージしユーザーへコミット承認要求。 |
| **`FAILED`** | エラー上限到達。自動自己修復の断念。 | 実行停止。`tasks.md` を更新し、ブロッカーとしてマーク。 |

---

## 2. エラー分類器とリトライ制御ロジック (`error_classifier.py`)

エラー発生時、LLMの不完全な推測に頼らず、エラーログの文字列やプロセスの終了コードを Python スクレイピングしてエラーカテゴリを決定する。

### 2.1 5大エラーカテゴリと上限値設定
```python
from enum import Enum, auto
from typing import Dict

class ErrorCategory(Enum):
    SYNTAX = auto()          # 構文エラー、インデント不正、インポートエラー
    CONSTRAINT = auto()      # 仕様違反、シグネチャ不一致、アーキテクチャ制約違反
    TEST_FAILURE = auto()    # pytest アサーション失敗、バウンダリテスト例外
    RUNTIME = auto()         # タイムアウト、メモリ不足、実行時クラッシュ
    REVIEW_REJECTED = auto() # ⭐NEW レビューAgentによる仕様/セキュリティ指摘差し戻し

DEFAULT_MAX_RETRIES: Dict[ErrorCategory, int] = {
    ErrorCategory.SYNTAX: 3,
    ErrorCategory.CONSTRAINT: 2,
    ErrorCategory.TEST_FAILURE: 2,
    ErrorCategory.RUNTIME: 1,
    ErrorCategory.REVIEW_REJECTED: 2  # ⭐NEW：差し戻しは最大2回まで
}
```

### 2.2 ヒーリングプロンプト生成アルゴリズム (`_build_healing_prompt`)
エラー分類に応じて、Coder（実装Agent）の次の試行に渡すプロンプトを最適化する。

- **`SYNTAX` 発生時:** エラーのスタックトレースの最下部（ファイルの行番号とシンタックスエラーメッセージ）を抽出し、「指定された行の構文エラーを修正すること。ロジック全体は変更しないこと」を指示。
- **`TEST_FAILURE` 発生時:** 失敗したテスト関数の名称とアサーション差分（`E assert X == Y`）を抽出し、「テストコードを修正してはならない。実装側のロジックを修正してテストを通過させること」を厳命。
- **`REVIEW_REJECTED` 発生時:** レビューAgentが返却した JSON の `comment` および指摘された行番号範囲（`line_range`）を結合し、「設計指示書（仕様）の要求と以下のレビュー指摘を満たすようにコードを再実装すること」を指示。


---

## 3. コード破壊防止と自動 AST マージ (`_merge_python_code`)

> [!WARNING]
> **【参考資料・非規範】**
> 本セクションのASTマージ仕様は Aider 導入前のレガシーアーキテクチャにおける実装解説であり、現行システムでは使用されていません。

ローカルLLMにファイル全体の書き換えを許すと、指示していない既存の正常なメソッドやインポート文を欠落させる「破壊的編集」が発生する。これを防ぐため、Python 標準の `ast` モジュールを用いた抽象構文木マージを実行する。

### 3.1 AST マージアルゴリズム
1. **解析:** 書き込み前の既存ソースコード（`existing_content`）と、Coder が生成したコード（`generated_code`）の双方を `ast.parse()` で構文木へ変換する。
2. **インポート文の統合:** 両者の AST の先頭にある `Import`, `ImportFrom` ノードを抽出・重複排除し、ソートして結合する。
3. **トップレベルノードのマージ:**
   - 関数定義 (`FunctionDef`, `AsyncFunctionDef`) およびクラス定義 (`ClassDef`) を名称（`node.name`）をキーとして辞書化する。
   - 既存コードのノードの順序を維持しつつ、同名のノードが存在する場合は生成された側のノードで置き換え（上書き変更）、新しい名称のノードはファイルの適切な位置（同種ノードの末尾）に追記する。
4. **コード再構成:** マージされた AST を `ast.unparse()` で文字列に戻し、Ruff でフォーマットを整えた上でファイルに書き込む。

```python
import ast
from typing import Dict, Any

def _merge_python_code(existing_content: str, generated_code: str) -> str:
    if not existing_content.strip():
        return generated_code

    try:
        base_tree = ast.parse(existing_content)
        new_tree = ast.parse(generated_code)
    except SyntaxError:
        # 生成コードに構文エラーがある場合はマージせずそのまま返し、後段のSYNTAXエラー検知に委ねる
        return generated_code

    new_functions: Dict[str, ast.FunctionDef] = {
        node.name: node for node in new_tree.body if isinstance(node, ast.FunctionDef)
    }

    merged_body = []
    for node in base_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in new_functions:
            merged_body.append(new_functions.pop(node.name)) # 上書き置換
        else:
            merged_body.append(node)

    # 新規追加された関数を末尾に追記
    merged_body.extend(new_functions.values())
    base_tree.body = merged_body

    return ast.unparse(base_tree)
```

---

## 4. レビュー差し戻しループと Git 未依存差分検証

### 4.1 差し戻し先を常に「Coder（実装Agent）」とする設計トレードオフ
レビューで仕様の不整合が指摘された場合、本来であれば上流の要件定義（Executor）からやり直すのが理想的である。しかし、本スタックにおける `execute_issue()` ループ構造では以下のトレードオフが存在する。

- **理由:** Executor はループの外側で初期化時に一度だけ実行され、その後の高速な自己修復ループは Coder と決定論的テストの間で回るアーキテクチャとなっている。
- **トレードオフの選択:** 上流の Executor を再ループに巻き込むと、コンテキスト管理の複雑化および推論コスト・時間の増大を招く。したがって、**レビュー指摘の原因が設計/実装のどちらであっても、まずは常に Coder への修正依頼として処理する**（プロンプト内にオリジナルの実装指示書とレビュー指摘の両方を盛り込む）。
- **破綻時の解決:** もし設計指示書そのものが根本的に誤っている場合、Coder の修正試行はテスト通過やレビューをクリアできず、`REVIEW_REJECTED` の上限（2回）に到達する。この時点で自動的に `State.FAILED` となり、ブロッカー B7 として人間へエスカレーションされる安全装置が機能する。

### 4.2 非 Git 依存 unified diff 生成アルゴリズム
> [!NOTE]
> 現在はエージェントによる自動ブランチ作成およびPR作成運用 (PM-036) へ移行したため、レビュアーAgentは `git diff` を直接参照可能である (DD-003 §4 の `get_git_diff()` を使用)。
> 以下のロジックは、メモリ上のみで差分を計算していた旧レガシーアーキテクチャの参考情報として残している。

旧仕様では、手動コミット承認を待つ必要があったため、`orchestrator.py` のファイル書き込みインターフェース `_write_files()` で以下のロジックを実行し、メモリ内で差分を生成してレビューAgentに渡していた。

```python
import difflib
from typing import List

def _generate_unified_diff(filepath: str, old_content: str, new_content: str) -> str:
    """書き込み前後の文字列からunified diffを生成する。Git依存を完全に排除。"""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        n=3 # 前後3行のコンテキストを保持
    )
    return "".join(diff)
```

---

## 5. ブロッカー B7（レビュー上限到達）と自動除外機構

> [!WARNING]
> **【参考資料・非規範】**
> 本セクションのB7検知・除外仕様はレガシーアーキテクチャの実装解説です。現行のB7判定ロジックは SBOS-DD-003 に従います。

### 5.1 `check-blockers.py` における B7 検出アルゴリズム
レビューの差し戻しループが無限に回ることを防ぐため、`check-blockers.py` は純粋な正規表現だけでなく、Python 側での数値比較ロジックを組み込んで判定を行う。

```python
import re
from typing import List, Dict, Any

def _detect_b7_blocker(task_line: str, issue_id: str, history_records: List[Dict]) -> bool:
    """タスク行のラウンドメタデータと実行履歴を照合し、B7ブロッカーを検知する。"""
    round_match = re.search(r"round:(\d+)", task_line)
    max_round_match = re.search(r"max_round:(\d+)", task_line)

    if not round_match:
        return False

    current_round = int(round_match.group(1))
    max_round = int(max_round_match.group(1)) if max_round_match else 3

    if current_round >= max_round:
        latest_history = next((h for h in reversed(history_records) if h["issue_id"] == issue_id), None)
        if latest_history and not latest_history["success"] and latest_history.get("final_state") == "FAILED":
            return True
    return False
```

### 5.2 バッチ実行（`execute_batch()`）への影響
1. 日次バッチまたは `/orchestrate` コマンド実行時、`check-blockers.py` がスキャンを走行する。
2. B7 条件を満たした Issue は `blocked.json` の `blocked_issues` 配列へ追加され、分類コード `"B7_REVIEW_LIMIT_EXCEEDED"` が付与される。
3. 実行可能な Issue を列挙する `actionable` 配列からは自動的に除外されるため、`orchestrator.py` の自動バッチ処理が該当 Issue を誤って再試行し続け、CPU/GPU リソースを浪費する事態が完全に阻止される。---

## 6. オーケストレイト中核ロジックの完全コード実装仕様

本節では、基本・詳細設計を実稼働させるための中核スクリプト `tools/orchestrator.py` のクラス構造および主要メソッドの完全なリファレンス実装を規定する。

### 6.1 `IssueOrchestrator` クラスメイン制御ループ (`execute_issue`)
以下は、例外捕捉、エラー分類、リトライカウンタ管理、および状態遷移を統合した実装仕様である。

```python
import os
import time
import logging
from typing import Optional, Dict, Any, List
from enum import Enum, auto

class State(Enum):
    DRAFT = auto()
    SANITIZED = auto()
    L1_PASSED = auto()
    L2_PASSED = auto()
    L3_PASSED = auto()
    REVIEW_PASSED = auto()
    FAILED = auto()

class IssueOrchestrator:
    def __init__(self, issue_id: str, project_key: str, project_path: str):
        self.issue_id = issue_id
        self.project_key = project_key
        self.project_path = project_path
        self.state = State.DRAFT
        self.logger = logging.getLogger(f"orchestrator.{issue_id}")
        
        # コンポーネント初期化（スタブ）
        # self.context = SharedContext(issue_id, project_key, project_path)
        # self.client = AgentClient()
        # self.prompt_builder = PromptBuilder()
        # self.classifier = ErrorClassifier()
        
        self.retries = {
            "SYNTAX": 0,
            "CONSTRAINT": 0,
            "TEST_FAILURE": 0,
            "RUNTIME": 0,
            "REVIEW_REJECTED": 0
        }
        self.max_retries = {
            "SYNTAX": 3,
            "CONSTRAINT": 2,
            "TEST_FAILURE": 2,
            "RUNTIME": 1,
            "REVIEW_REJECTED": 2
        }

    def execute_issue(self, max_total_steps: int = 15) -> bool:
        """Issue実行のメインステートマシンループ。REVIEW_PASSEDに到達すればTrueを返す。"""
        self.logger.info(f"=== Starting execution loop for Issue {self.issue_id} ===")
        step_count = 0
        
        # 1. 衛星ディレクトリへのCWDスイッチ
        original_cwd = os.getcwd()
        os.chdir(self.project_path)
        self.logger.info(f"Switched CWD to {self.project_path}")
        
        try:
            while self.state != State.REVIEW_PASSED and step_count < max_total_steps:
                step_count += 1
                self.logger.debug(f"[Step {step_count}] Current State: {self.state.name}")
                
                try:
                    if self.state == State.DRAFT:
                        self._handle_draft_state()
                    elif self.state == State.SANITIZED:
                        self._handle_sanitized_state()
                    elif self.state == State.L1_PASSED:
                        self._handle_l1_passed_state()
                    elif self.state == State.L2_PASSED:
                        self._handle_l2_passed_state()
                    elif self.state == State.L3_PASSED:
                        self._handle_l3_passed_state()
                except Exception as e:
                    error_type = self._classify_error(str(e))
                    self.retries[error_type] += 1
                    self.logger.warning(
                        f"Error encountered ({error_type}): {str(e)} | "
                        f"Retry count: {self.retries[error_type]}/{self.max_retries[error_type]}"
                    )
                    
                    if self.retries[error_type] >= self.max_retries[error_type]:
                        self.logger.error(f"Max retries reached for {error_type}. Escalating to FAILED.")
                        self.state = State.FAILED
                        self._mark_task_as_b7_or_failed(error_type)
                        return False
                    else:
                        # ヒーリングプロンプトを生成してDRAFTまたは前段状態へロールバック
                        self._rollback_and_heal(error_type, str(e))
                        
            if self.state == State.REVIEW_PASSED:
                self.logger.info(f"Issue {self.issue_id} successfully passed all reviews!")
                return True
            else:
                self.logger.error("Execution loop terminated before reaching REVIEW_PASSED.")
                return False
                
        finally:
            os.chdir(original_cwd)
            self.logger.info(f"Restored CWD to {original_cwd}")

    def _handle_draft_state(self):
        # 要件定義と実装指示書生成の実行
        self.logger.info("Executing requirement gathering and implementation plan generation...")
        time.sleep(0.5) # シミュレーション
        self.state = State.SANITIZED

    def _handle_sanitized_state(self):
        # 静的構文解析・Linterチェック
        self.logger.info("Running Ruff / ESLint static syntax validation...")
        time.sleep(0.5)
        self.state = State.L1_PASSED

    def _handle_l1_passed_state(self):
        # 型チェック・高次静的検証
        self.logger.info("Running advanced type checking and security scan...")
        time.sleep(0.5)
        self.state = State.L2_PASSED

    def _handle_l2_passed_state(self):
        # 決定論的テスト (pytest) の実行
        self.logger.info("Running automated test suite (pytest)...")
        time.sleep(0.5)
        self.state = State.L3_PASSED

    def _handle_l3_passed_state(self):
        # Reviewer Agentによる客観的監査
        self.logger.info("Calling Reviewer Agent for unified diff audit...")
        time.sleep(0.5)
        # 監査クリア
        self.state = State.REVIEW_PASSED

    def _classify_error(self, error_msg: str) -> str:
        if "SyntaxError" in error_msg or "IndentationError" in error_msg:
            return "SYNTAX"
        elif "assert" in error_msg or "Failed" in error_msg:
            return "TEST_FAILURE"
        elif "ReviewRejected" in error_msg:
            return "REVIEW_REJECTED"
        elif "ConstraintViolation" in error_msg:
            return "CONSTRAINT"
        return "RUNTIME"

    def _rollback_and_heal(self, error_type: str, error_msg: str):
        self.logger.info(f"Rolling back temporary files and preparing healing prompt for {error_type}...")
        # 状態をDRAFTへ戻し、次回試行でCoderがエラーコンテキストを受け取れるよう準備
        self.state = State.DRAFT

    def _mark_task_as_b7_or_failed(self, error_type: str):
        self.logger.error(f"Marking task {self.issue_id} in tasks.md as blocked ({error_type}).")
```

---

## 7. 高等 AST 構文解析と関数レベルマージの詳細アルゴリズム

前述の `_merge_python_code` におけるマージロジックをさらに深掘りし、クラスメソッドやデコレータを保持したまま正確に差分マージを行うための `NodeTransformer` アルゴリズムを詳述する。

### 7.1 クラス内部メソッドの非破壊的置換 (`ClassMethodMerger`)
Python のソースコードにおいては、トップレベルの関数だけでなく、クラス (`ast.ClassDef`) 内部に定義された特定のメソッドのみをリファクタリングする要求が極めて多い。
以下のアルゴリズムにより、クラス内の既存プロパティや無関係なメソッドを維持したまま、ターゲットメソッドのみを安全に差し替える。

```python
import ast
from typing import Dict

class ClassMethodMerger(ast.NodeTransformer):
    """クラス定義内のメソッドを選択的に更新するASTトランスフォーマー"""
    def __init__(self, new_methods: Dict[str, ast.FunctionDef]):
        self.new_methods = new_methods
        self.updated_names = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        new_body = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in self.new_methods:
                    # 新しいメソッド定義で置換
                    new_body.append(self.new_methods[item.name])
                    self.updated_names.add(item.name)
                else:
                    new_body.append(item)
            else:
                new_body.append(item)
        
        # 既存クラスに存在しなかった新設メソッドを末尾に追加
        for m_name, m_node in self.new_methods.items():
            if m_name not in self.updated_names:
                new_body.append(m_node)
                
        node.body = new_body
        return node
```

### 7.2 インポート文の正規化と重複排除アルゴリズム
コード生成モデルは、すでにファイル先頭でインポートされているモジュール（例: `import os`, `from typing import List`）を関数内部や末尾で再度インポートするコードを出しやすい。
これを整理するため、書き込み前に以下のインポートクリーナーを走行させる。

```python
import ast

def clean_and_normalize_imports(source_code: str) -> str:
    """インポート文をファイル先頭に集約し、重複を排除してソートする"""
    tree = ast.parse(source_code)
    
    imports = []
    import_froms: Dict[str, set] = {}
    other_nodes = []
    
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module not in import_froms:
                import_froms[module] = set()
            for alias in node.names:
                import_froms[module].add(alias.name)
        else:
            other_nodes.append(node)
            
    # 新しいインポートノードの生成
    new_import_nodes = []
    for mod in sorted(set(imports)):
        new_import_nodes.append(ast.Import(names=[ast.alias(name=mod, asname=None)]))
        
    for mod in sorted(import_froms.keys()):
        names = [ast.alias(name=n, asname=None) for n in sorted(import_froms[mod])]
        new_import_nodes.append(ast.ImportFrom(module=mod, names=names, level=0))
        
    tree.body = new_import_nodes + other_nodes
    return ast.unparse(tree)
```

---

## 8. メモリおよびパフォーマンス最適化設計

### 8.1 大規模ファイルにおける `difflib.unified_diff` の計算計算量と制限
`difflib.unified_diff` は行単位のゲシュタルトパターンマッチング（Gestalt Pattern Matching）アルゴリズムを採用しており、時間計算量は最悪ケースで $O(N^2)$、空間計算量は $O(N)$（$N$ はファイル総行数）となる。
数万行を超える巨大なデータ定義ファイルや自動生成コードに対して実行すると、CPUおよびメモリを大きく消費し、Orchestrator がブロックされるリスクがある。

**最適化およびセーフガード指針:**
1. **ファイルサイズ上限の強制:** 対象ファイルの行数が 2,500 行を超える場合、`difflib.unified_diff` の計算をスキップし、変更された関数またはクラスの AST ノード文字列表現のみを切り出してレビューAgentへ送出する。
2. **前後コンテキスト行数（`n`）の最適化:** レビューの可読性を保ちつつトークン消費を最小化するため、コンテキスト行数は `n=3` に固定し、無関係な正常行の出力を抑制する。