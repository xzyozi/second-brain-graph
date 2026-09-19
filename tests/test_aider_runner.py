"""
Unit tests for tools/aider_runner.py
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tools.aider_runner import (
    AiderRunError,
    GitDiffError,
    get_git_diff,
    get_max_target_file_lines,
    resolve_effective_edit_format,
    revert_working_tree_files,
    run_aider,
)
from tools.config_loader import BackendExecutionConfig


def test_get_git_diff_success() -> None:
    """git diff コマンドが成功した際、標準出力の文字列が返されることを検証する。"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "diff --git a/file.txt b/file.txt\n+new line"
        diff = get_git_diff(cwd=".")
        assert "diff --git" in diff


def test_get_git_diff_failure() -> None:
    """git diff コマンド失敗時に GitDiffError が送出されることを検証する (fail-closed)."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "git error"
        with pytest.raises(GitDiffError):
            get_git_diff(cwd=".")


@patch("subprocess.run")
def test_run_aider_success(mock_run: MagicMock) -> None:
    """run_aider が成功時に True を返すことを検証する。"""
    mock_run.return_value.returncode = 0
    res = run_aider("Fix bug", ["test.py"])
    assert res is True
    assert mock_run.called


@patch("subprocess.run")
def test_run_aider_custom_model_and_timeout(mock_run: MagicMock) -> None:
    """run_aider にカスタムモデルとタイムアウトが渡されることを検証する。"""
    mock_run.return_value.returncode = 0
    res = run_aider("Fix bug", ["test.py"], model="ollama/custom-model", timeout=600)
    assert res is True
    cmd = mock_run.call_args[0][0]
    assert "--model" in cmd
    assert "ollama/custom-model" in cmd


@patch("subprocess.run")
def test_run_aider_timeout_raises_error(mock_run: MagicMock) -> None:
    """Aider 実行タイムアウト時に AiderRunError が発生することを検証する。"""
    import subprocess

    mock_run.side_effect = subprocess.TimeoutExpired(cmd="aider", timeout=300)
    with pytest.raises(AiderRunError, match="timed out"):
        run_aider("Fix bug", ["test.py"])


@patch("subprocess.run")
def test_run_aider_allows_nonexistent_files(mock_run: MagicMock, tmp_path: Path) -> None:
    """指定されたターゲットファイルが存在しない場合でも FileNotFoundError を投げず新規ファイル作成を許可することを検証する。"""
    mock_run.return_value.returncode = 0
    res = run_aider("Create new file", ["new_script.py"], cwd=str(tmp_path))
    assert res is True
    assert mock_run.called


def test_get_default_aider_model() -> None:
    """config/models.json からモデル名を正常取得できることを検証する。"""
    from tools.aider_runner import get_default_aider_model

    model = get_default_aider_model()
    assert isinstance(model, str)
    assert len(model) > 0


@patch("subprocess.run")
def test_run_aider_sanitizes_ollama_api_base_v1_suffix(
    mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OLLAMA_API_BASE に /v1 サフィックスが含まれる場合、自動的に除去されることを検証する。"""
    mock_run.return_value.returncode = 0
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434/v1")

    run_aider("Fix bug", ["test.py"])

    assert mock_run.called
    env_passed = mock_run.call_args[1]["env"]
    assert env_passed["OLLAMA_API_BASE"] == "http://localhost:11434"


def test_get_git_diff_bad_revision_fallback() -> None:
    """HEAD コミットがない新規リポジトリで git diff HEAD が失敗した際、git diff --cached と git diff へフォールバックすることを検証する。"""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=128, stderr="fatal: bad revision 'HEAD'"),
            MagicMock(returncode=0, stdout="diff --git a/staged.py b/staged.py"),
            MagicMock(returncode=0, stdout="diff --git a/unstaged.py b/unstaged.py"),
        ]
        diff = get_git_diff(cwd=".")
        assert "a/staged.py" in diff
        assert "a/unstaged.py" in diff
        assert mock_run.call_count == 4


@patch("subprocess.run")
def test_run_aider_nonzero_exit_raises_error(mock_run: MagicMock) -> None:
    """Aider が非ゼロ終了コードを返した場合に AiderRunError が発生することを検証する。"""
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Aider process error"
    with pytest.raises(AiderRunError, match="returncode 1"):
        run_aider("Fix bug", ["test.py"])


@patch("subprocess.run")
def test_run_aider_includes_edit_format(mock_run: MagicMock) -> None:
    """run_aider に edit_format パラメータまたは config 設定が指定された場合、--edit-format が CLI に渡されることを検証する。"""
    mock_run.return_value.returncode = 0
    run_aider("Fix bug", ["test.py"], edit_format="diff")
    cmd = mock_run.call_args[0][0]
    assert "--edit-format" in cmd
    assert "diff" in cmd


@patch("subprocess.run")
def test_run_aider_tmp_file_cleaned_up_on_error(mock_run: MagicMock, tmp_path: Path) -> None:
    """Aider 実行が失敗（例外発生）した場合でも、指示文の一時ファイルがクリーンアップされることを検証する。"""
    mock_run.side_effect = RuntimeError("Subprocess crash")
    with pytest.raises(AiderRunError, match="Failed to run Aider CLI"):
        run_aider("Fix bug", ["test.py"], cwd=str(tmp_path))

    # 一時ファイル (.aider.instruction_*.tmp) が削除されていることを確認
    tmp_files = list(tmp_path.glob(".aider.instruction_*.tmp"))
    assert len(tmp_files) == 0


# ---------------------------------------------------------------------------
# get_default_aider_model の ollama/ プレフィックス付与ロジック
# ---------------------------------------------------------------------------
def _backend_config_with_coding_model(backend: str, model: str) -> BackendExecutionConfig:
    """code_edit ルートに指定 backend/model を持つ設定を組み立てるヘルパー。"""
    from tools.config_loader import BackendExecutionConfig, ProfileConfig

    if backend == "ollama":
        profile = ProfileConfig(
            backend="ollama",
            model=model,
            openai_endpoint="http://localhost:11434/v1",
            ollama_management_endpoint="http://localhost:11434",
        )
    else:
        profile = ProfileConfig(
            backend="llama_server",
            model=model,
            openai_endpoint="http://localhost:8080/v1",
            port=8080,
            model_path="./models/test.gguf",
        )
    return BackendExecutionConfig(
        mode="exclusive",
        fallback="disabled",
        routes={"code_edit": "coding"},
        profiles={"coding": profile},
    )


def test_get_default_aider_model_adds_ollama_prefix() -> None:
    """ollama バックエンドでモデル名に接頭辞が無い場合、ollama/ が付与されることを確認する。"""
    from tools.aider_runner import get_default_aider_model

    with patch(
        "tools.config_loader.get_backend_execution_config",
        return_value=_backend_config_with_coding_model("ollama", "qwen2.5-coder:7b"),
    ):
        model = get_default_aider_model()

    assert model == "ollama/qwen2.5-coder:7b"


def test_get_default_aider_model_does_not_double_prefix() -> None:
    """既に ollama/ 接頭辞を持つモデル名には二重付与しないことを確認する。"""
    from tools.aider_runner import get_default_aider_model

    with patch(
        "tools.config_loader.get_backend_execution_config",
        return_value=_backend_config_with_coding_model("ollama", "ollama/qwen2.5-coder:7b"),
    ):
        model = get_default_aider_model()

    assert model == "ollama/qwen2.5-coder:7b"


def test_get_default_aider_model_llama_server_no_prefix() -> None:
    """llama_server バックエンドでは ollama/ を付与しないことを確認する。"""
    from tools.aider_runner import get_default_aider_model

    with patch(
        "tools.config_loader.get_backend_execution_config",
        return_value=_backend_config_with_coding_model("llama_server", "gemma-4-12B"),
    ):
        model = get_default_aider_model()

    assert model == "gemma-4-12B"


def test_get_default_aider_model_falls_back_on_config_error() -> None:
    """設定取得が例外を投げた場合、フォールバックモデル名を返すことを確認する (fail-safe)。"""
    from tools.aider_runner import get_default_aider_model

    with patch(
        "tools.config_loader.get_backend_execution_config",
        side_effect=RuntimeError("config broken"),
    ):
        model = get_default_aider_model()

    assert model == "ollama/qwen2.5-coder:7b-instruct"


# ---------------------------------------------------------------------------
# ハイブリッド編集モード & フォールバックのテスト
# ---------------------------------------------------------------------------
def test_get_max_target_file_lines(tmp_path: Path) -> None:
    """実在ファイル群の最大行数が正しく取得されること、未存在ファイルが0行として扱われることを検証する。"""
    f1 = tmp_path / "f1.py"
    f1.write_text("a\nb\nc\n", encoding="utf-8")  # 3 lines

    f2 = tmp_path / "f2.py"
    f2.write_text("1\n2\n3\n4\n5\n", encoding="utf-8")  # 5 lines

    # f2 が最大 (5行)
    assert get_max_target_file_lines(str(tmp_path), ["f1.py", "f2.py", "nonexistent.py"]) == 5
    # 未存在ファイルのみの場合は 0行
    assert get_max_target_file_lines(str(tmp_path), ["nonexistent.py"]) == 0


def test_resolve_effective_edit_format() -> None:
    """hybrid モード時の行数閾値判定および明示指定時の挙動を検証する。"""
    # hybrid モード: 閾値(100)未満は whole
    assert resolve_effective_edit_format("hybrid", max_lines=50, threshold=100) == "whole"
    assert resolve_effective_edit_format("hybrid", max_lines=99, threshold=100) == "whole"
    # hybrid モード: 閾値(100)以上は diff
    assert resolve_effective_edit_format("hybrid", max_lines=100, threshold=100) == "diff"
    assert resolve_effective_edit_format("hybrid", max_lines=250, threshold=100) == "diff"

    # 明示指定時: 行数に関わらずそのまま返る
    assert resolve_effective_edit_format("whole", max_lines=500, threshold=100) == "whole"
    assert resolve_effective_edit_format("diff", max_lines=10, threshold=100) == "diff"
    assert resolve_effective_edit_format("udiff", max_lines=10, threshold=100) == "udiff"


@patch("subprocess.run")
def test_revert_working_tree_files(mock_run: MagicMock) -> None:
    """revert_working_tree_files が git checkout -- target_files を呼び出すことを検証する。"""
    mock_run.return_value.returncode = 0
    revert_working_tree_files(".", ["foo.py", "bar.py"])
    assert mock_run.called
    first_call_args = mock_run.call_args_list[0][0][0]
    assert first_call_args == ["git", "checkout", "--", "foo.py", "bar.py"]


@patch("subprocess.run")
def test_run_aider_hybrid_selects_whole_for_small_file(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """行数が閾値未満のファイルに対して hybrid モードで whole が選択されることを検証する。"""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    small_file = tmp_path / "small.py"
    small_file.write_text("\n".join([f"line_{i}" for i in range(50)]), encoding="utf-8")

    res = run_aider(
        "Edit small file",
        ["small.py"],
        cwd=str(tmp_path),
        edit_format="hybrid",
        hybrid_line_threshold=100,
    )
    assert res is True
    aider_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][0] == "aider"]
    assert len(aider_calls) == 1
    cmd = aider_calls[0]
    idx = cmd.index("--edit-format")
    assert cmd[idx + 1] == "whole"


@patch("subprocess.run")
def test_run_aider_hybrid_selects_diff_for_large_file(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """行数が閾値以上のファイルに対して hybrid モードで diff が選択されることを検証する。"""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    large_file = tmp_path / "large.py"
    large_file.write_text("\n".join([f"line_{i}" for i in range(150)]), encoding="utf-8")

    res = run_aider(
        "Edit large file",
        ["large.py"],
        cwd=str(tmp_path),
        edit_format="hybrid",
        hybrid_line_threshold=100,
    )
    assert res is True
    aider_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][0] == "aider"]
    assert len(aider_calls) == 1
    cmd = aider_calls[0]
    idx = cmd.index("--edit-format")
    assert cmd[idx + 1] == "diff"


@patch("tools.aider_runner.revert_working_tree_files")
@patch("subprocess.run")
def test_run_aider_diff_falls_back_to_whole_on_failure(
    mock_run: MagicMock, mock_revert: MagicMock, tmp_path: Path
) -> None:
    """diff 実行失敗時に revert が実行され whole モードでフォールバック再試行されることを検証する。"""
    large_file = tmp_path / "large.py"
    large_file.write_text("\n".join([f"line_{i}" for i in range(150)]), encoding="utf-8")

    def side_effect(cmd: Any, *args: Any, **kwargs: Any) -> MagicMock:
        if cmd[0] == "aider":
            if "--edit-format" in cmd:
                idx = cmd.index("--edit-format")
                fmt = cmd[idx + 1]
                if fmt == "diff":
                    return MagicMock(returncode=1, stderr="diff failed to match context")
                elif fmt == "whole":
                    return MagicMock(returncode=0, stdout="Success", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = side_effect

    res = run_aider(
        "Edit file",
        ["large.py"],
        cwd=str(tmp_path),
        edit_format="diff",
        fallback_to_whole=True,
    )
    assert res is True

    aider_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][0] == "aider"]
    assert len(aider_calls) == 2

    # 1回目の呼び出しは diff
    idx1 = aider_calls[0].index("--edit-format")
    assert aider_calls[0][idx1 + 1] == "diff"

    # revert が呼ばれていること
    mock_revert.assert_called_once_with(str(tmp_path), ["large.py"])

    # 2回目の呼び出しは whole
    idx2 = aider_calls[1].index("--edit-format")
    assert aider_calls[1][idx2 + 1] == "whole"


@patch("subprocess.run")
def test_run_aider_diff_does_not_fallback_when_disabled(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """fallback_to_whole=False の場合、diff 失敗時に再試行せず即座に例外を送出することを検証する。"""
    def side_effect(cmd: Any, *args: Any, **kwargs: Any) -> MagicMock:
        if cmd[0] == "aider":
            return MagicMock(returncode=1, stderr="diff failed")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = side_effect

    with pytest.raises(AiderRunError, match="returncode 1"):
        run_aider(
            "Edit file",
            ["large.py"],
            cwd=str(tmp_path),
            edit_format="diff",
            fallback_to_whole=False,
        )

    aider_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][0] == "aider"]
    assert len(aider_calls) == 1


@patch("tools.aider_runner.revert_working_tree_files")
@patch("subprocess.run")
def test_run_aider_diff_and_fallback_whole_both_fail(
    mock_run: MagicMock, mock_revert: MagicMock, tmp_path: Path
) -> None:
    """diff と フォールバック whole の両方が失敗した場合、例外が送出されることを検証する。"""
    def side_effect(cmd: Any, *args: Any, **kwargs: Any) -> MagicMock:
        if cmd[0] == "aider":
            return MagicMock(returncode=1, stderr="diff failed")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = side_effect

    with pytest.raises(AiderRunError, match="returncode 1"):
        run_aider(
            "Edit file",
            ["large.py"],
            cwd=str(tmp_path),
            edit_format="diff",
            fallback_to_whole=True,
        )

    aider_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][0] == "aider"]
    assert len(aider_calls) == 2
    mock_revert.assert_called_once()

