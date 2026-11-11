"""Issue本文のTarget Files節からの編集対象ファイル抽出と、不正パスの検証 (#186).

Target Files節のバッククォート内に書かれた相対パスだけを、編集対象の唯一の定義元とする。
このモジュールはファイルシステムやGitに触れない純粋関数だけを提供する。
実在確認を行わないのは、新規作成ファイルも対象になり得るため。
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger("target_files")

#: Target Files節の見出しを判定するキーワード (小文字で比較する)
_SECTION_KEYWORDS = ("編集対象ファイル", "target files", "target_files")

_BACKTICK_PATTERN = re.compile(r"`([^`]*)`")
_LEGACY_PY_PATTERN = re.compile(r"[\w/.-]+\.py")
_DRIVE_LETTER_PATTERN = re.compile(r"^[A-Za-z]:")
_GLOB_CHARACTERS = frozenset("*?[]")

InvalidPath = Tuple[str, str]


class InvalidTargetFilesError(ValueError):
    """Target Files節に、編集対象として使えないパスが含まれている場合の例外."""

    def __init__(self, invalid: List[InvalidPath]) -> None:
        self.invalid = list(invalid)
        details = ", ".join(f"{path!r} ({reason})" for path, reason in self.invalid)
        super().__init__(f"Target Files に不正なパスが含まれています: {details}")


def normalize_target_path(path: str) -> str:
    """前後の空白を除去し、区切りを `/` に統一する (空白は名前の一部として保持する)."""
    return path.strip().replace("\\", "/")


def validate_target_file_path(path: str) -> Optional[str]:
    """編集対象として使えないパスなら理由を返し、有効なら None を返す.

    拒否するもの: 空、絶対パス、親ディレクトリ参照(`..`)、glob、ディレクトリ指定。
    """
    normalized = normalize_target_path(path)
    if not normalized:
        return "空のパスです"
    if normalized.startswith("/") or _DRIVE_LETTER_PATTERN.match(normalized):
        return "絶対パスは指定できません"
    if any(character in _GLOB_CHARACTERS for character in normalized):
        return "globは指定できません"
    if normalized.endswith("/"):
        return "ディレクトリは指定できません (ファイルを指定してください)"
    if ".." in normalized.split("/"):
        return "親ディレクトリ参照(..)は指定できません"
    return None


def _target_section_lines(issue_text: str) -> List[str]:
    """Target Files節に属する行を返す (次の見出しで終了する)."""
    section: List[str] = []
    in_section = False
    for line in issue_text.splitlines():
        stripped = line.strip()
        if any(keyword in stripped.lower() for keyword in _SECTION_KEYWORDS):
            in_section = True
            continue
        if in_section and (stripped.startswith("## ") or stripped.startswith("# ")):
            in_section = False
        if in_section:
            section.append(stripped)
    return section


def extract_target_files_with_invalid(
    issue_text: str,
) -> Tuple[List[str], List[InvalidPath]]:
    """Target Files節から、(有効なパス, 不正なパスと理由) を抽出する.

    節内にバッククォート形式のパスが1つも無い旧形式のIssueは、従来の `.py` 抽出へ
    フォールバックし、警告を出す。不正パスは捨てずに呼び出し側へ返す。
    """
    section = _target_section_lines(issue_text)

    candidates: List[str] = []
    for line in section:
        candidates.extend(match.group(1) for match in _BACKTICK_PATTERN.finditer(line))

    if not candidates:
        legacy = _extract_legacy_python_paths(section)
        if legacy:
            logger.warning(
                "Target Files がバッククォート形式ではないため、legacy の .py 抽出にフォールバックします: %s",
                legacy,
            )
        return legacy, []

    valid: List[str] = []
    invalid: List[InvalidPath] = []
    for raw in candidates:
        reason = validate_target_file_path(raw)
        if reason is not None:
            entry = (normalize_target_path(raw), reason)
            if entry not in invalid:
                invalid.append(entry)
            continue
        normalized = normalize_target_path(raw)
        if normalized not in valid:
            valid.append(normalized)
    return valid, invalid


def _extract_legacy_python_paths(section: List[str]) -> List[str]:
    """旧形式: 節内の本文から `.py` を拾う (バッククォートを使わない既存Issue向け)."""
    found: List[str] = []
    for line in section:
        for match in _LEGACY_PY_PATTERN.findall(line):
            if match not in found:
                found.append(match)
    return found


def extract_target_files_from_issue_text(issue_text: str) -> List[str]:
    """後方互換API: 有効なTarget Filesだけをリストで返す (不正パスは含めない)."""
    valid, _invalid = extract_target_files_with_invalid(issue_text)
    return valid


def require_valid_target_files(issue_text: str) -> List[str]:
    """Target Files節を抽出し、不正パスが1つでもあれば InvalidTargetFilesError を送出する.

    不正パスを黙って捨てると、意図したファイルが対象から落ちて「対象外変更」として
    後段で停止し、原因が分かりにくくなる。そのため編集開始前にまとめて報告する。
    """
    valid, invalid = extract_target_files_with_invalid(issue_text)
    if invalid:
        raise InvalidTargetFilesError(invalid)
    return valid
