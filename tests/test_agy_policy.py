"""agy外部送信ポリシーの契約テスト."""

from pathlib import Path

import pytest

from tools.agy_policy import AgyOperation, AgyPolicyDeniedError, authorize_agy_execution
from tools.config_loader import AgyExternalSendConfig


def test_allow_all_mode_preserves_migration_compatibility(tmp_path: Path) -> None:
    """既定のallow_allは、既存routesの移行を止めずに認可できる。"""
    context = authorize_agy_execution(
        project_key=None,
        operation="text",
        cwd=tmp_path,
        policy_config=AgyExternalSendConfig(mode="allow_all"),
    )

    assert context.project_key is None
    assert context.operation == "text"


def test_allowlist_rejects_missing_project_key() -> None:
    """allowlistモードではproject keyなしの外部送信を拒否する。"""
    policy = AgyExternalSendConfig(mode="allowlist", allowed_project_keys=["TFG"])

    with pytest.raises(AgyPolicyDeniedError, match="AGY_POLICY_DENIED"):
        authorize_agy_execution(project_key=None, operation="text", policy_config=policy)


def test_allowlist_rejects_unknown_project_key() -> None:
    """allowlistにないproject keyを拒否する。"""
    policy = AgyExternalSendConfig(mode="allowlist", allowed_project_keys=["TFG"])

    with pytest.raises(AgyPolicyDeniedError, match="not in the external-send allowlist"):
        authorize_agy_execution(project_key="OTHER", operation="text", policy_config=policy)


def test_allowlist_accepts_case_insensitive_project_key() -> None:
    """project keyは既存の大文字prefix運用に合わせて大文字比較する。"""
    policy = AgyExternalSendConfig(mode="allowlist", allowed_project_keys=["TFG"])

    context = authorize_agy_execution(project_key="tfg", operation="text", policy_config=policy)

    assert context.project_key == "TFG"


def test_policy_can_reject_secret_files(tmp_path: Path) -> None:
    """reject_secret_files有効時、秘密情報らしいファイルがあれば拒否する。"""
    (tmp_path / ".env").write_text("FAKE_SECRET=do-not-send\n", encoding="utf-8")
    policy = AgyExternalSendConfig(
        mode="allowlist", allowed_project_keys=["TFG"], reject_secret_files=True
    )

    with pytest.raises(AgyPolicyDeniedError, match="secret-like files"):
        authorize_agy_execution(
            project_key="TFG", operation="edit", cwd=tmp_path, policy_config=policy
        )


def test_allowlist_rejects_project_cwd_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """編集時、cwdから解決したproject keyと指定keyが異なる場合は拒否する。"""
    policy = AgyExternalSendConfig(mode="allowlist", allowed_project_keys=["TFG", "OTHER"])
    monkeypatch.setattr("tools.agy_policy.resolve_project_from_cwd", lambda cwd: "OTHER")

    with pytest.raises(AgyPolicyDeniedError, match="cwd does not match project key"):
        authorize_agy_execution(
            project_key="TFG", operation="edit", cwd=tmp_path, policy_config=policy
        )


def test_allowlist_rejects_unregistered_edit_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """allowlist編集ではproject keyを解決できないcwdも拒否する。"""
    policy = AgyExternalSendConfig(mode="allowlist", allowed_project_keys=["TFG"])
    monkeypatch.setattr("tools.agy_policy.resolve_project_from_cwd", lambda cwd: None)

    with pytest.raises(AgyPolicyDeniedError, match="cwd is not registered"):
        authorize_agy_execution(
            project_key="TFG", operation="edit", cwd=tmp_path, policy_config=policy
        )


def test_allowlist_permits_authorized_project_key_for_all_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """allowlistに登録されたproject keyは text / edit / review の全操作で認可される。"""
    policy = AgyExternalSendConfig(
        mode="allowlist", allowed_project_keys=["PROJECT_A"], reject_secret_files=True
    )
    monkeypatch.setattr("tools.agy_policy.resolve_project_from_cwd", lambda cwd: "PROJECT_A")

    operations: list[AgyOperation] = ["text", "edit", "review"]
    for op in operations:
        ctx = authorize_agy_execution(
            project_key="project_a",
            operation=op,
            cwd=tmp_path,
            policy_config=policy,
        )
        assert ctx.project_key == "PROJECT_A"
        assert ctx.operation == op


@pytest.mark.parametrize(
    "secret_filename",
    [
        ".env",
        ".env.production",
        ".env.local",
        "cert.pem",
        "private.key",
        "token.json",
    ],
)
def test_policy_rejects_various_secret_file_patterns(tmp_path: Path, secret_filename: str) -> None:
    """reject_secret_files有効時、各種秘密情報ファイルが存在すれば拒否する。"""
    (tmp_path / secret_filename).write_text("secret_value", encoding="utf-8")
    policy = AgyExternalSendConfig(
        mode="allowlist", allowed_project_keys=["TFG"], reject_secret_files=True
    )

    with pytest.raises(AgyPolicyDeniedError, match="secret-like files exist"):
        authorize_agy_execution(
            project_key="TFG", operation="text", cwd=tmp_path, policy_config=policy
        )
