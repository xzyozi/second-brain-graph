#!/usr/bin/env python3
"""tools/benchmark_aider_formats.py - Aider edit_format (whole vs diff vs udiff) 実証実験スクリプト

ローカルモデル (ornith-1.5-9b 等) に対して、異なるファイル規模（小規模〜中大規模）での
Aider コード編集成功率・所要時間・パッチ適用の安定性を自動測定・比較検証します。
"""

import ast
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

# プロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def create_mock_repo(base_dir: Path) -> Path:
    """隔離された一時 Git リポジトリを作成する。"""
    repo_dir = base_dir / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "BenchmarkUser"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "benchmark@example.com"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "input"], cwd=repo_dir, capture_output=True, check=True)

    return repo_dir


def generate_test_file_small(repo_dir: Path) -> Path:
    """小規模ファイル (約50行) を生成する。"""
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
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit small"], cwd=repo_dir, capture_output=True, check=True)
    return file_path


def generate_test_file_large(repo_dir: Path) -> Path:
    """中〜大規模ファイル (約250行) を生成する。"""
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

    # 200行以上のコードを擬似的に埋め込む
    for i in range(1, 25):
        lines.extend([
            f"class TransformerBlock{i}:",
            f'    """Transformer block {i}."""',
            f"    def __init__(self, scale: float = {i}.0):",
            "        self.scale = scale",
            "",
            "    def transform(self, val: float) -> float:",
            "        return val * self.scale",
            "",
        ])

    lines.extend([
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
    ])

    file_path.write_text("\n".join(lines), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit large"], cwd=repo_dir, capture_output=True, check=True)
    return file_path


def run_aider_benchmark(
    repo_dir: Path,
    target_file: str,
    instruction: str,
    model: str,
    edit_format: str,
    timeout: int = 300,
) -> Dict[str, Any]:
    """指定された edit_format で Aider を実行し結果を計測する。"""
    # 実行前の git HEAD コミットハッシュを記録
    rev_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True
    ).stdout.strip()

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
        target_file,
    ]

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time
        returncode = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        returncode = -1
        stdout = ""
        stderr = f"Timed out after {timeout} seconds"

    # Git 差分の確認
    diff_proc = subprocess.run(
        ["git", "diff"], cwd=repo_dir, capture_output=True, text=True, check=True
    )
    diff_output = diff_proc.stdout.strip()
    has_diff = len(diff_output) > 0
    diff_lines = len(diff_output.splitlines()) if has_diff else 0

    # 構文チェック (Python AST)
    target_path = repo_dir / target_file
    syntax_valid = False
    if target_path.exists():
        try:
            ast.parse(target_path.read_text(encoding="utf-8"))
            syntax_valid = True
        except SyntaxError:
            syntax_valid = False

    # 判定: returncode == 0 かつ diff が存在し、構文が正しいこと
    success = (returncode == 0) and has_diff and syntax_valid

    # 次のテストのために git reset --hard
    subprocess.run(["git", "reset", "--hard", rev_before], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_dir, capture_output=True, check=True)

    return {
        "edit_format": edit_format,
        "success": success,
        "returncode": returncode,
        "elapsed_sec": round(elapsed, 1),
        "has_diff": has_diff,
        "diff_lines": diff_lines,
        "syntax_valid": syntax_valid,
        "stdout_tail": stdout[-500:] if stdout else "",
        "stderr_tail": stderr[-500:] if stderr else "",
    }


def main() -> None:
    model = "ollama/ornith-1.5-9b:latest"
    formats = ["whole", "diff", "udiff"]

    print("=" * 70)
    print("  Aider edit_format 実証ベンチマーク (whole vs diff vs udiff)")
    print(f"  対象モデル: {model}")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_path = Path(tmp_dir_str)
        repo_dir = create_mock_repo(tmp_path)

        # -------------------------------------------------------------
        # Case 1: 小規模ファイル (約50行)
        # -------------------------------------------------------------
        print("\n--- [Case 1: 小規模ファイル (~50行)] calculator.py のバグ修正 ---")
        generate_test_file_small(repo_dir)
        small_instruction = "In calculator.py, fix the bug in the add function so that it returns a + b instead of a - b."

        results_small = []
        for fmt in formats:
            print(f"  ▶ 実行中: format={fmt:6s} ...", end="", flush=True)
            res = run_aider_benchmark(repo_dir, "calculator.py", small_instruction, model, fmt)
            status_str = "SUCCESS" if res["success"] else "FAILED"
            print(f" [{status_str}] 所要時間: {res['elapsed_sec']:5.1f}s, 差分行数: {res['diff_lines']}, 構文正常: {res['syntax_valid']}")
            results_small.append(res)

        # -------------------------------------------------------------
        # Case 2: 中〜大規模ファイル (約250行)
        # -------------------------------------------------------------
        print("\n--- [Case 2: 中規模ファイル (~250行)] processor.py の例外処理追加 ---")
        generate_test_file_large(repo_dir)
        large_instruction = "In processor.py, in the PipelineRunner.process_records method, wrap the float conversion in a try-except ValueError block and log a warning if it fails."

        results_large = []
        for fmt in formats:
            print(f"  ▶ 実行中: format={fmt:6s} ...", end="", flush=True)
            res = run_aider_benchmark(repo_dir, "processor.py", large_instruction, model, fmt)
            status_str = "SUCCESS" if res["success"] else "FAILED"
            print(f" [{status_str}] 所要時間: {res['elapsed_sec']:5.1f}s, 差分行数: {res['diff_lines']}, 構文正常: {res['syntax_valid']}")
            results_large.append(res)

    print("\n" + "=" * 70)
    print("  ベンチマーク結果サマリ")
    print("=" * 70)
    print(f"{'Format':8s} | {'規模':10s} | {'合否':8s} | {'所要時間':10s} | {'差分行数':8s} | {'構文':6s}")
    print("-" * 65)
    for r in results_small:
        verdict = "PASS" if r["success"] else "FAIL"
        print(f"{r['edit_format']:8s} | {'小 (~50行)':10s} | {verdict:8s} | {r['elapsed_sec']:8.1f}s | {r['diff_lines']:8d} | {'OK' if r['syntax_valid'] else 'NG'}")
    for r in results_large:
        verdict = "PASS" if r["success"] else "FAIL"
        print(f"{r['edit_format']:8s} | {'中 (~250行)':10s} | {verdict:8s} | {r['elapsed_sec']:8.1f}s | {r['diff_lines']:8d} | {'OK' if r['syntax_valid'] else 'NG'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
