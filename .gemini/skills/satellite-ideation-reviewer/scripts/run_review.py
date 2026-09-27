#!/usr/bin/env python3
"""satellite-ideation-reviewer: agys によるサテライトコード自律レビュー＆Issue自動起票スクリプト.

サテライトリポジトリ（projects/<name>/）のコードを agys で自律レビューし、
既存 Issue との重複チェック（ステータス不問）を経て、stage:ideation ラベル付きで
GitHub Issue を自律起票します。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ロガー設定: 標準出力を汚さないよう sys.stderr に出力（ユーザーグローバルルール準拠）
logger = logging.getLogger("satellite_reviewer")
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)


THEME_CONFIGS: dict[str, dict[str, str]] = {
    "security": {
        "name": "セキュリティ",
        "guidelines": (
            "- 入力バリデーションの欠落（外部入力、ファイル入力、引数など）\n"
            "- パストラバーサル脆弱性（os.path.join や Path 解決時の検証不足）\n"
            "- コマンドインジェクション、危険なAPI呼び出し（shell=True, eval, exec 等）\n"
            "- ハードコードされた秘密情報、APIトークン、認証情報\n"
            "- 安全でないファイルパーミッションや一時ファイルの取り扱い"
        ),
    },
    "edge_cases": {
        "name": "エッジケース処理",
        "guidelines": (
            "- None, 空文字列, 空リスト, 空辞書に対する防御的処理の欠落\n"
            "- 存在しないファイル・ディレクトリやアクセス権限エラー時のハンドリング\n"
            "- ネットワークや外部プロセスのタイムアウト、リトライ、切断時のフォールバック\n"
            "- 境界値条件（インデックス範囲外、0除算、巨大入力）に対する堅牢性\n"
            "- 例外の不適切な握りつぶし（bare except）やエラー情報の消失"
        ),
    },
    "architecture": {
        "name": "関心事の分離（アーキテクチャ境界）",
        "guidelines": (
            "- 単一責任の原則（1つのクラス・関数が過剰な責務を持っていないか）\n"
            "- レイヤー間の結合度（ビジネスロジックとインフラ/IO処理の過度な密結合）\n"
            "- グローバル状態の乱用や暗黙の副作用\n"
            "- 循環依存や不透明なモジュール間依存\n"
            "- 将来の拡張性・テスト容易性を阻害している設計の歪み"
        ),
    },
}

REQUIRED_LABELS: dict[str, tuple[str, str]] = {
    "stage:ideation": ("cfd3d7", "構想・壁打ち中（実装対象外）"),
    "theme:security": ("d93f0b", "セキュリティ脆弱性・安全対策"),
    "theme:edge_cases": ("e99695", "エッジケース・異常系堅牢化"),
    "theme:architecture": ("bfd4f2", "関心事の分離・構造改善"),
}


@dataclass
class ReviewItem:
    """agys から抽出されたレビュー指摘項目."""

    title: str
    target_file: str
    severity: str  # High, Medium, Low
    summary: str
    problem_detail: str
    suggested_solution: str
    keywords: list[str] = field(default_factory=list)
    related_issue_note: str = ""


@dataclass
class ExistingIssue:
    """既存の GitHub Issue 情報."""

    number: int
    title: str
    state: str  # OPEN, CLOSED
    body: str = ""
    labels: list[str] = field(default_factory=list)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """CLI 引数をパースする."""
    parser = argparse.ArgumentParser(
        description="agys を使用したサテライト自律レビュー＆Issue自動起票ツール"
    )
    parser.add_argument(
        "--target",
        required=True,
        help="対象サテライト名（例: env_builder, test_file_grep）。projects/<name> 配下を指定。",
    )
    parser.add_argument(
        "--theme",
        required=True,
        choices=list(THEME_CONFIGS.keys()),
        help="レビューテーマ (security, edge_cases, architecture)",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=3,
        help="1回の実行で起票する最大 Issue 数（デフォルト: 3）",
    )
    parser.add_argument(
        "--path",
        default="",
        help="サテライト内の特定サブディレクトリやファイルにスコープを限定（相対パス）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の Issue 起票を行わず、検知結果とプレビューを出力する",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細デバッグログを出力する",
    )
    parser.add_argument(
        "--mock-response",
        help=argparse.SUPPRESS,  # テスト用モック JSON 文字列またはファイルパス
    )
    return parser.parse_args(args)


def validate_target_repo(repo_root: Path, target_name: str) -> Path:
    """対象サテライトのパスを検証し、母艦保護を行う."""
    # 母艦自身を直接レビューすることは禁止
    if target_name in ("second-brain-graph", ".", ""):
        raise ValueError(
            "母艦リポジトリ（second-brain-graph）はレビュー対象外です。サテライト名を指定してください。"
        )

    target_dir = repo_root / "projects" / target_name
    if not target_dir.is_dir():
        raise FileNotFoundError(f"指定されたサテライトディレクトリが存在しません: {target_dir}")

    return target_dir


def fetch_existing_issues(target_dir: Path) -> list[ExistingIssue]:
    """対象サテライトの既存 Issue を全件（Open/Closed）取得する."""
    cmd = [
        "gh",
        "issue",
        "list",
        "--state",
        "all",
        "--limit",
        "100",
        "--json",
        "number,title,state,body,labels",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        data = json.loads(result.stdout)
        issues: list[ExistingIssue] = []
        for item in data:
            labels = [
                lbl["name"] if isinstance(lbl, dict) else str(lbl) for lbl in item.get("labels", [])
            ]
            issues.append(
                ExistingIssue(
                    number=item.get("number", 0),
                    title=item.get("title", ""),
                    state=item.get("state", "OPEN").upper(),
                    body=item.get("body", ""),
                    labels=labels,
                )
            )
        logger.info(f"既存 Issue {len(issues)} 件を取得しました（Open/Closed 全件照合用）")
        return issues
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"既存 Issue の取得に失敗しました（GitHub 連携未設定または offline）: {e}")
        return []


def collect_target_files(target_dir: Path, subpath: str = "") -> list[str]:
    """レビュー対象となるソースコードファイルの相対パス一覧を収集する."""
    base_path = target_dir / subpath if subpath else target_dir
    if base_path.is_file():
        return [str(base_path.relative_to(target_dir)).replace("\\", "/")]

    valid_extensions = {
        ".py",
        ".ts",
        ".js",
        ".go",
        ".rs",
        ".sh",
        ".bash",
        ".ps1",
        ".json",
        ".yaml",
        ".yml",
    }
    ignore_dirs = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "docs",
    }

    collected: list[str] = []
    for root, dirs, files in os.walk(base_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in valid_extensions:
                rel = str(p.relative_to(target_dir)).replace("\\", "/")
                collected.append(rel)

    return sorted(collected)


def build_review_prompt(
    theme_key: str,
    target_files: list[str],
    existing_issues: list[ExistingIssue],
) -> str:
    """agys に渡すレビュー指示プロンプトを構築する."""
    theme_info = THEME_CONFIGS[theme_key]
    files_str = "\n".join(f"- {f}" for f in target_files[:50])  # 上限50ファイル

    existing_issues_str = "\n".join(
        f"- #{iss.number} [{iss.state}] {iss.title}" for iss in existing_issues[:30]
    )
    if not existing_issues_str:
        existing_issues_str = "（既存 Issue なし）"

    prompt = f"""あなたは専門のシニアコードレビューアナリストです。
以下の指示に従い、指定されたコードベースの分析を実施してください。

【最重要制約: Read-Only の厳格遵守】
あなたは分析とレポートのみを行います。
ファイルの新規作成、編集、削除、シェルコマンドの実行など、作業ツリーを変更する操作は一切禁止されています。
コードの読み取りのみを行ってください。

【レビューテーマ: {theme_info["name"]}】
以下の観点に厳密に集中してコードを分析し、潜在的な不具合、リスク、改善点を検出してください:
{theme_info["guidelines"]}

【対象ファイル候補】
{files_str}

【既存の Issue リスト（重複回避のため参照）】
{existing_issues_str}

【出力形式の要件】
分析結果は、以下の構造を持つ単一の JSON オブジェクトとして出力してください。
マークダウンのコードブロック（```json ... ```）の中に JSON のみを記述してください。余計な挨拶や説明文は出力しないでください。

```json
{{
  "reviews": [
    {{
      "title": "[{theme_key}] 簡潔かつ具体的な課題タイトル（例: file_utils におけるパストラバーサル防止の不備）",
      "target_file": "対象ファイルパス#行番号（例: src/utils/file_utils.py#L30-L45）",
      "severity": "High" | "Medium" | "Low",
      "summary": "問題の簡潔な要約（1〜2行）",
      "problem_detail": "何が起きているか、どのようなリスクがあるかの詳細説明",
      "suggested_solution": "推奨される具体的な修正案やアプローチ、改善方針",
      "keywords": ["関連キーワード1", "キーワード2"]
    }}
  ]
}}
```

問題が検知されなかった場合は、`"reviews": []` を返してください。
"""
    return prompt


def parse_agys_response(raw_output: str) -> list[ReviewItem]:
    """agys の出力文字列から JSON を抽出し、ReviewItem のリストに変換する."""
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_output)
    json_str = json_match.group(1) if json_match else raw_output.strip()

    # JSON 開始中括弧から終了中括弧までを抽出（前後にテキストが混ざる対策）
    first_brace = json_str.find("{")
    last_brace = json_str.rfind("}")
    if first_brace != -1 and last_brace != -1:
        json_str = json_str[first_brace : last_brace + 1]

    data = json.loads(json_str)
    reviews_data = data.get("reviews", [])

    items: list[ReviewItem] = []
    for r in reviews_data:
        severity = r.get("severity", "Medium").capitalize()
        if severity not in ("High", "Medium", "Low"):
            severity = "Medium"
        items.append(
            ReviewItem(
                title=r.get("title", "未命名の課題"),
                target_file=r.get("target_file", "unknown"),
                severity=severity,
                summary=r.get("summary", ""),
                problem_detail=r.get("problem_detail", ""),
                suggested_solution=r.get("suggested_solution", ""),
                keywords=r.get("keywords", []),
            )
        )
    return items


def resolve_agy_executable() -> str:
    """agy.exe の実行可能ファイルパスを解決する."""
    import shutil

    for candidate in ("agy.exe", "agy"):
        found = shutil.which(candidate)
        if found:
            return found

    known_paths = [
        Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
        Path.home() / ".cargo" / "bin" / "agy.exe",
    ]
    for p in known_paths:
        if p.is_file():
            return str(p)

    return "agy"


def run_agys_review(
    target_dir: Path,
    prompt: str,
    mock_response: str | None = None,
) -> list[ReviewItem]:
    """agys を呼び出してレビュー結果を取得する."""
    if mock_response:
        # モック指定がある場合（テスト用）
        if os.path.exists(mock_response):
            with open(mock_response, encoding="utf-8") as f:
                content = f.read()
        else:
            content = mock_response
        return parse_agys_response(content)

    agy_exe = resolve_agy_executable()
    logger.info(f"agys（Antigravity CLI ヘッドレス: {agy_exe}）を起動して自律レビューを実行中...")
    cmd = [agy_exe, "--dangerously-skip-permissions", "-p", prompt]

    try:
        proc = subprocess.run(
            cmd,
            cwd=target_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,  # 3分タイムアウト
        )
        if proc.returncode != 0:
            logger.error(
                f"agys の実行がエラー終了しました (exit code {proc.returncode}): {proc.stderr}"
            )
            return []

        raw_output = proc.stdout.strip()
        if not raw_output:
            logger.warning(f"agys の出力が空でした。stderr: {proc.stderr}")
            return []

        return parse_agys_response(raw_output)
    except subprocess.TimeoutExpired:
        logger.error("agys のレビュー処理がタイムアウトしました (180s)")
        return []
    except Exception as e:
        logger.error(f"agys 実行または応答解析に失敗しました: {e}")
        return []


def check_duplicates(
    items: list[ReviewItem],
    existing_issues: list[ExistingIssue],
) -> list[ReviewItem]:
    """既存 Issue との重複チェックを行い、除外または例外追記を適用する."""
    filtered: list[ReviewItem] = []

    for item in items:
        is_duplicate_open = False
        matched_closed_issue: ExistingIssue | None = None

        # 抽出したキーワードとファイル名を正規化して照合
        item_file = item.target_file.split("#")[0].strip().lower()
        item_title_words = set(re.findall(r"[\w]+", item.title.lower()))

        for ex in existing_issues:
            ex_title_words = set(re.findall(r"[\w]+", ex.title.lower()))
            overlap = item_title_words.intersection(ex_title_words)

            # タイトルの主要キーワードが複数一致、またはファイルパスが一致かつタイトルが類似
            file_match = item_file and item_file in ex.body.lower()
            keyword_match = len(overlap) >= 3 or (len(overlap) >= 2 and file_match)

            if keyword_match:
                if ex.state == "OPEN":
                    is_duplicate_open = True
                    logger.info(f"スキップ（既存 Open Issue #{ex.number} と重複）: {item.title}")
                    break
                elif ex.state == "CLOSED" and matched_closed_issue is None:
                    matched_closed_issue = ex

        if is_duplicate_open:
            continue

        if matched_closed_issue is not None:
            # Closed Issue と重複する場合は例外的に起票するが、その旨を明記
            item.related_issue_note = (
                f"過去に類似の課題（Issue #{matched_closed_issue.number}: Closed）が存在しましたが、"
                f"再発防止または別観点（テーマ）からの再確認のため起票します。"
            )
            logger.info(
                f"過去 Closed Issue #{matched_closed_issue.number} と類似のため、注記を付与して起票対象とします: {item.title}"
            )

        filtered.append(item)

    return filtered


def filter_and_cap_issues(items: list[ReviewItem], max_issues: int) -> list[ReviewItem]:
    """重要度順にソートし、最大起票件数（Cap）で切り詰める."""
    severity_order = {"High": 0, "Medium": 1, "Low": 2}
    sorted_items = sorted(items, key=lambda x: severity_order.get(x.severity, 1))
    return sorted_items[:max_issues]


def format_issue_body(item: ReviewItem, theme_key: str) -> str:
    """起票用 Issue 本文の Markdown を生成する."""
    theme_name = THEME_CONFIGS.get(theme_key, {}).get("name", theme_key)
    rel_note = item.related_issue_note or "該当なし"

    body = f"""## 検出テーマ: {theme_name}
- **対象ファイル**: `{item.target_file}`
- **重要度**: {item.severity}

### 課題・懸念点 (What & Why)
{item.summary}

{item.problem_detail}

### 改善提案 (Suggested Approach)
{item.suggested_solution}

### 過去の関連 Issue
- {rel_note}

---
*※ 本 Issue は `agys` 自律レビューにより自動起票されました（`stage:ideation`）。壁打ち・検討後に `stage:ready` へ昇格してください。*
"""
    return body


def ensure_satellite_labels(target_dir: Path, theme_key: str, dry_run: bool = False) -> None:
    """対象サテライトリポジトリに必要な GitHub ラベル（stage:ideation, theme:<theme>）が存在することを保証する."""
    needed_labels = ["stage:ideation", f"theme:{theme_key}"]
    if dry_run:
        logger.debug(f"[DRY-RUN] ラベル存在確認・自動作成をスキップ: {needed_labels}")
        return

    existing: set[str] = set()
    try:
        res = subprocess.run(
            ["gh", "label", "list", "--json", "name"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        existing = {item.get("name", "") for item in json.loads(res.stdout)}
    except Exception as e:
        logger.warning(f"既存ラベルの確認に失敗しました: {e}")

    for lbl in needed_labels:
        if lbl not in existing:
            color, desc = REQUIRED_LABELS.get(lbl, ("ededed", "Auto-generated label"))
            try:
                subprocess.run(
                    [
                        "gh",
                        "label",
                        "create",
                        lbl,
                        "--color",
                        color,
                        "--description",
                        desc,
                        "--force",
                    ],
                    cwd=target_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8",
                )
                logger.info(f"ラベル '{lbl}' を自動作成・同期しました")
            except Exception as e:
                logger.warning(f"ラベル '{lbl}' の自動作成に失敗しました: {e}")


def create_github_issue(target_dir: Path, item: ReviewItem, theme_key: str, dry_run: bool) -> bool:
    """GitHub Issue を作成する（stage:ideation, theme:<theme> ラベル付き）."""
    body = format_issue_body(item, theme_key)
    labels = ["stage:ideation", f"theme:{theme_key}"]

    if dry_run:
        print("\n" + "=" * 60)
        print(f"[DRY-RUN] 起票対象: {item.title}")
        print(f"[Labels]: {', '.join(labels)}")
        print("-" * 60)
        print(body.strip())
        print("=" * 60 + "\n")
        return True

    cmd = [
        "gh",
        "issue",
        "create",
        "--title",
        item.title,
        "--body",
        body,
        "--label",
        labels[0],
        "--label",
        labels[1],
    ]
    try:
        res = subprocess.run(
            cmd,
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        issue_url = res.stdout.strip()
        logger.info(f"Issue 起票完了: {issue_url}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Issue 起票に失敗しました ({item.title}): {e.stderr}")
        return False


def main(args: list[str] | None = None) -> int:
    """メイン実行フロー."""
    opts = parse_args(args)
    if opts.verbose:
        logger.setLevel(logging.DEBUG)

    repo_root = Path(__file__).resolve().parents[4]

    try:
        target_dir = validate_target_repo(repo_root, opts.target)
    except Exception as e:
        logger.error(str(e))
        return 1

    logger.info(f"ターゲット: {opts.target} | テーマ: {opts.theme} | 上限: {opts.max_issues} 件")

    # 1. 既存 Issue 取得（Open/Closed 全件）
    existing_issues = fetch_existing_issues(target_dir)

    # 2. 対象ファイル収集
    target_files = collect_target_files(target_dir, opts.path)
    if not target_files:
        logger.warning(f"対象となるコードファイルが見つかりませんでした: {opts.target}")
        return 0
    logger.info(f"レビュー対象コードファイル数: {len(target_files)} 件")

    # 3. プロンプト生成
    prompt = build_review_prompt(opts.theme, target_files, existing_issues)

    # 4. agys 実行（またはモック実行）
    raw_items = run_agys_review(target_dir, prompt, opts.mock_response)
    logger.info(f"agys レビュー検知項目数: {len(raw_items)} 件")

    if not raw_items:
        logger.info("検出された改善提案・課題はありませんでした。")
        return 0

    # 5. 重複チェック（ステータス不問）
    unique_items = check_duplicates(raw_items, existing_issues)

    # 6. 上限件数（Cap）の適用
    final_items = filter_and_cap_issues(unique_items, opts.max_issues)
    logger.info(f"起票対象項目数（Cap 適用後）: {len(final_items)} 件")

    # 7. Issue 起票（またはドライラン）
    if final_items:
        ensure_satellite_labels(target_dir, opts.theme, opts.dry_run)

    success_count = 0
    for item in final_items:
        if create_github_issue(target_dir, item, opts.theme, opts.dry_run):
            success_count += 1

    logger.info(
        f"処理完了: {success_count}/{len(final_items)} 件の Issue を処理しました (dry_run={opts.dry_run})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
