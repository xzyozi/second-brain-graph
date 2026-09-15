"""Rust-specific language verifier supporting cargo check and lexical parsing."""

import re
import subprocess
from pathlib import Path

from tools.lang.base import BaseLanguageVerifier, VerificationResult, register_verifier


@register_verifier("rust")
@register_verifier("rs")
class RustLanguageVerifier(BaseLanguageVerifier):
    """Verifier implementation for Rust language files and Cargo projects."""

    def verify_syntax(self, file_path: Path) -> VerificationResult:
        """Verify Rust syntax using cargo check if in project, or lexical validation."""
        if not file_path.exists():
            return VerificationResult(is_valid=False, errors=[f"File not found: {file_path}"])

        project_dir = self._find_cargo_root(file_path.parent)
        if project_dir:
            return self.check_build(project_dir)

        # Standalone file fallback check (brace balancing and basic token extraction)
        code_text = file_path.read_text(encoding="utf-8")
        errors = self._check_standalone_rust(code_text)
        identifiers = self._extract_identifiers(code_text)

        return VerificationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            identifiers=identifiers,
        )

    def verify_identifiers(self, file_path: Path, required_identifiers: list[str]) -> VerificationResult:
        """Verify presence of required Rust identifiers, types, or functions."""
        syntax_res = self.verify_syntax(file_path)
        if not syntax_res.is_valid:
            return syntax_res

        code_text = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        identifiers = syntax_res.identifiers or self._extract_identifiers(code_text)

        missing = [ident for ident in required_identifiers if ident not in identifiers]
        errors = [f"Missing required Rust identifier: '{ident}'" for ident in missing]

        return VerificationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            identifiers=identifiers,
        )

    def check_build(self, project_dir: Path) -> VerificationResult:
        """Execute cargo check in the target Cargo project directory."""
        cargo_toml = project_dir / "Cargo.toml"
        if not cargo_toml.exists():
            return VerificationResult(is_valid=False, errors=[f"Cargo.toml not found in {project_dir}"])

        res = subprocess.run(
            ["cargo", "check", "--message-format=short"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            return VerificationResult(is_valid=False, errors=[res.stderr or res.stdout])
        return VerificationResult(is_valid=True)

    def _find_cargo_root(self, start_dir: Path) -> Path | None:
        curr = start_dir.resolve()
        for parent in [curr] + list(curr.parents):
            if (parent / "Cargo.toml").exists():
                return parent
        return None

    def _check_standalone_rust(self, code: str) -> list[str]:
        errors = []
        stack = []
        pairs = {"{": "}", "(": ")", "[": "]"}

        for line_idx, line in enumerate(code.splitlines(), start=1):
            for char in line:
                if char in pairs:
                    stack.append((char, line_idx))
                elif char in pairs.values():
                    if not stack:
                        errors.append(f"Unmatched closing brace '{char}' at line {line_idx}")
                        break
                    last_open, _ = stack.pop()
                    if pairs[last_open] != char:
                        errors.append(f"Mismatched brace '{last_open}' and '{char}' at line {line_idx}")
                        break
        if stack:
            unclosed, line_idx = stack[-1]
            errors.append(f"Unclosed brace '{unclosed}' opened at line {line_idx}")
        return errors

    def _extract_identifiers(self, code: str) -> set[str]:
        identifiers = set()
        # Functions: fn function_name
        for match in re.finditer(r"\bfn\s+([a-zA-Z_][a-zA-Z0-9_]*)", code):
            identifiers.add(match.group(1))
        # Structs / Enums / Traits: struct Name, enum Name, trait Name
        for match in re.finditer(r"\b(struct|enum|trait|type)\s+([a-zA-Z_][a-zA-Z0-9_]*)", code):
            identifiers.add(match.group(2))
        # Use statements: use std::sync::Arc
        for match in re.finditer(r"\buse\s+([a-zA-Z0-9_:]+)", code):
            parts = match.group(1).split("::")
            identifiers.update(parts)
        # Identifiers in general token scan
        for match in re.finditer(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", code):
            identifiers.add(match.group(0))
        return identifiers
