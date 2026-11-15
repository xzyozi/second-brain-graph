"""Issue本文のTarget Files抽出と不正パス検証のテスト (#186)."""

from __future__ import annotations

import pytest

from tools.workspace.target_files import (
    InvalidTargetFilesError,
    extract_target_files_from_issue_text,
    extract_target_files_with_invalid,
    require_valid_target_files,
    validate_target_file_path,
)

SECTION = "## 4. 編集対象ファイル (Target Files)\n"


# ---------------------------------------------------------------------------
# validate_target_file_path: 不正パスの理由を返す (None なら有効)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "docs/README.md",
        "config/models.yaml",
        "pyproject.toml",
        "src/my module/main.py",
        ".github/workflows/ci.yml",
    ],
)
def test_validate_accepts_relative_file_paths(path: str) -> None:
    assert validate_target_file_path(path) is None


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "C:/Windows/system.ini",
        "C:\\Windows\\system.ini",
        "../outside.py",
        "src/../../outside.py",
        "src/*.py",
        "src/**/test_?.py",
        "src/[ab].py",
        "src/",
        "src\\",
        "",
        "   ",
    ],
)
def test_validate_rejects_unsafe_or_ambiguous_paths(path: str) -> None:
    assert validate_target_file_path(path) is not None


# ---------------------------------------------------------------------------
# extract_target_files_with_invalid: バッククォート内の相対パスを抽出する
# ---------------------------------------------------------------------------


def test_extract_takes_backticked_paths_regardless_of_extension() -> None:
    text = SECTION + (
        "- `tools/app.py`（既存編集）\n"
        "- `docs/design/README.md`\n"
        "- `config/models.yaml` (新規作成 / 既存編集)\n"
        "- `pyproject.toml`\n"
    )

    valid, invalid = extract_target_files_with_invalid(text)

    assert valid == [
        "tools/app.py",
        "docs/design/README.md",
        "config/models.yaml",
        "pyproject.toml",
    ]
    assert invalid == []


def test_extract_ignores_prose_mentions_outside_backticks() -> None:
    """説明文に出てくる .py は対象にしない (従来の過剰抽出の解消)."""
    text = SECTION + ("- `src/app.py`\n- 注意: tests/test_other.py は自動生成しないこと\n")

    valid, _ = extract_target_files_with_invalid(text)

    assert valid == ["src/app.py"]


def test_extract_stops_at_next_heading() -> None:
    text = SECTION + "- `src/app.py`\n\n## 5. 除外条件\n- `src/other.py`\n"

    valid, _ = extract_target_files_with_invalid(text)

    assert valid == ["src/app.py"]


def test_extract_normalizes_separators_and_deduplicates() -> None:
    text = SECTION + "- `src\\app.py`\n- `src/app.py`\n- `src/lib.py`\n"

    valid, _ = extract_target_files_with_invalid(text)

    assert valid == ["src/app.py", "src/lib.py"]


def test_extract_keeps_spaces_inside_path_and_trims_edges() -> None:
    text = SECTION + "- ` src/my module/main.py `\n"

    valid, _ = extract_target_files_with_invalid(text)

    assert valid == ["src/my module/main.py"]


def test_extract_reports_invalid_paths_without_dropping_silently() -> None:
    text = SECTION + (
        "- `src/app.py`\n- `../outside.py`\n- `/etc/passwd`\n- `src/*.py`\n- `src/`\n"
    )

    valid, invalid = extract_target_files_with_invalid(text)

    assert valid == ["src/app.py"]
    assert [path for path, _reason in invalid] == [
        "../outside.py",
        "/etc/passwd",
        "src/*.py",
        "src/",
    ]
    assert all(reason for _path, reason in invalid)


def test_extract_falls_back_to_legacy_py_scan_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """バッククォートが無い旧形式は、従来どおり .py を抽出し警告を出す."""
    text = SECTION + "- src/app.py\n- tests/test_app.py\n"

    with caplog.at_level("WARNING"):
        valid, invalid = extract_target_files_with_invalid(text)

    assert valid == ["src/app.py", "tests/test_app.py"]
    assert invalid == []
    assert any("legacy" in record.getMessage().lower() for record in caplog.records)


def test_extract_returns_empty_when_section_is_missing() -> None:
    valid, invalid = extract_target_files_with_invalid("# 見出しのみ\n本文\n")

    assert valid == []
    assert invalid == []


# ---------------------------------------------------------------------------
# 後方互換: extract_target_files_from_issue_text は有効パスのリストを返す
# ---------------------------------------------------------------------------


def test_legacy_extractor_still_returns_valid_list() -> None:
    text = SECTION + "- `src/app.py`\n- `docs/note.md`\n"

    assert extract_target_files_from_issue_text(text) == ["src/app.py", "docs/note.md"]


# ---------------------------------------------------------------------------
# require_valid_target_files: 不正パスがあれば編集開始前に例外で停止する
# ---------------------------------------------------------------------------


def test_require_valid_returns_paths_when_all_valid() -> None:
    text = SECTION + "- `src/app.py`\n- `docs/note.md`\n"

    assert require_valid_target_files(text) == ["src/app.py", "docs/note.md"]


def test_require_valid_raises_when_any_path_is_invalid() -> None:
    """有効なパスが混在していても、不正が1つでもあれば停止する (黙って落とさない)."""
    text = SECTION + "- `src/app.py`\n- `../outside.py`\n"

    with pytest.raises(InvalidTargetFilesError) as caught:
        require_valid_target_files(text)

    assert [path for path, _reason in caught.value.invalid] == ["../outside.py"]


def test_require_valid_does_not_raise_for_legacy_format() -> None:
    """バッククォートの無い旧形式は、不正扱いにせず従来どおり抽出する."""
    text = SECTION + "- src/app.py\n"

    assert require_valid_target_files(text) == ["src/app.py"]


# ---------------------------------------------------------------------------
# InvalidTargetFilesError: 不正パスをまとめて報告する
# ---------------------------------------------------------------------------


def test_invalid_target_files_error_lists_paths_and_reasons() -> None:
    error = InvalidTargetFilesError(
        [("../x.py", "親ディレクトリ参照"), ("src/", "ディレクトリ指定")]
    )

    message = str(error)
    assert "../x.py" in message
    assert "src/" in message
    assert error.invalid == [("../x.py", "親ディレクトリ参照"), ("src/", "ディレクトリ指定")]
