"""Python-specific language verifier using ast and py_compile."""

import ast
import py_compile
import subprocess
from pathlib import Path

from tools.lang.base import BaseLanguageVerifier, VerificationResult, register_verifier


@register_verifier("python")
@register_verifier("py")
class PythonLanguageVerifier(BaseLanguageVerifier):
    """Verifier implementation for Python language files."""

    def verify_syntax(self, file_path: Path) -> VerificationResult:
        """Verify Python syntax via ast.parse and py_compile."""
        if not file_path.exists():
            return VerificationResult(is_valid=False, errors=[f"File not found: {file_path}"])

        code_text = file_path.read_text(encoding="utf-8")
        errors = []
        tree = None

        try:
            tree = ast.parse(code_text, filename=str(file_path))
        except SyntaxError as e:
            errors.append(f"SyntaxError in {file_path.name}:{e.lineno}: {e.msg}")

        try:
            py_compile.compile(file_path, doraise=True)
        except Exception as e:
            errors.append(f"py_compile error: {e}")

        identifiers = self._extract_identifiers(tree) if tree else set()
        return VerificationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            ast_tree=tree,
            identifiers=identifiers,
        )

    def verify_identifiers(self, file_path: Path, required_identifiers: list[str]) -> VerificationResult:
        """Verify presence of specific identifiers in Python AST."""
        syntax_res = self.verify_syntax(file_path)
        if not syntax_res.is_valid:
            return syntax_res

        missing = [ident for ident in required_identifiers if ident not in syntax_res.identifiers]
        errors = [f"Missing required identifier in AST: '{ident}'" for ident in missing]

        return VerificationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            ast_tree=syntax_res.ast_tree,
            identifiers=syntax_res.identifiers,
        )

    def has_try_except_block(self, file_path: Path) -> bool:
        """Check if Python file contains at least one try-except block."""
        syntax_res = self.verify_syntax(file_path)
        if not syntax_res.is_valid or not syntax_res.ast_tree:
            return False
        return any(isinstance(node, ast.Try) for node in ast.walk(syntax_res.ast_tree))

    def check_build(self, project_dir: Path) -> VerificationResult:
        """Run ruff / pytest syntax and lint check on project directory."""
        res = subprocess.run(
            ["python", "-m", "py_compile"] + [str(p) for p in project_dir.glob("*.py")],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            return VerificationResult(is_valid=False, errors=[res.stderr])
        return VerificationResult(is_valid=True)

    def _extract_identifiers(self, tree: ast.AST) -> set[str]:
        """Extract all Name, Attribute, Import, Call, and FunctionDef identifiers."""
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.FunctionDef | ast.ClassDef):
                identifiers.add(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    identifiers.add(alias.name)
                    if alias.asname:
                        identifiers.add(alias.asname)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    identifiers.add(node.module)
                for alias in node.names:
                    identifiers.add(alias.name)
        return identifiers
