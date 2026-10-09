"""Unit tests for tools/doctor.py."""

import json
from pathlib import Path
from unittest.mock import patch

from tools.doctor import (
    CheckResult,
    check_gitignore,
    check_issue_specs,
    check_project_json,
    check_registry,
    check_satellite_dir,
    check_tasks_md,
    check_venv,
    diagnose_project,
    main,
    print_doctor_report,
)


def test_check_registry(tmp_path: Path) -> None:
    """レジストリ登録の検証"""
    project_root = tmp_path
    meta_dir = project_root / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    reg_file = meta_dir / ".project-registry.json"

    reg_data = {
        "projects": {
            "TFG": {
                "name": "test_file_grep",
                "dir": "projects/test_file_grep",
                "meta": "metadata/projects/TFG",
            }
        }
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    # 1. 登録済みキー
    res_ok, pdata = check_registry("TFG", project_root)
    assert res_ok.status == "OK"
    assert pdata is not None

    # 2. 未登録キー
    res_fail, pdata_none = check_registry("UNKNOWN", project_root)
    assert res_fail.status == "FAIL"
    assert pdata_none is None


def test_check_satellite_dir(tmp_path: Path) -> None:
    """サテライトディレクトリと .git の存在チェック"""
    sat_dir = tmp_path / "sat"
    res_no_dir = check_satellite_dir(sat_dir)
    assert res_no_dir.status == "FAIL"

    sat_dir.mkdir(parents=True, exist_ok=True)
    res_no_git = check_satellite_dir(sat_dir)
    assert res_no_git.status == "FAIL"

    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    res_ok = check_satellite_dir(sat_dir)
    assert res_ok.status == "OK"


def test_check_project_json(tmp_path: Path) -> None:
    """サテライト docs/project.json の存在および --fix での自己修復を検証"""
    project_root = tmp_path
    sat_dir = project_root / "projects" / "test_proj"
    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True, exist_ok=True)

    proj_entry = {"name": "test_proj", "dir": "projects/test_proj"}

    # 1. 存在しない場合 (fix=False)
    res_missing = check_project_json(
        "TP", sat_dir, proj_entry, project_root=project_root, fix=False
    )
    assert res_missing.status == "FAIL"
    assert res_missing.fixable is True

    # 2. 存在しない場合 (fix=True): self_heal で自動生成
    def mock_heal(key: str, entry: dict, project_root: Path) -> Path:
        p = sat_docs / "project.json"
        p.write_text('{"key": "TP"}', encoding="utf-8")
        return p

    with patch(
        "tools.doctor.self_heal_satellite_project_json",
        side_effect=mock_heal,
    ):
        res_fixed = check_project_json(
            "TP", sat_dir, proj_entry, project_root=project_root, fix=True
        )
        assert res_fixed.status == "FIXED"

    # 3. 存在し key 一致
    res_ok = check_project_json("TP", sat_dir, proj_entry, project_root=project_root, fix=False)
    assert res_ok.status == "OK"


def test_check_tasks_md(tmp_path: Path) -> None:
    """docs/tasks.md の存在および --fix による作成を検証"""
    sat_dir = tmp_path
    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True, exist_ok=True)

    # 1. 存在しない場合
    res_missing = check_tasks_md(sat_dir, "TP", fix=False)
    assert res_missing.status == "FAIL"
    assert res_missing.fixable is True

    # 2. fix=True で作成
    res_fixed = check_tasks_md(sat_dir, "TP", fix=True)
    assert res_fixed.status == "FIXED"
    assert (sat_docs / "tasks.md").exists()

    # 3. 存在する場合
    (sat_docs / "tasks.md").write_text("- [ ] [TP-0001] タスク1\n", encoding="utf-8")
    res_ok = check_tasks_md(sat_dir, "TP", fix=False)
    assert res_ok.status == "OK"
    assert "1 件" in res_ok.message


def test_check_gitignore(tmp_path: Path) -> None:
    """サテライトの .gitignore 設定チェックおよび --fix を検証"""
    sat_dir = tmp_path
    gitignore = sat_dir / ".gitignore"

    # 1. 空の .gitignore
    gitignore.write_text("# initial\n", encoding="utf-8")
    res_warn = check_gitignore(sat_dir, fix=False)
    assert res_warn.status == "WARN"

    # 2. fix=True で追記
    res_fixed = check_gitignore(sat_dir, fix=True)
    assert res_fixed.status == "FIXED"
    content = gitignore.read_text(encoding="utf-8")
    assert ".venv/" in content
    assert ".aider*" in content

    # 3. 追記後は OK
    res_ok = check_gitignore(sat_dir, fix=False)
    assert res_ok.status == "OK"


def test_check_issue_specs(tmp_path: Path) -> None:
    """未完了タスクに対する仕様書 docs/issues/*.md の存在チェックを検証"""
    sat_dir = tmp_path
    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True, exist_ok=True)
    issues_dir = sat_docs / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)

    tasks_file = sat_docs / "tasks.md"
    tasks_file.write_text(
        "- [ ] [TP-0001] タスク1 <!-- stage:ready -->\n- [ ] [TP-0002] タスク2 <!-- stage:ready -->\n",
        encoding="utf-8",
    )

    # 1. 仕様書がない場合
    res_missing = check_issue_specs(sat_dir, "TP")
    assert res_missing.status == "WARN"
    assert "TP-0001" in res_missing.message

    # 2. 仕様書を作成した場合
    (issues_dir / "TP-0001.md").write_text("# Spec 1", encoding="utf-8")
    (issues_dir / "TP-0002.md").write_text("# Spec 2", encoding="utf-8")
    res_ok = check_issue_specs(sat_dir, "TP")
    assert res_ok.status == "OK"
    assert "2 件" in res_ok.message


def test_print_doctor_report() -> None:
    """レポート表示のステータス判定を検証"""
    ok_results = [
        CheckResult(name="Test1", status="OK", message="OK msg"),
        CheckResult(name="Test2", status="FIXED", message="Fixed msg"),
    ]
    assert print_doctor_report("TP", ok_results) is True

    warn_results = [
        CheckResult(name="Test1", status="OK", message="OK msg"),
        CheckResult(name="Test2", status="WARN", message="Warn msg"),
    ]
    assert print_doctor_report("TP", warn_results) is True

    fail_results = [
        CheckResult(name="Test1", status="FAIL", message="Fail msg"),
    ]
    assert print_doctor_report("TP", fail_results) is False


def test_doctor_main_with_target(tmp_path: Path) -> None:
    """main() でターゲット指定時の動作を検証"""
    project_root = tmp_path
    meta_dir = project_root / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    reg_file = meta_dir / ".project-registry.json"
    reg_data = {
        "projects": {
            "TP": {
                "name": "test_proj",
                "dir": "projects/test_proj",
                "meta": "metadata/projects/TP",
            }
        }
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    sat_dir = project_root / "projects" / "test_proj"
    sat_dir.mkdir(parents=True, exist_ok=True)
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)

    with (
        patch("sys.argv", ["doctor.py", "TP"]),
        patch("tools.doctor.PROJECT_ROOT", project_root),
        patch("tools.doctor.diagnose_project") as mock_diag,
        patch("tools.doctor.print_doctor_report", return_value=True) as mock_report,
    ):
        mock_diag.return_value = [CheckResult(name="Test", status="OK", message="msg")]
        try:
            main()
        except SystemExit:
            pass
        assert mock_diag.called
        assert mock_diag.call_args.args[0] == "TP"
        assert mock_report.called


def test_check_venv(tmp_path: Path) -> None:
    """check_venv の検証"""
    sat_dir = tmp_path
    # 1. .venv なし
    res_no = check_venv(sat_dir, fix=False)
    assert res_no.status == "FAIL"
    assert res_no.fixable is True


def test_diagnose_project_full(tmp_path: Path) -> None:
    """diagnose_project の統合実行を検証"""
    project_root = tmp_path
    meta_dir = project_root / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    reg_file = meta_dir / ".project-registry.json"
    reg_data = {
        "projects": {
            "TP": {
                "name": "test_proj",
                "dir": "projects/test_proj",
                "meta": "metadata/projects/TP",
            }
        }
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    sat_dir = project_root / "projects" / "test_proj"
    sat_dir.mkdir(parents=True, exist_ok=True)
    (sat_dir / ".git").mkdir(parents=True, exist_ok=True)
    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True, exist_ok=True)
    (sat_docs / "project.json").write_text('{"key": "TP"}', encoding="utf-8")
    (sat_docs / "tasks.md").write_text("# Tasks\n", encoding="utf-8")

    # gh コマンドをモック
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        results = diagnose_project("TP", project_root, fix=False)
        assert len(results) >= 5
        names = [r.name for r in results]
        assert "Registry Entry" in names
        assert "Satellite Directory" in names
        assert "Satellite project.json" in names
        assert "Tasks Backlog" in names


def test_check_gitignore_covers_all_generated_artifacts(tmp_path: Path) -> None:
    """.venv/ と .aider* 以外の生成物パターンも警告・追記の対象になる (Issue #98)。"""
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".venv/\n.aider*\n", encoding="utf-8")

    res_warn = check_gitignore(tmp_path, fix=False)
    assert res_warn.status == "WARN"
    assert ".pytest_cache/" in res_warn.message
    assert "__pycache__/" in res_warn.message
    assert ".venv/" not in res_warn.message

    res_fixed = check_gitignore(tmp_path, fix=True)
    assert res_fixed.status == "FIXED"
    content = gitignore.read_text(encoding="utf-8")
    for entry in (".pytest_cache/", "__pycache__/", "*.pyc", ".ruff_cache/", ".mypy_cache/"):
        assert content.splitlines().count(entry) == 1

    assert check_gitignore(tmp_path, fix=False).status == "OK"
