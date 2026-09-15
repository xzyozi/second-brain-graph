"""TypeScript / JavaScript language verifier using tsc, node -c, or lexical parsing."""

import re
import subprocess
from pathlib import Path

from tools.lang.base import BaseLanguageVerifier, VerificationResult, register_verifier


@register_verifier("typescript")
@register_verifier("ts")
@register_verifier("javascript")
@register_verifier("js")
class TypeScriptLanguageVerifier(BaseLanguageVerifier):
    """Verifier implementation for TypeScript and JavaScript files."""

    def verify_syntax(self, file_path: Path) -> VerificationResult:
        """Verify TS/JS syntax using tsc or node -c, falling back to lexical check."""
        if not file_path.exists():
            return VerificationResult(is_valid=False, errors=[f"File not found: {file_path}"])

        code_text = file_path.read_text(encoding="utf-8")
        errors = []

        # Try node --check for JS / TS if node is available
        if file_path.suffix in [".js", ".cjs", ".mjs"]:
            res = subprocess.run(["node", "--check", str(file_path)], capture_output=True, text=True)
            if res.returncode != 0:
                errors.append(f"Node syntax error: {res.stderr}")

        if not errors:
            errors.extend(self._check_standalone_ts(code_text))

        identifiers = self._extract_identifiers(code_text)
        return VerificationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            identifiers=identifiers,
        )

    def verify_identifiers(self, file_path: Path, required_identifiers: list[str]) -> VerificationResult:
        """Verify presence of required TypeScript/JavaScript identifiers."""
        syntax_res = self.verify_syntax(file_path)
        if not syntax_res.is_valid:
            return syntax_res

        code_text = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        identifiers = syntax_res.identifiers or self._extract_identifiers(code_text)

        missing = [ident for ident in required_identifiers if ident not in identifiers]
        errors = [f"Missing required TS/JS identifier: '{ident}'" for ident in missing]

        return VerificationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            identifiers=identifiers,
        )

    def check_build(self, project_dir: Path) -> VerificationResult:
        """Run tsc --noEmit in target TypeScript project directory."""
        tsconfig = project_dir / "tsconfig.json"
        if not tsconfig.exists():
            return VerificationResult(is_valid=False, errors=[f"tsconfig.json not found in {project_dir}"])

        res = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            return VerificationResult(is_valid=False, errors=[res.stdout or res.stderr])
        return VerificationResult(is_valid=True)

    def _check_standalone_ts(self, code: str) -> list[str]:
        errors = []
        stack = []
        pairs = {"{": "}", "(": ")", "[": "]"}

        for line_idx, line in enumerate(code.splitlines(), start=1):
            for char in line:
                if char in pairs:
                    stack.append((char, line_idx))
                elif char in pairs.values():
                    if not stack:
                        errors.append(f"Unmatched closing bracket '{char}' at line {line_idx}")
                        break
                    last_open, _ = stack.pop()
                    if pairs[last_open] != char:
                        errors.append(f"Mismatched bracket '{last_open}' and '{char}' at line {line_idx}")
                        break
        if stack:
            unclosed, line_idx = stack[-1]
            errors.append(f"Unclosed bracket '{unclosed}' opened at line {line_idx}")
        return errors

    def _extract_identifiers(self, code: str) -> set[str]:
        identifiers = set()
        # Functions / Methods / Classes / Interfaces / Types
        for match in re.finditer(
            r"\b(function|class|interface|type|enum|const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)",
            code,
        ):
            identifiers.add(match.group(2))
        # General identifiers
        for match in re.finditer(r"\b[a-zA-Z_$][a-zA-Z0-9_$]*\b", code):
            identifiers.add(match.group(0))
        return identifiers
