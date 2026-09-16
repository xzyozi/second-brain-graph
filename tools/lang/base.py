"""Base abstraction and data models for language-specific verification tools."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class VerificationResult:
    """Standard container for code verification results."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    ast_tree: Optional[Any] = None
    identifiers: set[str] = field(default_factory=set)


class BaseLanguageVerifier(ABC):
    """Abstract Base Class for language-specific verification and analysis."""

    @abstractmethod
    def verify_syntax(self, file_path: Path) -> VerificationResult:
        """Verify code syntax and return verification result."""
        pass

    @abstractmethod
    def verify_identifiers(self, file_path: Path, required_identifiers: list[str]) -> VerificationResult:
        """Verify presence of specific identifiers, methods, or imports."""
        pass

    @abstractmethod
    def check_build(self, project_dir: Path) -> VerificationResult:
        """Execute project-level build/check command (e.g. cargo check, tsc)."""
        pass


_VERIFIER_REGISTRY: dict[str, type[BaseLanguageVerifier]] = {}


def get_tree_sitter_parser(language: str) -> Optional[Any]:
    """Retrieve Tree-sitter parser for given language using tree_sitter_languages."""
    try:
        from tree_sitter_languages import get_parser
        return get_parser(language)
    except Exception:
        return None


def find_tree_sitter_errors(node: Any) -> list[str]:
    """Recursively collect error messages from Tree-sitter AST nodes."""
    errors = []
    if node.is_missing:
        errors.append(f"Missing syntax element '{node.type}' around line {node.start_point[0] + 1}")
    elif node.type == "ERROR":
        errors.append(f"Syntax error around line {node.start_point[0] + 1}, column {node.start_point[1] + 1}")

    for child in node.children:
        errors.extend(find_tree_sitter_errors(child))
    return errors


def extract_tree_sitter_identifiers(node: Any, code_bytes: bytes) -> set[str]:
    """Recursively extract identifiers and name tokens from Tree-sitter AST nodes."""
    identifiers = set()
    identifier_types = {
        "identifier",
        "type_identifier",
        "field_identifier",
        "property_identifier",
        "scoped_identifier",
        "word",
    }
    if node.type in identifier_types and not node.is_missing:
        text = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        if text and text.isidentifier():
            identifiers.add(text)

    for child in node.children:
        identifiers.update(extract_tree_sitter_identifiers(child, code_bytes))
    return identifiers


def register_verifier(name: str):
    """Decorator to register a language verifier class."""
    def decorator(cls: type[BaseLanguageVerifier]):
        _VERIFIER_REGISTRY[name.lower()] = cls
        return cls
    return decorator


def get_verifier(language: str) -> BaseLanguageVerifier:
    """Factory function to retrieve verifier instance for a given language."""
    lang_key = language.lower()
    if lang_key not in _VERIFIER_REGISTRY:
        raise ValueError(
            f"Unsupported language verifier: '{language}'. "
            f"Registered languages: {list(_VERIFIER_REGISTRY.keys())}"
        )
    return _VERIFIER_REGISTRY[lang_key]()
