"""Unit tests for tools/doctor.py."""

import json
from pathlib import Path
from unittest.mock import patch

from tools.doctor import (
    CheckResult,
    check_github_issues_access,
    check_gitignore,
    check_legacy_local_files,
    check_project_json,
    check_registry,
    check_satellite_dir,
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

    # 4. allowed_new_file_globs の形式検証 (Issue #102)
    # 正しい形式: 文字列のリスト
    p_json = sat_docs / "project.json"
    p_json.write_text(
        '{"key": "TP", "allowed_new_file_globs": ["tests/**", "src/**"]}', encoding="utf-8"
    )
    res_globs_ok = check_project_json(
        "TP", sat_dir, proj_entry, project_root=project_root, fix=False
    )
    assert res_globs_ok.status == "OK"

    # 不正な形式: 文字列以外が含まれるか、リストでない
    p_json.write_text('{"key": "TP", "allowed_new_file_globs": "invalid_string"}', encoding="utf-8")
    res_globs_invalid = check_project_json(
        "TP", sat_dir, proj_entry, project_root=project_root, fix=False
    )
    assert res_globs_invalid.status == "WARN"
    assert "allowed_new_file_globs は文字列の配列である必要があります" in res_globs_invalid.message


def test_check_legacy_local_files(tmp_path: Path) -> None:
    """レガシーファイル (docs/tasks.md, docs/issues/) が不在なら OK、残存時は非推奨 WARN となることを検証"""
    sat_dir = tmp_path
    sat_docs = sat_dir / "docs"
    sat_docs.mkdir(parents=True, exist_ok=True)

    # 1. 不在の場合 -> OK（エラーにならない）
    res_clean = check_legacy_local_files(sat_dir)
    assert res_clean.status == "OK"
    assert "SSOT" in res_clean.message

    # 2. docs/tasks.md が残存している場合 -> WARN
    tasks_file = sat_docs / "tasks.md"
    tasks_file.write_text("- [ ] [TP-0001] タスク1\n", encoding="utf-8")
    res_tasks_warn = check_legacy_local_files(sat_dir)
    assert res_tasks_warn.status == "WARN"
    assert "docs/tasks.md" in res_tasks_warn.message

    # 3. docs/issues/ も残存している場合 -> 両方 WARN 通知
    issues_dir = sat_docs / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    (issues_dir / "TP-0001.md").write_text("# Spec 1", encoding="utf-8")
    res_both_warn = check_legacy_local_files(sat_dir)
    assert res_both_warn.status == "WARN"
    assert "docs/tasks.md" in res_both_warn.message
    assert "docs/issues/" in res_both_warn.message


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


def test_check_gitignore_missing_file_is_not_reported_as_fixed(tmp_path: Path) -> None:
    """.gitignore が無い衛星では --fix でも FIXED と誤報告しない (Issue #100)。"""
    for fix in (False, True):
        res = check_gitignore(tmp_path, fix=fix)
        assert res.status == "WARN"
        assert res.fixable is False
        assert ".gitignore が存在しません" in res.message

    # 新規作成もしない
    assert not (tmp_path / ".gitignore").exists()


def test_check_github_issues_access() -> None:
    """GitHub CLI / GitHub Issues (SSOT) 疎通チェックを検証"""
    from unittest.mock import MagicMock

    # 1. github_repo 未設定 -> WARN
    res_no_repo = check_github_issues_access(None)
    assert res_no_repo.status == "WARN"

    # 2. gh 未インストール -> WARN
    with patch("shutil.which", return_value=None):
        res_no_gh = check_github_issues_access("owner/repo")
        assert res_no_gh.status == "WARN"

    # 3. gh issue list 成功 -> OK
    with (
        patch("shutil.which", return_value="gh"),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="[]", stderr="")),
    ):
        res_ok = check_github_issues_access("owner/repo")
        assert res_ok.status == "OK"
        assert "owner/repo" in res_ok.message


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

    # gh コマンドをモック（tasks.md や docs/issues が存在しなくてもエラーにならないこと）
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
        assert "Legacy Local Files" in names
        assert "GitHub Issues Access" in names
        assert all(
            r.status != "FAIL"
            for r in results
            if r.name in ("Legacy Local Files", "GitHub Issues Access")
        )


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


def test_doctor_multilang_environment_and_gitignore(tmp_path: Path) -> None:
    """Issue #168: TypeScript および Rust サテライトに対する check_environment と check_gitignore の動作を検証する。"""
    from unittest.mock import MagicMock

    from tools.doctor import check_environment

    # 1. TypeScript サテライト
    ts_dir = tmp_path / "ts_sat"
    ts_dir.mkdir()
    (ts_dir / "package.json").write_text('{"name": "ts-sat"}', encoding="utf-8")

    # node_modules なしの場合: WARN
    with (
        patch(
            "shutil.which", side_effect=lambda cmd: "fake_node" if cmd in ("node", "npm") else None
        ),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="v20.0.0", stderr="")
        res_ts_warn = check_environment(ts_dir, language="typescript", fix=False)
        assert res_ts_warn.status == "WARN"
        assert "node_modules" in res_ts_warn.message

        # --fix で npm install を試行 -> FIXED
        res_ts_fixed = check_environment(ts_dir, language="typescript", fix=True)
        assert res_ts_fixed.status == "FIXED"

        # node_modules が存在する場合 -> OK
        nm_dir = ts_dir / "node_modules"
        nm_dir.mkdir(exist_ok=True)
        (nm_dir / "dummy.txt").write_text("ok", encoding="utf-8")
        res_ts_ok = check_environment(ts_dir, language="typescript", fix=False)
        assert res_ts_ok.status == "OK"

    # TypeScript gitignore
    gi_ts = ts_dir / ".gitignore"
    gi_ts.write_text(".aider*\n", encoding="utf-8")
    res_gi_ts = check_gitignore(ts_dir, language="typescript", fix=True)
    assert res_gi_ts.status == "FIXED"
    assert "node_modules/" in gi_ts.read_text(encoding="utf-8")

    # 2. Rust サテライト
    rust_dir = tmp_path / "rust_sat"
    rust_dir.mkdir()
    (rust_dir / "Cargo.toml").write_text('[package]\nname = "rust-sat"\n', encoding="utf-8")

    with (
        patch("shutil.which", side_effect=lambda cmd: "fake_cargo" if cmd == "cargo" else None),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="cargo 1.75.0", stderr="")
        res_rust_ok = check_environment(rust_dir, language="rust", fix=False)
        assert res_rust_ok.status == "OK"
        assert "Rust 環境 有効" in res_rust_ok.message

    # Rust gitignore
    gi_rust = rust_dir / ".gitignore"
    gi_rust.write_text(".aider*\n", encoding="utf-8")
    res_gi_rust = check_gitignore(rust_dir, language="rust", fix=True)
    assert res_gi_rust.status == "FIXED"
    assert "target/" in gi_rust.read_text(encoding="utf-8")
