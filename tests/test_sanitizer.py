#!/usr/bin/env python3
"""tests/test_sanitizer.py - 機密情報マスキング・サニタイズモジュールの単体テスト."""

from tools.sanitizer import (
    REDACTED,
    REDACTED_EMAIL,
    REDACTED_PRIVATE_KEY,
    sanitize_data,
    sanitize_text,
)


class TestSanitizeText:
    """sanitize_text の各種シークレットパターン置換テスト."""

    def test_sanitize_empty_and_none(self) -> None:
        assert sanitize_text("") == ""
        assert sanitize_text(None) is None  # type: ignore

    def test_sanitize_private_keys(self) -> None:
        rsa_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA0Y1234567890abcdefghijklmnopqrstuvwxyz\n"
            "-----END RSA PRIVATE KEY-----"
        )
        ec_key = (
            "-----BEGIN EC PRIVATE KEY-----\n"
            "MHcCAQEEIAbcdef1234567890\n"
            "-----END EC PRIVATE KEY-----"
        )
        openssh_key = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAA=\n"
            "-----END OPENSSH PRIVATE KEY-----"
        )
        text = f"Here is my RSA key:\n{rsa_key}\nand EC key:\n{ec_key}\nand SSH:\n{openssh_key}"
        sanitized = sanitize_text(text)
        assert rsa_key not in sanitized
        assert ec_key not in sanitized
        assert openssh_key not in sanitized
        assert sanitized.count(REDACTED_PRIVATE_KEY) == 3

    def test_sanitize_auth_urls(self) -> None:
        urls = [
            "postgresql://db_user:SuperSecretP@ss1@db.internal:5432/mydb",
            "mysql://root:P%40ssw0rd!@127.0.0.1:3306/app",
            "mongodb+srv://admin:my_mongo_pass@cluster0.mongodb.net/test",
            "redis://default:redispw123@redis-cache:6379/0",
            "https://api_user:token12345@api.service.com/v1/resource",
        ]
        for url in urls:
            sanitized = sanitize_text(url)
            assert "[REDACTED]@" in sanitized
            assert "SuperSecretP@ss1" not in sanitized
            assert "P%40ssw0rd!" not in sanitized
            assert "my_mongo_pass" not in sanitized
            assert "redispw123" not in sanitized
            assert "token12345" not in sanitized

    def test_sanitize_specific_api_tokens(self) -> None:
        # GitHub Secret Scanning (Push Protection) 回避のためプレフィックスを動的生成
        gh_pat = "".join(["g", "h", "p", "_", "1234567890" * 4])
        gh_fine_grained = "".join(
            [
                "git",
                "hub",
                "_pat_",
                "11AAAAAAA0123456789012345678901234567890123456789012345678901234567890123456789012",
            ]
        )
        # OpenAI token
        openai_key = "".join(["s", "k", "-", "1234567890abcdef" * 2])
        # Anthropic token
        anthropic_key = "".join(["s", "k", "-", "ant-", "1234567890abcdef" * 2])
        # AWS Access Key
        aws_key = "".join(["AK", "IA", "IOSFODNN7EXAMPLE"])
        # Google API Key
        google_key = "".join(["AI", "za", "SyD-1234567890abcdef1234567890a"])
        # Slack token
        slack_token = "".join(
            ["x", "o", "x", "b", "-", "1234567890-", "1234567890123-", "abcdefghijklmn"]
        )
        # JWT
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )

        sample = (
            f"gh={gh_pat}\n"
            f"pat={gh_fine_grained}\n"
            f"openai={openai_key}\n"
            f"claude={anthropic_key}\n"
            f"aws={aws_key}\n"
            f"google={google_key}\n"
            f"slack={slack_token}\n"
            f"jwt={jwt}\n"
        )
        sanitized = sanitize_text(sample)

        assert gh_pat not in sanitized
        assert gh_fine_grained not in sanitized
        assert openai_key not in sanitized
        assert anthropic_key not in sanitized
        assert aws_key not in sanitized
        assert google_key not in sanitized
        assert slack_token not in sanitized
        assert jwt not in sanitized
        assert sanitized.count(REDACTED) >= 8

    def test_sanitize_bearer_token(self) -> None:
        header = "Authorization: Bearer mySecretTokenString1234567890"
        sanitized = sanitize_text(header)
        assert "Authorization: Bearer [REDACTED]" == sanitized

    def test_sanitize_kv_secrets(self) -> None:
        lines = [
            'password = "my_super_secret_password"',
            "secret: 'another_secret_value'",
            'API_KEY="AI_service_key_99999"',
            "access_token: token_value_abcde",
        ]
        text = "\n".join(lines)
        sanitized = sanitize_text(text)
        assert "my_super_secret_password" not in sanitized
        assert "another_secret_value" not in sanitized
        assert "AI_service_key_99999" not in sanitized
        assert "token_value_abcde" not in sanitized

        assert 'password = "[REDACTED]"' in sanitized
        assert "secret: '[REDACTED]'" in sanitized
        assert 'API_KEY="[REDACTED]"' in sanitized
        assert "access_token: [REDACTED]" in sanitized

    def test_sanitize_emails(self) -> None:
        text = (
            "Contact user at personal.email@gmail.com or admin@company.co.jp.\n"
            "For tests, use test@example.com or user@localhost."
        )
        sanitized = sanitize_text(text)
        # 実在しうる個人メールはマスク
        assert "personal.email@gmail.com" not in sanitized
        assert "admin@company.co.jp" not in sanitized
        assert REDACTED_EMAIL in sanitized

        # テスト用ドメインは除外されて保持
        assert "test@example.com" in sanitized
        assert "user@localhost" in sanitized

    def test_benign_code_not_corrupted(self) -> None:
        """通常の Python コードや変数名が誤検知で壊れないこと."""
        code = (
            "def calculate_tax(price: float, rate: float = 0.1) -> float:\n"
            "    result = price * (1.0 + rate)\n"
            "    logger.info(f'Calculated tax: {result}')\n"
            "    return result\n"
        )
        sanitized = sanitize_text(code)
        assert sanitized == code


class TestSanitizeData:
    """sanitize_data の再帰的構造化データサニタイズテスト."""

    def test_sanitize_dict_and_list_nested(self) -> None:
        raw_data = {
            "issue_id": "EC-001",
            "cwd": "/path/to/project",
            "credentials": {
                "db_url": "postgres://admin:secret123@db:5432/main",
                "api_keys": [
                    "sk-" + "1234567890abcdef1234567890abcdef",
                    "AKIA" + "IOSFODNN7EXAMPLE",
                ],
            },
            "rounds": [
                {"round": 1, "comment": "Contact dev@corporate.org with password='abc'"},
                {"round": 2, "comment": "LGTM with test@example.com"},
            ],
            "count": 42,
            "is_valid": True,
        }

        sanitized = sanitize_data(raw_data)

        # 非文字列型の維持
        assert sanitized["count"] == 42
        assert sanitized["is_valid"] is True
        assert sanitized["issue_id"] == "EC-001"

        # ネストした認証URLのマスク
        assert "secret123" not in sanitized["credentials"]["db_url"]
        assert "[REDACTED]@" in sanitized["credentials"]["db_url"]

        # リスト内トークンのマスク
        assert (
            "sk-" + "1234567890abcdef1234567890abcdef"
            not in sanitized["credentials"]["api_keys"][0]
        )
        assert sanitized["credentials"]["api_keys"][0] == REDACTED
        assert sanitized["credentials"]["api_keys"][1] == REDACTED

        # コメント内メールアドレス・KVシークレットのマスク
        comment1 = sanitized["rounds"][0]["comment"]
        assert "dev@corporate.org" not in comment1
        assert REDACTED_EMAIL in comment1
        assert "password='[REDACTED]'" in comment1

        # テスト用ドメインのメールは保持
        comment2 = sanitized["rounds"][1]["comment"]
        assert "test@example.com" in comment2
