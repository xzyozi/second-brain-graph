"""TypeScript / JavaScript language verifier using Tree-sitter and tsc / node -c."""

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

TS_KEYWORDS = {
    "abstract", "any", "as", "asserts", "async", "await", "bigint", "boolean", "break",
    "case", "catch", "class", "const", "continue", "debugger", "declare", "default",
    "delete", "do", "else", "enum", "export", "extends", "false", "finally", "for",
    "from", "function", "get", "if", "implements", "import", "in", "instanceof",
    "interface", "is", "keyof", "let", "module", "namespace", "never", "new", "null",
    "number", "object", "package", "private", "protected", "public", "readonly", "require",
    "return", "set", "static", "string", "super", "switch", "symbol", "this", "throw",
    "true", "try", "type", "typeof", "undefined", "unknown", "var", "void", "while",
    "with", "yield",
}


@register_verifier("typescript")
@register_verifier("ts")
@register_verifier("javascript")
@register_verifier("js")
class TypeScriptLanguageVerifier(BaseLanguageVerifier):
    """Verifier implementation for TypeScript and JavaScript files using Tree-sitter."""

    def verify_syntax(self, file_path: Path) -> VerificationResult:
        """Verify TS/JS syntax using Tree-sitter AST validation or node --check for JS files."""
        if not file_path.exists():
            return VerificationResult(is_valid=False, errors=[f"File not found: {file_path}"])

        code_text = file_path.read_text(encoding="utf-8")
        code_bytes = code_text.encode("utf-8")
        errors = []

        # For JavaScript files, optionally run node --check if available
        if file_path.suffix in [".js", ".cjs", ".mjs"]:
            res = subprocess.run(["node", "--check", str(file_path)], capture_output=True, text=True)
            if res.returncode != 0:
                errors.append(f"Node syntax error: {res.stderr}")

        lang = "typescript" if file_path.suffix in [".ts", ".tsx"] else "javascript"
        parser = get_tree_sitter_parser(lang)

        if parser:
            tree = parser.parse(code_bytes)
            ts_errors = find_tree_sitter_errors(tree.root_node)
            errors.extend(ts_errors)
            identifiers = extract_tree_sitter_identifiers(tree.root_node, code_bytes) - TS_KEYWORDS
            return VerificationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                ast_tree=tree,
                identifiers=identifiers,
            )

        # Fallback if tree-sitter parser is unavailable
        if not errors:
            errors.extend(self._check_standalone_ts(code_text))
        identifiers = self._extract_identifiers_fallback(code_text)
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
        if syntax_res.identifiers is not None and len(syntax_res.identifiers) > 0:
            identifiers = syntax_res.identifiers
        else:
            code_bytes = code_text.encode("utf-8")
            lang = "typescript" if file_path.suffix in [".ts", ".tsx"] else "javascript"
            parser = get_tree_sitter_parser(lang)
            if parser:
                tree = parser.parse(code_bytes)
                identifiers = extract_tree_sitter_identifiers(tree.root_node, code_bytes) - TS_KEYWORDS
            else:
                identifiers = self._extract_identifiers_fallback(code_text)

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

    def _extract_identifiers_fallback(self, code: str) -> set[str]:
        import re
        identifiers = set()
        for match in re.finditer(r"\b[a-zA-Z_$][a-zA-Z0-9_$]*\b", code):
            identifiers.add(match.group(0))
        return identifiers - TS_KEYWORDS


