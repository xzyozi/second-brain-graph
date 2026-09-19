#!/usr/bin/env python3
"""tools/sanitizer.py - 機密情報マスキング・サニタイズ共通モジュール (DD-003 §10.3, Issue #20)

LLM 送信プロンプト、Git diff、テスト実行ログ、実行履歴 (execution_history.json)、
および Failure Report 等に含まれる可能性のある機密情報（APIキー、トークン、パスワード、
認証URL、秘密鍵、個人メールアドレス等）を検知し、安全に [REDACTED] へ置換します。
"""

import re
from typing import Any, List, Set, Tuple

# 置換マーカー定数
REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"
REDACTED_PRIVATE_KEY = "[REDACTED_PRIVATE_KEY]"

# RFC 2606 準拠のテスト・プレースホルダー用ドメイン（マスキング除外対象）
EXCLUDED_EMAIL_DOMAINS: Set[str] = {
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "localhost",
    "local",
}

# 1. 秘密鍵 (RSA, EC, DSA, OPENSSH, PKCS8 等)
PATTERN_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----[\s\S]+?-----END (?:[A-Z0-9_-]+ )?PRIVATE KEY-----",
    re.MULTILINE,
)

# 2. 認証URL / 接続文字列 (Basic Auth 等)
# 例: postgresql://user:password123@localhost:5432/db -> postgresql://user:[REDACTED]@localhost:5432/db
PATTERN_AUTH_URL = re.compile(
    r"((?:https?|ftp|postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+):([^\s/@]+)@",
    re.IGNORECASE,
)

# 3. 代表的なクラウド・サービス固有の APIキー / アクセストークン
PATTERNS_SPECIFIC_TOKENS: List[Tuple[re.Pattern, str]] = [
    # GitHub (Personal Access Token, OAuth, App Token 等)
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82,}\b"), REDACTED),
    # OpenAI / Anthropic
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), REDACTED),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"), REDACTED),
    # AWS Access Key ID
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED),
    # Google API Key
    (re.compile(r"\bAIza[0-9A-Za-z-_]{30,}\b"), REDACTED),
    # Slack Token (Bot, User, App)
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"), REDACTED),
    # JWT Token (header.payload.signature)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), REDACTED),
]

# 4. Bearer トークン
PATTERN_BEARER = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9_\-\.]{15,})\b")

# 5. 一般的な Key-Value 形式の機密データ
# 例: password = "secret", api_key: 'abcdef12345', SECRET_KEY = xyz
# キー名、セパレータ、前後の空白を group(1) でそのまま保持し、クォートを group(2) で保持
PATTERN_KV_SECRET = re.compile(
    r"(?i)\b((?:password|passwd|pwd|secret|api_?key|auth_?token|access_?token|private_?key)\s*[:=]\s*)([\"']?)([^\s\"'<>,;&]+)\2",
)

# 6. メールアドレス
PATTERN_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def sanitize_text(text: str) -> str:
    """文字列内の機密情報（トークン、パスワード、秘密鍵、メール等）を検知しマスク置換する。

    Args:
        text: 処理対象のプレーンテキストまたはコード・ログ文字列

    Returns:
        サニタイズ（マスキング）処理済みの文字列
    """
    if not text:
        return text

    # 1. 秘密鍵
    text = PATTERN_PRIVATE_KEY.sub(REDACTED_PRIVATE_KEY, text)

    # 2. 認証URL (ユーザー名は残しパスワード部のみ置換)
    text = PATTERN_AUTH_URL.sub(r"\1:" + REDACTED + "@", text)

    # 3. 固有サービス API キー・トークン
    for pattern, replacement in PATTERNS_SPECIFIC_TOKENS:
        text = pattern.sub(replacement, text)

    # 4. Bearer 認証ヘッダー
    text = PATTERN_BEARER.sub(f"Bearer {REDACTED}", text)

    # 5. Key-Value 機密値 (キー名、セパレータ、クォートは保持し、値のみ置換)
    def _kv_replacer(match: re.Match) -> str:
        prefix = match.group(1)
        quote = match.group(2)
        return f"{prefix}{quote}{REDACTED}{quote}"

    text = PATTERN_KV_SECRET.sub(_kv_replacer, text)

    # 6. メールアドレス (RFC 2606 のテスト用ドメインは除外)
    def _email_replacer(match: re.Match) -> str:
        domain = match.group(2).lower()
        if domain in EXCLUDED_EMAIL_DOMAINS:
            return match.group(0)
        return REDACTED_EMAIL

    text = PATTERN_EMAIL.sub(_email_replacer, text)

    return text


def sanitize_data(data: Any) -> Any:
    """辞書やリストなどの構造化データを再帰的に走査し、全文字列フィールドをサニタイズする。

    Args:
        data: 辞書、リスト、文字列等の任意のデータ構造

    Returns:
        サニタイズされた同一構造のデータ
    """
    if isinstance(data, str):
        return sanitize_text(data)
    elif isinstance(data, dict):
        return {k: sanitize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(sanitize_data(item) for item in data)
    elif isinstance(data, set):
        return {sanitize_data(item) for item in data}
    return data
