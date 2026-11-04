"""tools/edit_guard.py - コード編集エンジン（Aider / agy）用書き込み境界ガード.

コード編集エンジンが作業ツリー外や対象外ファイル、母艦リポジトリそのものを
破壊・汚染することを防止する防護層。
実行前検証、スナップショット取得、事後ロールバック、および監査レポートの生成を行う。
"""

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger("edit_guard")


class EditGuardError(Exception):
    """書き込み境界ガード違反時の基底例外."""

    pass


class MotherRepositoryProtectionError(EditGuardError):
    """母艦リポジトリへの直接書き込みが試みられた場合の例外."""

    pass


@dataclass(frozen=True)
class GuardReport:
    """事後ロールバック結果の監査レポート."""

    violations: List[str] = field(default_factory=list)
    reverted: List[str] = field(default_factory=list)


SECRET_FILE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "token.json",
    "credentials.json",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
]


def _get_mother_root() -> Path:
    """母艦リポジトリのルートパスを解決する."""
    return Path(__file__).resolve().parent.parent


def validate_cwd_is_satellite(
    cwd: Optional[str | Path],
    mother_root: Optional[Path] = None,
    require_exists: bool = False,
) -> Path:
    """cwd が母艦リポジトリではなく、正当なサテライトディレクトリであることを検証する.

    - cwd が未指定または空文字の場合は EditGuardError
    - cwd が母艦リポジトリそのもの、または母艦の管理ディレクトリ（tools, config, docs, tests等）の場合は
      MotherRepositoryProtectionError を送出する
    - require_exists=True の場合、cwd が実在するディレクトリで Git リポジトリであることを検証する
    """
    if not cwd:
        raise EditGuardError("cwd must be specified for code edit operations")

    cwd_path = Path(cwd).resolve()
    mother = (mother_root or _get_mother_root()).resolve()

    # 母艦リポジトリ自身、または母艦配下で projects 外のパスは拒否
    if cwd_path == mother:
        raise MotherRepositoryProtectionError(
            f"母艦リポジトリ（{mother}）での直接コード編集は固く禁止されています。"
        )

    try:
        # 母艦配下にある場合、projects/ 配下であることを強制
        rel = cwd_path.relative_to(mother)
        parts = rel.parts
        if not (len(parts) >= 2 and parts[0] == "projects"):
            raise MotherRepositoryProtectionError(
                f"母艦内部のディレクトリ（{cwd_path}）への書き込みは許可されていません。projects/ 配下の衛星を指定してください。"
            )
    except ValueError:
        # 母艦の外部にある独立ディレクトリの場合は許可（外部ワークスペース等）
        pass

    if require_exists:
        if not cwd_path.exists() or not cwd_path.is_dir():
            raise EditGuardError(f"Specified cwd does not exist or is not a directory: {cwd_path}")
        git_dir = cwd_path / ".git"
        if not git_dir.exists():
            raise EditGuardError(f"cwd is not a git repository (missing .git): {cwd_path}")
    elif cwd_path.exists() and cwd_path.is_dir():
        # 実在する場合は git チェック（存在しないモックパスはスキップ）
        git_dir = cwd_path / ".git"
        if (cwd_path / "pyproject.toml").exists() and not git_dir.exists() and cwd_path == mother:
            raise MotherRepositoryProtectionError(
                "母艦リポジトリへの直接書き込みは禁止されています。"
            )

    return cwd_path


def detect_secret_files(cwd: Path) -> List[str]:
    """作業ツリー内の機密情報ファイル（.env, *.pem 等）を検出する."""
    found: List[str] = []
    for pattern in SECRET_FILE_PATTERNS:
        # サブディレクトリも含めて走査（.git は除外）
        for match in cwd.glob(pattern):
            if ".git" not in match.parts:
                found.append(match.relative_to(cwd).as_posix())
        for match in cwd.glob(f"**/{pattern}"):
            if ".git" not in match.parts:
                posix = match.relative_to(cwd).as_posix()
                if posix not in found:
                    found.append(posix)
    return sorted(found)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Git コマンドを実行する."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _parse_porcelain_line(line: str) -> Tuple[str, str, Optional[str]]:
    """`git status --porcelain` の 1 行を解析する."""
    xy = line[:2]
    rest = line[3:].strip()
    old_path = None
    if " -> " in rest:
        old_part, new_part = rest.split(" -> ", 1)
        old_path = old_part.strip().strip('"')
        raw_filename = new_part.strip().strip('"')
    else:
        raw_filename = rest.strip('"')
    return xy, raw_filename, old_path


def _is_protected_path(posix_file: str, normalized_targets: Set[str]) -> bool:
    """保護対象パス（編集許可ファイル・自動生成許可・設定）かどうかを判定する."""
    return (
        posix_file in normalized_targets
        or posix_file.startswith(".aider")
        or posix_file.startswith(".agy")
        or posix_file.startswith(".pytest")
        or posix_file == ".gitignore"
    )


def warn_if_working_tree_dirty(cwd: Optional[str | Path], target_files: List[str]) -> None:
    """編集実行前に作業ツリーが clean でない場合、警告ログを残す."""
    if not cwd:
        return
    cwd_path = Path(cwd)
    if not cwd_path.exists():
        return
    normalized_targets = {Path(tf).as_posix() for tf in target_files}
    try:
        res = _git(cwd_path, "status", "--porcelain")
        if res.returncode != 0:
            return
        dirty = []
        for line in res.stdout.splitlines():
            if not line.strip():
                continue
            xy, raw_filename, _ = _parse_porcelain_line(line)
            posix_file = Path(raw_filename).as_posix()
            if not _is_protected_path(posix_file, normalized_targets):
                dirty.append(line)
        if dirty:
            logger.warning(
                "[Edit Guard] Working tree is not clean before running edit engine; "
                f"changes outside target_files may be reverted: {dirty[:5]}"
            )
    except Exception as e:
        logger.warning(f"Failed to check working tree before running edit engine: {e}")


@dataclass
class GuardSnapshot:
    """編集実行前の状態スナップショット."""

    cwd: Path
    target_files: List[str]
    gitignore_content: Optional[str] = None
    gitignore_existed: bool = False
    manage_gitignore: bool = False
    detected_secrets: List[str] = field(default_factory=list)


def prepare_guard(
    cwd: Optional[str | Path],
    target_files: List[str],
    mother_root: Optional[Path] = None,
) -> GuardSnapshot:
    """実行前の境界検証とスナップショットの取得を行う.

    1. cwd が母艦でないこと・正当なサテライトであることを検証
    2. 秘密情報ファイルの検出
    3. .gitignore の内容を退避
    4. 作業ツリーの dirty 警告
    """
    cwd_path = validate_cwd_is_satellite(cwd, mother_root=mother_root)
    secrets = detect_secret_files(cwd_path)
    if secrets:
        logger.warning(f"[Edit Guard] Secret-like files detected in workspace: {secrets}")

    gitignore_path = cwd_path / ".gitignore"
    gitignore_existed = gitignore_path.exists()
    gitignore_content: Optional[str] = None
    if gitignore_existed and gitignore_path.is_file():
        try:
            gitignore_content = gitignore_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to snapshot .gitignore: {e}")

    warn_if_working_tree_dirty(cwd_path, target_files)
    return GuardSnapshot(
        cwd=cwd_path,
        target_files=target_files,
        gitignore_content=gitignore_content,
        gitignore_existed=gitignore_existed,
        manage_gitignore=True,
        detected_secrets=secrets,
    )


def rollback_unauthorized_changes(
    snapshot: GuardSnapshot,
    target_files: Optional[List[str]] = None,
) -> GuardReport:
    """target_files 以外の変更を取り消し、Git ステータスを正常化する.

    - 未追跡のファイルおよびディレクトリ: ゴミとみなして削除
    - 追跡済みファイル: `git restore --staged --worktree` で HEAD の状態に復元
    - 新規ステージされたファイル: インデックスと作業ツリーから削除
    - .gitignore: 実行前のスナップショットと異なっていれば復元
    """
    cwd = snapshot.cwd
    effective_targets = target_files if target_files is not None else snapshot.target_files
    normalized_targets = {Path(tf).as_posix() for tf in effective_targets}

    reverted: List[str] = []
    violations: List[str] = []

    try:
        res = _git(cwd, "status", "--porcelain")
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if not line.strip():
                    continue
                xy, raw_filename, old_path = _parse_porcelain_line(line)
                posix_file = Path(raw_filename).as_posix()

                if _is_protected_path(posix_file, normalized_targets):
                    continue

                violations.append(f"{xy} {raw_filename}")
                file_path = cwd / raw_filename

                try:
                    if xy == "??":
                        # 未追跡ファイルまたはディレクトリの削除
                        if file_path.is_file() or file_path.is_symlink():
                            logger.warning(
                                f"[Edit Guard] Deleted untracked unauthorized artifact file: {raw_filename}"
                            )
                            file_path.unlink()
                            reverted.append(raw_filename)
                        elif file_path.is_dir():
                            logger.warning(
                                f"[Edit Guard] Deleted untracked unauthorized directory: {raw_filename}"
                            )
                            shutil.rmtree(file_path, ignore_errors=True)
                            reverted.append(raw_filename)
                    elif xy[0] in ("A", "C", "R"):
                        # 新規ステージされたファイルを取り消し
                        logger.warning(
                            f"[Edit Guard] Deleted newly added unauthorized file: {raw_filename}"
                        )
                        _git(cwd, "rm", "-f", "--", raw_filename)
                        if file_path.exists():
                            if file_path.is_dir():
                                shutil.rmtree(file_path, ignore_errors=True)
                            else:
                                file_path.unlink()
                        reverted.append(raw_filename)
                        if old_path:
                            _git(cwd, "restore", "--staged", "--worktree", "--", old_path)
                            reverted.append(old_path)
                    else:
                        # 追跡済みファイルの変更・削除の復元
                        logger.warning(
                            f"[Edit Guard] Restored tracked file modified outside target_files: {raw_filename}"
                        )
                        _git(cwd, "restore", "--staged", "--worktree", "--", raw_filename)
                        reverted.append(raw_filename)
                except Exception as ce:
                    logger.warning(f"[Edit Guard] Failed to revert {raw_filename}: {ce}")

        # .gitignore の巻き戻し確認（明示的に manage_gitignore が有効な場合のみ）
        if snapshot.manage_gitignore:
            gitignore_path = cwd / ".gitignore"
            if snapshot.gitignore_existed and snapshot.gitignore_content is not None:
                current_gitignore = (
                    gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else None
                )
                if current_gitignore != snapshot.gitignore_content:
                    logger.warning(
                        "[Edit Guard] .gitignore was modified; reverting to pre-edit state."
                    )
                    gitignore_path.write_text(snapshot.gitignore_content, encoding="utf-8")
                    _git(cwd, "restore", "--staged", "--worktree", "--", ".gitignore")
                    reverted.append(".gitignore")
            elif not snapshot.gitignore_existed and gitignore_path.exists():
                # 実行前になかったのに作成された場合
                logger.warning("[Edit Guard] .gitignore was newly created; removing.")
                gitignore_path.unlink()
                _git(cwd, "restore", "--staged", "--worktree", "--", ".gitignore")
                reverted.append(".gitignore")

    except Exception as e:
        logger.warning(f"[Edit Guard] Error during rollback: {e}")

    return GuardReport(violations=violations, reverted=reverted)


def cleanup_unauthorized_aider_artifacts(
    cwd: Optional[str | Path],
    target_files: List[str],
) -> List[str]:
    """後方互換性API: aider_runner / 既存テストから呼ばれる関数のアダプター."""
    if not cwd:
        return []
    cwd_path = Path(cwd)
    if not cwd_path.exists():
        return []
    snapshot = GuardSnapshot(
        cwd=cwd_path,
        target_files=target_files,
        gitignore_content=None,
    )
    report = rollback_unauthorized_changes(snapshot, target_files)
    return report.reverted
