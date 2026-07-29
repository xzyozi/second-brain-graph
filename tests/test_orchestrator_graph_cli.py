"""tests/test_orchestrator_graph_cli.py - OrchestratorGraph CLI エントリポイントの単体テスト."""

import json
from unittest.mock import MagicMock, patch

from tools.orchestrator_graph import cmd_execute, cmd_orchestrate, main


def test_cmd_orchestrate_no_cache(capsys, tmp_path, monkeypatch):
    """キャッシュが存在しない場合の cmd_orchestrate 出力テスト."""
    monkeypatch.chdir(tmp_path)
    args = MagicMock()
    cmd_orchestrate(args)

    captured = capsys.readouterr()
    assert "エラー: 優先度キャッシュが存在しません" in captured.out


def test_cmd_orchestrate_with_cache(capsys, tmp_path, monkeypatch):
    """キャッシュが存在する場合の cmd_orchestrate 提示テスト."""
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "tools" / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "priority-cache.json"

    data = {
        "issues": [
            {"id": "EC-012", "title": "決済バグ修正", "score": 95},
            {"id": "EC-013", "title": "ログ追加", "score": 80},
        ]
    }
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    args = MagicMock()
    cmd_orchestrate(args)

    captured = capsys.readouterr()
    assert "1位: [EC-012]「決済バグ修正」（スコア: 95）" in captured.out
    assert "2位: [EC-013]「ログ追加」（スコア: 80）" in captured.out
    assert "uv run python tools/orchestrator_graph.py execute --issue-id EC-012" in captured.out


@patch("tools.orchestrator_graph.build_graph")
@patch("tools.orchestrator_graph.build_initial_state")
def test_cmd_execute(mock_init, mock_build, capsys):
    """cmd_execute の動作検証."""
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {"review_verdict": "LGTM"}
    mock_build.return_value = mock_graph

    mock_init.return_value = {"issue_id": "EC-012"}

    args = MagicMock()
    args.issue_id = "EC-012"

    cmd_execute(args)

    captured = capsys.readouterr()
    assert "Issue EC-012 の実行が完了しました" in captured.out
    mock_graph.invoke.assert_called_once()


@patch("sys.argv", ["orchestrator_graph.py", "orchestrate"])
@patch("tools.orchestrator_graph.cmd_orchestrate")
def test_main_orchestrate(mock_cmd):
    """CLI メインエントリポイント (orchestrate) テスト."""
    main()
    mock_cmd.assert_called_once()


@patch("sys.argv", ["orchestrator_graph.py", "execute", "--issue-id", "EC-012"])
@patch("tools.orchestrator_graph.cmd_execute")
def test_main_execute(mock_cmd):
    """CLI メインエントリポイント (execute) テスト."""
    main()
    mock_cmd.assert_called_once()
