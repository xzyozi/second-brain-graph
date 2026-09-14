"""Language-agnostic target file discovery for the coding workflow."""

import re
from pathlib import Path
from typing import Iterable, List

FILE_PATH_PATTERN = re.compile(r"(?<![\w./-])(?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9][\w.-]*")
IGNORED_DIRECTORIES = frozenset(
    {".aider", ".git", ".pytest_cache", ".venv", "__pycache__", "build", "dist", "node_modules", "venv"}
)


def is_project_file(path: Path) -> bool:
    """Return whether *path* is an eligible, non-generated project file."""
    return path.is_file() and bool(path.suffix) and not any(part in IGNORED_DIRECTORIES for part in path.parts)


def extract_declared_files(text: str) -> List[str]:
    """Extract unique relative file paths from a target-files section in Markdown."""
    targets: List[str] = []
    in_target_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if any(header in stripped.lower() for header in ("編集対象ファイル", "target files", "target_files")):
            in_target_section = True
        elif in_target_section and (stripped.startswith("## ") or stripped.startswith("# ")):
            in_target_section = False
        elif in_target_section:
            for match in FILE_PATH_PATTERN.findall(stripped):
                if match not in targets:
                    targets.append(match)
    return targets


def discover_project_files(root: Path) -> List[str]:
    """Discover all eligible files below *root*, regardless of programming language."""
    return [str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*") if is_project_file(path)]


def resolve_declared_files(targets: Iterable[str], root: Path) -> List[str]:
    """Resolve missing target names to an existing file with a matching stem."""
    candidates = discover_project_files(root)
    resolved: List[str] = []
    for target in targets:
        if (root / target).exists() or target in resolved:
            resolved.append(target)
            continue
        stem = Path(target).stem.removeprefix("test_").strip("_")
        match = next(
            (
                item
                for item in candidates
                if stem
                and (
                    stem in Path(item).stem.removeprefix("test_").strip("_")
                    or Path(item).stem.removeprefix("test_").strip("_") in stem
                )
            ),
            None,
        )
        resolved.append(match or target)
    return resolved
