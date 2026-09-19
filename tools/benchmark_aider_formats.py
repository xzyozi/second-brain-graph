#!/usr/bin/env python3
"""tools/benchmark_aider_formats.py - Aider edit_format 多角的実証ベンチマークスクリプト

ローカルモデル (Ornith 1.5 9B, Gemma 4 12B, Qwen 2.5 Coder 14B 等) に対して、
多種多様なファイル規模（小〜大、600行超）、日本語混在コード、新規ファイル作成、
複数ファイル同時編集、および hybrid 編集とフォールバックの実機挙動を多角的に検証・測定します。
"""

import argparse
import ast
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

# プロジェクトルートをインポートパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.aider_runner import run_aider  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark")


def create_mock_repo(base_dir: Path) -> Path:
    """隔離された一時 Git リポジトリを作成する。"""
    repo_dir = base_dir / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "BenchmarkUser"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "benchmark@example.com"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "core.autocrlf", "input"], cwd=repo_dir, capture_output=True, check=True
    )

    return repo_dir


def _safe_commit(repo_dir: Path, msg: str) -> None:
    """変更がある場合のみ安全に git add & commit を行う。"""
    subprocess.run(["git", "add", "-A", "."], cwd=repo_dir, capture_output=True, check=False)
    st = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True, check=False
    )
    if st.stdout.strip():
        subprocess.run(["git", "commit", "-m", msg], cwd=repo_dir, capture_output=True, check=False)


# ---------------------------------------------------------------------------
# テストファイル生成器 (多彩なシナリオ)
# ---------------------------------------------------------------------------
def generate_small_file(repo_dir: Path) -> Path:
    """小規模ファイル (~50行): 計算ロジックモジュール。"""
    file_path = repo_dir / "calculator.py"
    content = '''"""Simple calculator module for benchmark."""

import math
import logging

logger = logging.getLogger(__name__)


def add(a: int, b: int) -> int:
    """Add two numbers (has bug for test)."""
    # BUG: using subtraction instead of addition
    return a - b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def divide(a: float, b: float) -> float:
    """Divide a by b with zero division check."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def power(base: float, exp: float) -> float:
    """Calculate power."""
    return math.pow(base, exp)


def modulus(a: int, b: int) -> int:
    """Calculate modulus."""
    return a % b
'''
    file_path.write_text(content, encoding="utf-8")
    _safe_commit(repo_dir, "Initial commit small")
    return file_path


def generate_medium_file(repo_dir: Path) -> Path:
    """中規模ファイル (~250行): パイプライン処理モジュール。"""
    file_path = repo_dir / "processor.py"
    lines = [
        '"""Data processing and pipeline utility."""',
        "",
        "import logging",
        "import json",
        "from typing import List, Dict, Any, Optional",
        "",
        "logger = logging.getLogger(__name__)",
        "",
        "class RecordValidator:",
        '    """Validator for incoming raw dictionary records."""',
        "",
        "    def __init__(self, required_keys: Optional[List[str]] = None):",
        "        self.required_keys = required_keys or ['id', 'name', 'value']",
        "",
        "    def validate(self, record: Dict[str, Any]) -> bool:",
        "        for k in self.required_keys:",
        "            if k not in record:",
        "                return False",
        "        return True",
        "",
    ]

    for i in range(1, 25):
        lines.extend(
            [
                f"class TransformerBlock{i}:",
                f'    """Transformer block {i}."""',
                f"    def __init__(self, scale: float = {i}.0):",
                "        self.scale = scale",
                "",
                "    def transform(self, val: float) -> float:",
                "        return val * self.scale",
                "",
            ]
        )

    lines.extend(
        [
            "class PipelineRunner:",
            '    """Main runner for data processing pipeline."""',
            "",
            "    def __init__(self):",
            "        self.validator = RecordValidator()",
            "        self.records: List[Dict[str, Any]] = []",
            "",
            "    def process_records(self, raw_records: List[Dict[str, Any]]) -> int:",
            '        """Process all records. NEEDS ERROR HANDLING."""',
            "        count = 0",
            "        for r in raw_records:",
            "            # TARGET FOR EDIT: Add try-except block here to catch ValueError and log warning",
            "            val = float(r.get('value', 0))",
            "            if val > 0:",
            "                count += 1",
            "        return count",
            "",
            "    def get_summary(self) -> Dict[str, Any]:",
            "        return {'processed_count': len(self.records)}",
            "",
        ]
    )

    file_path.write_text("\n".join(lines), encoding="utf-8")
    _safe_commit(repo_dir, "Initial commit medium")
    return file_path


def generate_large_file(repo_dir: Path) -> Path:
    """大規模ファイル (~600行): 状態管理および多数のハンドラを持つシステムモジュール。"""
    file_path = repo_dir / "system_orchestrator.py"
    lines = [
        '"""Comprehensive system orchestrator module for large scale benchmark."""',
        "",
        "import os",
        "import sys",
        "import time",
        "import logging",
        "from typing import Dict, Any, List, Optional, Callable",
        "",
        "logger = logging.getLogger('orchestrator')",
        "",
        "class OrchestratorContext:",
        "    def __init__(self, trace_id: str):",
        "        self.trace_id = trace_id",
        "        self.metadata: Dict[str, Any] = {}",
        "        self.logs: List[str] = []",
        "",
        "    def record(self, msg: str) -> None:",
        "        self.logs.append(f'[{time.time()}] {msg}')",
        "",
    ]

    # 40個のハンドラクラスを追加して行数を一気に約600行まで伸ばす
    for i in range(1, 45):
        lines.extend(
            [
                f"class TaskHandler_{i:02d}:",
                f'    """Task handler stage {i}."""',
                f"    STAGE_ID = {i}",
                "",
                "    def __init__(self, config: Optional[Dict[str, Any]] = None):",
                "        self.config = config or {}",
                "        self.executed = False",
                "",
                "    def handle(self, context: OrchestratorContext) -> bool:",
                f"        context.record('Executing stage {i}')",
                "        self.executed = True",
                "        return True",
                "",
                "    def rollback(self, context: OrchestratorContext) -> None:",
                f"        context.record('Rollback stage {i}')",
                "",
            ]
        )

    lines.extend(
        [
            "class SystemWorkflowCoordinator:",
            '    """Root coordinator executing all stages sequentially."""',
            "",
            "    def __init__(self):",
            "        self.stages: List[Any] = []",
            "",
            "    def execute_workflow(self, context: OrchestratorContext) -> bool:",
            '        """Execute all configured stages in order."""',
            "        # TARGET FOR EDIT: Add safety check: if not context.trace_id, raise ValueError('Missing trace_id')",
            "        for stage in self.stages:",
            "            ok = stage.handle(context)",
            "            if not ok:",
            "                return False",
            "        return True",
            "",
        ]
    )

    file_path.write_text("\n".join(lines), encoding="utf-8")
    _safe_commit(repo_dir, "Initial commit large")
    return file_path


def generate_japanese_file(repo_dir: Path) -> Path:
    """日本語混在ファイル (~150行): 日本語要件定義、Docstring、コメントを含む認証サービス。"""
    file_path = repo_dir / "auth_service.py"
    content = '''"""ユーザー認証およびトークン検証サービスモジュール

本モジュールは、APIリクエストに対するユーザー認証トークンの検証と
権限チェック（RBAC）を担当します。
"""

import time
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("auth")


class AuthToken:
    """認証トークン表現クラス。"""

    def __init__(self, token_str: str, user_id: str, expires_at: float):
        self.token_str = token_str
        self.user_id = user_id
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        """有効期限超過を判定する。"""
        return time.time() > self.expires_at


class UserSessionManager:
    """ユーザーセッションの保持とライフサイクル管理。"""

    def __init__(self):
        # メモリストレージ
        self.sessions: Dict[str, AuthToken] = {}
        self.user_roles: Dict[str, List[str]] = {}

    def register_token(self, user_id: str, token: AuthToken) -> None:
        """新しい認証トークンをセッション一覧に登録する。"""
        self.sessions[token.token_str] = token

    def validate_request(self, token_str: str, required_role: Optional[str] = None) -> bool:
        """トークンの正当性およびロール権限を検証する。"""
        # TARGET FOR EDIT: 空文字や None のトークンに対する防御チェックを追加
        # token_str が空文字または None の場合は即座に False を返すようにしてください。
        if token_str not in self.sessions:
            logger.warning("未登録のトークンです。")
            return False

        token = self.sessions[token_str]
        if token.is_expired():
            logger.warning("トークンの有効期限が切れています。")
            return False

        if required_role:
            roles = self.user_roles.get(token.user_id, [])
            if required_role not in roles:
                logger.warning(f"必要な権限 {required_role} を所持していません。")
                return False

        return True


def create_default_session_manager() -> UserSessionManager:
    """デフォルト構成のセッションマネージャーを生成するヘルパー。"""
    manager = UserSessionManager()
    return manager
'''
    file_path.write_text(content, encoding="utf-8")
    _safe_commit(repo_dir, "Initial commit japanese")
    return file_path


def generate_multi_files(repo_dir: Path) -> List[str]:
    """複数ファイル混在 (models.py 40行 + service.py 220行): 同時編集シナリオ用。"""
    f1 = repo_dir / "schema.py"
    f1_content = '''"""Data schemas for order processing."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderItem:
    item_id: str
    quantity: int
    price: float


@dataclass
class Order:
    order_id: str
    items: list[OrderItem]
    status: str = "pending"
    # TARGET FOR EDIT: Add total_amount field with float = 0.0
'''
    f1.write_text(f1_content, encoding="utf-8")

    f2 = repo_dir / "order_service.py"
    f2_lines = [
        '"""Order handling and fulfilment service."""',
        "",
        "import logging",
        "from schema import Order, OrderItem",
        "",
        "logger = logging.getLogger(__name__)",
        "",
    ]
    for i in range(1, 20):
        f2_lines.extend(
            [
                f"class OrderHook_{i}:",
                "    def on_process(self, order: Order) -> None:",
                f"        logger.debug('Hook {i} executed')",
                "",
            ]
        )
    f2_lines.extend(
        [
            "class OrderService:",
            "    def calculate_total(self, order: Order) -> float:",
            "        # TARGET FOR EDIT: Calculate sum of item.price * item.quantity and set order.total_amount",
            "        total = sum(item.price * item.quantity for item in order.items)",
            "        return total",
            "",
        ]
    )
    f2.write_text("\n".join(f2_lines), encoding="utf-8")

    _safe_commit(repo_dir, "Initial commit multi")
    return ["schema.py", "order_service.py"]


# ---------------------------------------------------------------------------
# ベンチマーク実行関数
# ---------------------------------------------------------------------------
def execute_benchmark_run(
    repo_dir: Path,
    target_files: List[str],
    instruction: str,
    model: str,
    edit_format: str,
    timeout: int = 240,
    use_runner_api: bool = False,
) -> Dict[str, Any]:
    """Aider または runner API を実行し、所要時間・差分・構文妥当性を測定する。"""
    rev_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True
    ).stdout.strip()

    start_time = time.time()
    returncode = 0
    err_msg = ""

    if use_runner_api:
        # tools.aider_runner.run_aider を直接呼ぶ (hybrid / fallback 総合検証)
        try:
            ok = run_aider(
                instruction=instruction,
                target_files=target_files,
                cwd=str(repo_dir),
                model=model,
                timeout=timeout,
                edit_format=edit_format,
            )
            returncode = 0 if ok else 1
        except Exception as e:
            returncode = 1
            err_msg = str(e)
    else:
        # Aider CLI を直接 subprocess で実行
        env = os.environ.copy()
        env["AIDER_SHOW_MODEL_WARNINGS"] = "false"
        env["OLLAMA_API_BASE"] = "http://localhost:11434"

        cmd = [
            "uv",
            "run",
            "aider",
            "--model",
            model,
            "--no-auto-commits",
            "--yes-always",
            "--no-show-model-warnings",
            "--edit-format",
            edit_format,
            "--message",
            instruction,
        ] + target_files

        try:
            proc = subprocess.run(
                cmd,
                cwd=repo_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            returncode = proc.returncode
            err_msg = proc.stderr
        except subprocess.TimeoutExpired:
            returncode = -1
            err_msg = f"Timed out after {timeout} seconds"

    elapsed = time.time() - start_time

    # Git 差分チェック (untracked ファイルも add -N して検出)
    subprocess.run(["git", "add", "-N", "."], cwd=repo_dir, capture_output=True, check=False)
    diff_proc = subprocess.run(
        ["git", "diff"], cwd=repo_dir, capture_output=True, text=True, check=False
    )
    diff_output = diff_proc.stdout.strip()
    has_diff = len(diff_output) > 0
    diff_lines = len(diff_output.splitlines()) if has_diff else 0

    # 構文チェック (Python AST)
    syntax_valid = True
    for tf in target_files:
        p = repo_dir / tf
        if p.exists() and p.suffix == ".py":
            try:
                ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                syntax_valid = False
                break

    success = (returncode == 0) and has_diff and syntax_valid

    # 次のテストのために git reset --hard & clean
    subprocess.run(
        ["git", "reset", "--hard", rev_before], cwd=repo_dir, capture_output=True, check=True
    )
    subprocess.run(["git", "clean", "-fd"], cwd=repo_dir, capture_output=True, check=True)

    return {
        "model": model,
        "edit_format": edit_format,
        "success": success,
        "returncode": returncode,
        "elapsed_sec": round(elapsed, 1),
        "has_diff": has_diff,
        "diff_lines": diff_lines,
        "syntax_valid": syntax_valid,
        "err_msg": err_msg[:200] if err_msg else "",
    }


# ---------------------------------------------------------------------------
# メイン実行関数
# ---------------------------------------------------------------------------
def run_all_benchmarks(
    models: List[str],
    scenarios: List[str],
    formats: List[str],
    timeout: int,
) -> List[Dict[str, Any]]:
    all_results: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_path = Path(tmp_dir_str)
        repo_dir = create_mock_repo(tmp_path)

        for model in models:
            print("\n" + "=" * 76)
            print(f"  モデル検証: {model}")
            print("=" * 76)

            # --- Scenario 1: 小規模 (~50行) ---
            if "small" in scenarios:
                print("\n[シナリオ 1] 小規模 (~50行: calculator.py バグ修正)")
                generate_small_file(repo_dir)
                instr = "In calculator.py, fix the bug in the add function so that it returns a + b instead of a - b."
                for fmt in formats:
                    print(f"  ▶ format={fmt:6s} ... ", end="", flush=True)
                    res = execute_benchmark_run(
                        repo_dir, ["calculator.py"], instr, model, fmt, timeout=timeout
                    )
                    status = "PASS" if res["success"] else "FAIL"
                    print(
                        f"[{status}] 時間: {res['elapsed_sec']:5.1f}s | 差分行数: {res['diff_lines']:3d} | 構文: {res['syntax_valid']}"
                    )
                    res["scenario"] = "小 (~50行)"
                    all_results.append(res)

            # --- Scenario 2: 中規模 (~250行) ---
            if "medium" in scenarios:
                print("\n[シナリオ 2] 中規模 (~250行: processor.py 例外処理追加)")
                generate_medium_file(repo_dir)
                instr = "In processor.py, in PipelineRunner.process_records, wrap the float(r.get('value', 0)) conversion in a try-except ValueError block and log a warning if it fails."
                for fmt in formats:
                    print(f"  ▶ format={fmt:6s} ... ", end="", flush=True)
                    res = execute_benchmark_run(
                        repo_dir, ["processor.py"], instr, model, fmt, timeout=timeout
                    )
                    status = "PASS" if res["success"] else "FAIL"
                    print(
                        f"[{status}] 時間: {res['elapsed_sec']:5.1f}s | 差分行数: {res['diff_lines']:3d} | 構文: {res['syntax_valid']}"
                    )
                    res["scenario"] = "中 (~250行)"
                    all_results.append(res)

            # --- Scenario 3: 大規模 (~600行) ---
            if "large" in scenarios:
                print("\n[シナリオ 3] 大規模 (~600行: system_orchestrator.py ガード処理追加)")
                generate_large_file(repo_dir)
                instr = "In system_orchestrator.py, in SystemWorkflowCoordinator.execute_workflow, add a guard at the beginning: if not context.trace_id, raise ValueError('Missing trace_id')."
                for fmt in formats:
                    print(f"  ▶ format={fmt:6s} ... ", end="", flush=True)
                    res = execute_benchmark_run(
                        repo_dir, ["system_orchestrator.py"], instr, model, fmt, timeout=timeout
                    )
                    status = "PASS" if res["success"] else "FAIL"
                    print(
                        f"[{status}] 時間: {res['elapsed_sec']:5.1f}s | 差分行数: {res['diff_lines']:3d} | 構文: {res['syntax_valid']}"
                    )
                    res["scenario"] = "大 (~600行)"
                    all_results.append(res)

            # --- Scenario 4: 日本語混在コード (~150行) ---
            if "japanese" in scenarios:
                print(
                    "\n[シナリオ 4] 日本語混在コード (~150行: auth_service.py バリデーション強化)"
                )
                generate_japanese_file(repo_dir)
                instr = "auth_service.py の UserSessionManager.validate_request メソッドの先頭に、token_str が None または空文字（not token_str）の場合に直ちに False を返すガード節を追加してください。"
                for fmt in formats:
                    print(f"  ▶ format={fmt:6s} ... ", end="", flush=True)
                    res = execute_benchmark_run(
                        repo_dir, ["auth_service.py"], instr, model, fmt, timeout=timeout
                    )
                    status = "PASS" if res["success"] else "FAIL"
                    print(
                        f"[{status}] 時間: {res['elapsed_sec']:5.1f}s | 差分行数: {res['diff_lines']:3d} | 構文: {res['syntax_valid']}"
                    )
                    res["scenario"] = "日本語 (~150行)"
                    all_results.append(res)

            # --- Scenario 5: 新規ファイル作成 (0行) ---
            if "new_file" in scenarios:
                print("\n[シナリオ 5] 新規ファイル作成 (未存在ファイル: utils/string_helper.py)")
                instr = "Create a new file utils/string_helper.py containing a function 'truncate(text: str, max_len: int = 50) -> str' that truncates text with '...' if longer than max_len."
                for fmt in ["whole", "diff"]:
                    print(f"  ▶ format={fmt:6s} ... ", end="", flush=True)
                    res = execute_benchmark_run(
                        repo_dir, ["utils/string_helper.py"], instr, model, fmt, timeout=timeout
                    )
                    status = "PASS" if res["success"] else "FAIL"
                    print(
                        f"[{status}] 時間: {res['elapsed_sec']:5.1f}s | 差分行数: {res['diff_lines']:3d} | 構文: {res['syntax_valid']}"
                    )
                    res["scenario"] = "新規作成 (0行)"
                    all_results.append(res)

            # --- Scenario 6: Hybrid & 自動フォールバック総合検証 ---
            if "hybrid_e2e" in scenarios:
                print("\n[シナリオ 6] Hybrid 実機パイプライン検証 (tools.aider_runner.run_aider)")
                # A: 50行ファイル (whole への自動ルーティング確認)
                generate_small_file(repo_dir)
                print("  ▶ [A] 50行ファイル (hybrid ➔ whole 期待) ... ", end="", flush=True)
                res_a = execute_benchmark_run(
                    repo_dir,
                    ["calculator.py"],
                    "In calculator.py, fix add function to return a + b.",
                    model,
                    "hybrid",
                    timeout=timeout,
                    use_runner_api=True,
                )
                status_a = "PASS" if res_a["success"] else "FAIL"
                print(
                    f"[{status_a}] 時間: {res_a['elapsed_sec']:5.1f}s | 差分行数: {res_a['diff_lines']:3d}"
                )
                res_a["scenario"] = "Hybrid:小➔whole"
                all_results.append(res_a)

                # B: 250行ファイル (diff への自動ルーティング確認)
                generate_medium_file(repo_dir)
                print("  ▶ [B] 250行ファイル (hybrid ➔ diff 期待) ... ", end="", flush=True)
                res_b = execute_benchmark_run(
                    repo_dir,
                    ["processor.py"],
                    "In processor.py, in PipelineRunner.process_records, wrap float(r.get('value', 0)) in try-except ValueError.",
                    model,
                    "hybrid",
                    timeout=timeout,
                    use_runner_api=True,
                )
                status_b = "PASS" if res_b["success"] else "FAIL"
                print(
                    f"[{status_b}] 時間: {res_b['elapsed_sec']:5.1f}s | 差分行数: {res_b['diff_lines']:3d}"
                )
                res_b["scenario"] = "Hybrid:大➔diff"
                all_results.append(res_b)

            # --- Scenario 7: 複数ファイル同時編集 (schema.py 40行 + order_service.py 220行) ---
            if "multi_file" in scenarios:
                print("\n[シナリオ 7] 複数ファイル同時編集 (schema.py + order_service.py)")
                files = generate_multi_files(repo_dir)
                instr = (
                    "In schema.py, add field total_amount: float = 0.0 to class Order. "
                    "In order_service.py, in OrderService.calculate_total, calculate total from item.price * item.quantity "
                    "and set order.total_amount = total."
                )
                for fmt in ["whole", "diff"]:
                    print(f"  ▶ format={fmt:6s} ... ", end="", flush=True)
                    res = execute_benchmark_run(repo_dir, files, instr, model, fmt, timeout=timeout)
                    status = "PASS" if res["success"] else "FAIL"
                    print(
                        f"[{status}] 時間: {res['elapsed_sec']:5.1f}s | 差分行数: {res['diff_lines']:3d} | 構文: {res['syntax_valid']}"
                    )
                    res["scenario"] = "複数ファイル"
                    all_results.append(res)

    return all_results


def print_summary_table(results: List[Dict[str, Any]]) -> None:
    """結果サマリを視覚的な Markdown 表で整形出力する。"""
    print("\n" + "=" * 76)
    print("  多角的ベンチマーク結果総合サマリ")
    print("=" * 76)
    print(
        f"| {'モデル':18s} | {'シナリオ':16s} | {'Format':8s} | {'合否':6s} | {'所要時間':8s} | {'差分行数':8s} |"
    )
    print(
        "| "
        + "-" * 18
        + " | "
        + "-" * 16
        + " | "
        + "-" * 8
        + " | "
        + "-" * 6
        + " | "
        + "-" * 8
        + " | "
        + "-" * 8
        + " |"
    )
    for r in results:
        model_name = r["model"].split("/")[-1].split(":")[0]
        verdict = "**PASS**" if r["success"] else "FAIL"
        print(
            f"| {model_name:18s} | {r.get('scenario', '-'):16s} | {r['edit_format']:8s} | {verdict:6s} | {r['elapsed_sec']:6.1f}s  | {r['diff_lines']:6d}行  |"
        )
    print("=" * 76)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aider edit_format 多角的実証ベンチマーク")
    parser.add_argument(
        "--models",
        default="ollama/ornith-1.5-9b:latest",
        help="対象モデル (カンマ区切りで複数指定可能)",
    )
    parser.add_argument(
        "--scenarios",
        default="small,medium,large,japanese,new_file,hybrid_e2e,multi_file",
        help="実行シナリオ (small,medium,large,japanese,new_file,hybrid_e2e,multi_file,all)",
    )
    parser.add_argument(
        "--formats",
        default="whole,diff",
        help="比較フォーマット (カンマ区切り)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=240,
        help="各実行のタイムアウト秒数",
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    if args.scenarios == "all":
        scenarios = ["small", "medium", "large", "japanese", "new_file", "hybrid_e2e", "multi_file"]
    else:
        scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]

    print(f"ベンチマーク開始: モデル={models}, シナリオ={scenarios}, フォーマット={formats}")
    results = run_all_benchmarks(models, scenarios, formats, timeout=args.timeout)
    print_summary_table(results)


if __name__ == "__main__":
    main()
