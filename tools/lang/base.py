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
