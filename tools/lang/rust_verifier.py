"""Rust-specific language verifier supporting cargo check and Tree-sitter AST parsing."""

import subprocess
from pathlib import Path

from tools.lang.base import (
    BaseLanguageVerifier,
    VerificationResult,
    extract_tree_sitter_identifiers,
    find_tree_sitter_errors,
    get_tree_sitter_parser,
    register_verifier,
)

RUST_KEYWORDS = {
    "abstract",
    "as",
    "async",
    "await",
    "become",
    "box",
    "break",
    "const",
    "continue",
    "crate",
    "do",
    "dyn",
    "else",
    "enum",
    "extern",
    "false",
    "final",
    "fn",
    "for",
    "if",
    "impl",
    "in",
    "let",
    "loop",
    "macro",
    "match",
    "mod",
    "move",
    "mut",
    "override",
    "priv",
    "pub",
    "ref",
    "return",
    "self",
    "Self",
    "static",
    "struct",
    "super",
    "trait",
    "true",
    "type",
    "typeof",
    "unsafe",
    "unsized",
    "use",
    "virtual",
    "where",
    "while",
    "yield",
}


@register_verifier("rust")
@register_verifier("rs")
class RustLanguageVerifier(BaseLanguageVerifier):
    """Verifier implementation for Rust language files and Cargo projects using Tree-sitter."""

    def verify_syntax(self, file_path: Path) -> VerificationResult:
        """Verify Rust syntax using cargo check if in project, or Tree-sitter AST validation."""
        if not file_path.exists():
            return VerificationResult(is_valid=False, errors=[f"File not found: {file_path}"])

        project_dir = self._find_cargo_root(file_path.parent)
        if project_dir:
            return self.check_build(project_dir)

        code_text = file_path.read_text(encoding="utf-8")
        code_bytes = code_text.encode("utf-8")
        parser = get_tree_sitter_parser("rust")

        if parser:
            tree = parser.parse(code_bytes)
            errors = find_tree_sitter_errors(tree.root_node)
            identifiers = (
                extract_tree_sitter_identifiers(tree.root_node, code_bytes) - RUST_KEYWORDS
            )
            return VerificationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                ast_tree=tree,
                identifiers=identifiers,
            )

        # Fallback if tree-sitter parser is unavailable
        errors = self._check_standalone_rust(code_text)
        identifiers = self._extract_identifiers_fallback(code_text)
        return VerificationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            identifiers=identifiers,
        )

    def verify_identifiers(
        self, file_path: Path, required_identifiers: list[str]
    ) -> VerificationResult:
        """Verify presence of required Rust identifiers, types, or functions."""
        syntax_res = self.verify_syntax(file_path)
        if not syntax_res.is_valid:
            return syntax_res

        code_text = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        if syntax_res.identifiers is not None and len(syntax_res.identifiers) > 0:
            identifiers = syntax_res.identifiers
        else:
            code_bytes = code_text.encode("utf-8")
            parser = get_tree_sitter_parser("rust")
            if parser:
                tree = parser.parse(code_bytes)
                identifiers = (
                    extract_tree_sitter_identifiers(tree.root_node, code_bytes) - RUST_KEYWORDS
                )
            else:
                identifiers = self._extract_identifiers_fallback(code_text)

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
            return VerificationResult(
                is_valid=False, errors=[f"Cargo.toml not found in {project_dir}"]
            )

        res = subprocess.run(
            ["cargo", "check", "--message-format=short"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            return VerificationResult(is_valid=False, errors=[res.stderr or res.stdout])
        return VerificationResult(is_valid=True)

    def _find_cargo_root(self, start_dir: Path, max_depth: int = 6) -> Path | None:
        curr = start_dir.resolve()
        depth = 0
        while depth < max_depth:
            if (curr / "Cargo.toml").exists():
                return curr
            if curr.parent == curr:
                break
            curr = curr.parent
            depth += 1
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
                        errors.append(
                            f"Mismatched brace '{last_open}' and '{char}' at line {line_idx}"
                        )
                        break
        if stack:
            unclosed, line_idx = stack[-1]
            errors.append(f"Unclosed brace '{unclosed}' opened at line {line_idx}")
        return errors

    def _extract_identifiers_fallback(self, code: str) -> set[str]:
        import re

        identifiers = set()
        for match in re.finditer(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", code):
            identifiers.add(match.group(0))
        return identifiers - RUST_KEYWORDS
