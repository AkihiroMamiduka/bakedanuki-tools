# coding: utf-8
from __future__ import annotations

import ast
import tokenize
from collections.abc import Iterator
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOTS = (
    REPOSITORY_ROOT / "bakedanuki" / "bakedanuki-tools" / "python",
    REPOSITORY_ROOT / "tests",
)
POWERSHELL_ROOT = REPOSITORY_ROOT / "scripts"


def _iter_python_files() -> Iterator[Path]:
    """comment policyの監査対象となるPythonファイルを返す。"""
    for root in PYTHON_ROOTS:
        yield from sorted(root.rglob("*.py"))


def _find_missing_docstrings(path: Path) -> list[str]:
    """指定ファイルからdocstringのない関数とメソッドを返す。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    missing: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is None:
                relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
                missing.append(f"{relative_path}:{node.lineno}:{node.name}")
    return missing


def _find_python_comment_periods(path: Path) -> list[str]:
    """指定Pythonファイルから句点で終わる1行コメントを返す。"""
    violations: list[str] = []
    with path.open(encoding="utf-8", newline="") as stream:
        for token in tokenize.generate_tokens(stream.readline):
            if token.type == tokenize.COMMENT and token.string.endswith("。"):
                relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
                violations.append(f"{relative_path}:{token.start[0]}")
    return violations


def _find_powershell_comment_periods(path: Path) -> list[str]:
    """指定PowerShellファイルから句点で終わる1行コメントを返す。"""
    violations: list[str] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if line.lstrip().startswith("#") and line.rstrip().endswith("。"):
            relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
            violations.append(f"{relative_path}:{line_number}")
    return violations


def test_all_functions_and_methods_have_docstrings() -> None:
    """すべてのPython関数とメソッドにdocstringがあることを確認する。"""
    missing = [
        violation
        for path in _iter_python_files()
        for violation in _find_missing_docstrings(path)
    ]

    assert not missing, "docstringがありません:\n" + "\n".join(missing)


def test_one_line_comments_do_not_end_with_japanese_period() -> None:
    """1行コメントが句点で終わっていないことを確認する。"""
    violations = [
        violation
        for path in _iter_python_files()
        for violation in _find_python_comment_periods(path)
    ]
    violations.extend(
        violation
        for path in sorted(POWERSHELL_ROOT.glob("*.ps1"))
        for violation in _find_powershell_comment_periods(path)
    )

    assert not violations, "句点で終わる1行コメントがあります:\n" + "\n".join(
        violations
    )
