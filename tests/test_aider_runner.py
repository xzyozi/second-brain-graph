"""Unit tests for tools.aider_runner."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from tools.aider_runner import AiderRunError, get_git_diff, run_aider
from tools.config_loader import ProfileConfig


@patch("subprocess.run")
def test_get_git_diff_success(mock_run):
    mock_res = MagicMock()
    mock_res.stdout = "diff --git a/file.txt b/file.txt"
    mock_res.returncode = 0
    mock_run.return_value = mock_res

    diff = get_git_diff(cwd=".")
    assert "diff --git" in diff
    mock_run.assert_called_once_with(
        ["git", "diff", "HEAD"],
        cwd=".",
        capture_output=True,
        text=True,
        check=True,
    )


@patch("subprocess.run")
def test_get_git_diff_failure(mock_run):
    mock_run.side_effect = Exception("Git not found")
    diff = get_git_diff(cwd=".")
    assert diff == ""


@patch("tools.aider_runner.get_coordinator")
@patch("tools.aider_runner.load_model_config")
@patch("subprocess.run")
def test_run_aider_success(mock_run, mock_load_config, mock_get_coordinator):
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_run.return_value = mock_res

    mock_cfg = MagicMock()
    mock_cfg.aider.no_auto_commits = True
    mock_load_config.return_value = mock_cfg

    def dummy_execute(intent, request):
        profile = ProfileConfig(
            backend="ollama",
            model="ollama/qwen2.5-coder:14b",
            openai_endpoint="http://localhost:11434/v1",
            ollama_management_endpoint="http://localhost:11434",
        )
        return request["action"](profile)

    coordinator = MagicMock()
    coordinator.execute.side_effect = dummy_execute
    mock_get_coordinator.return_value = coordinator

    result = run_aider("fix bug in main.py", ["main.py"], cwd="/tmp/project")
    assert result is True

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == [
        "aider",
        "--model",
        "ollama/qwen2.5-coder:14b",
        "--yes-always",
        "--no-auto-commits",
        "--message",
        "fix bug in main.py",
        "main.py",
    ]
    assert mock_run.call_args[1]["cwd"] == "/tmp/project"
    assert mock_run.call_args[1]["timeout"] == 600


@patch("tools.aider_runner.get_coordinator")
@patch("tools.aider_runner.load_model_config")
@patch("subprocess.run")
def test_run_aider_custom_model_and_timeout(mock_run, mock_load_config, mock_get_coordinator):
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_run.return_value = mock_res

    mock_cfg = MagicMock()
    mock_cfg.aider.no_auto_commits = False
    mock_load_config.return_value = mock_cfg

    def dummy_execute(intent, request):
        profile = ProfileConfig(
            backend="ollama",
            model="default-model",
            openai_endpoint="http://localhost:11434/v1",
            ollama_management_endpoint="http://localhost:11434",
        )
        return request["action"](profile)

    coordinator = MagicMock()
    coordinator.execute.side_effect = dummy_execute
    mock_get_coordinator.return_value = coordinator

    result = run_aider("add tests", ["test.py"], model="custom-model", timeout=120)
    assert result is True

    cmd = mock_run.call_args[0][0]
    assert cmd == [
        "aider",
        "--model",
        "ollama/custom-model",
        "--yes-always",
        "--message",
        "add tests",
        "test.py",
    ]
    assert mock_run.call_args[1]["timeout"] == 120


@patch("tools.aider_runner.get_coordinator")
@patch("tools.aider_runner.load_model_config")
@patch("subprocess.run")
def test_run_aider_timeout_raises_error(mock_run, mock_load_config, mock_get_coordinator):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["aider"], timeout=300)

    mock_cfg = MagicMock()
    mock_cfg.aider.no_auto_commits = True
    mock_load_config.return_value = mock_cfg

    def dummy_execute(intent, request):
        profile = ProfileConfig(
            backend="ollama",
            model="ollama/qwen2.5-coder:14b",
            openai_endpoint="http://localhost:11434/v1",
            ollama_management_endpoint="http://localhost:11434",
        )
        return request["action"](profile)

    coordinator = MagicMock()
    coordinator.execute.side_effect = dummy_execute
    mock_get_coordinator.return_value = coordinator

    with pytest.raises(AiderRunError) as exc_info:
        run_aider("long task", ["bigfile.py"], timeout=300)

    assert "Aider実行がタイムアウトしました (timeout=300)" in str(exc_info.value)


@patch("tools.aider_runner.get_coordinator")
@patch("tools.aider_runner.load_model_config")
@patch("subprocess.run")
def test_run_aider_file_not_found(mock_run, mock_load_config, mock_get_coordinator):
    mock_run.side_effect = FileNotFoundError()

    mock_cfg = MagicMock()
    mock_cfg.aider.no_auto_commits = True
    mock_load_config.return_value = mock_cfg

    def dummy_execute(intent, request):
        profile = ProfileConfig(
            backend="ollama",
            model="ollama/qwen2.5-coder:14b",
            openai_endpoint="http://localhost:11434/v1",
            ollama_management_endpoint="http://localhost:11434",
        )
        return request["action"](profile)

    coordinator = MagicMock()
    coordinator.execute.side_effect = dummy_execute
    mock_get_coordinator.return_value = coordinator

    result = run_aider("fix bug", ["main.py"])
    assert result is False
