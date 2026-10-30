"""Architecture guardrails for the V2 engine layer (SAFE-8, ANA-2, B0).

Engines are deterministic Python over supplied rows: no model client, no
network, no shell, no dynamic import, no warehouse connection. The single
exception is the descriptive engine, which computes its figures in SQL over
a private ``:memory:`` SQLite database loaded from its input rows.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest
from test_an1_architecture import (
    DANGEROUS_CALLS,
    DATABASE_ROOTS,
    DYNAMIC_CALLS,
    DYNAMIC_IMPORT_ROOTS,
    MODEL_CLIENT_ROOTS,
    NETWORK_ROOTS,
    SHELL_CALLS,
    SHELL_ROOTS,
)

ENGINE_DIR = Path(__file__).resolve().parents[1] / "src" / "engines"
ENGINE_FILES = tuple(sorted(ENGINE_DIR.glob("*.py"), key=lambda path: path.name))
ALLOWED_THIRD_PARTY = {"numpy", "pandas", "pydantic", "scipy", "sklearn", "statsmodels"}
ALLOWED_LOCAL = {"analysts", "contracts", "engines", "semantic"}
SQL_ENGINE = "descriptive.py"
STDLIB = frozenset(sys.stdlib_module_names)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _call_name(node: ast.Call) -> str:
    parts: list[str] = []
    target = node.func
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    return ".".join(reversed(parts))


def test_engine_package_exists_with_every_engine():
    names = {path.name for path in ENGINE_FILES}
    assert {"__init__.py", "base.py", "report.py", "descriptive.py", "diagnostic.py", "impact.py",
            "forecast.py", "scenario.py", "prescriptive.py", "horizon.py", "prep.py"} <= names


@pytest.mark.parametrize("source", ENGINE_FILES, ids=lambda path: path.name)
def test_engines_import_only_the_approved_stack(source):
    offenders = []
    for name in _imports(_tree(source)):
        root = name.split(".")[0]
        if root in MODEL_CLIENT_ROOTS or root in NETWORK_ROOTS or root in SHELL_ROOTS or root in DYNAMIC_IMPORT_ROOTS:
            offenders.append(name)
        elif root in DATABASE_ROOTS and not (root == "sqlite3" and source.name == SQL_ENGINE):
            offenders.append(name)
        elif root not in STDLIB and root not in ALLOWED_THIRD_PARTY and root not in ALLOWED_LOCAL:
            offenders.append(name)
    assert not offenders, f"{source.name} imports {offenders}"


@pytest.mark.parametrize("source", ENGINE_FILES, ids=lambda path: path.name)
def test_engines_have_no_shell_eval_or_dynamic_import_calls(source):
    calls = {_call_name(node) for node in ast.walk(_tree(source)) if isinstance(node, ast.Call)}
    assert not calls & (SHELL_CALLS | DANGEROUS_CALLS | DYNAMIC_CALLS), source.name


def test_descriptive_engine_only_opens_an_in_memory_database():
    tree = _tree(ENGINE_DIR / SQL_ENGINE)
    connects = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _call_name(node) == "sqlite3.connect"]
    assert connects, "the descriptive engine is expected to compute in SQL"
    for node in connects:
        assert len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and node.args[0].value == ":memory:"
        assert not node.keywords


@pytest.mark.parametrize("source", [path for path in ENGINE_FILES if path.name != SQL_ENGINE], ids=lambda path: path.name)
def test_only_the_descriptive_engine_contains_sql(source):
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.upper()
            assert not ("SELECT " in text and " FROM " in text), f"{source.name} embeds SQL: {node.value[:60]!r}"


def test_engines_never_reference_a_model_or_prompt():
    for source in ENGINE_FILES:
        text = source.read_text(encoding="utf-8").lower()
        for marker in ("ollama", "openai", "anthropic", "prompt(", "chat.completions", "llm_client"):
            assert marker not in text, f"{source.name} mentions {marker!r}"


@pytest.mark.parametrize("module", [f"engines.{path.stem}" if path.stem != "__init__" else "engines" for path in ENGINE_FILES])
def test_engine_modules_import(module):
    assert importlib.import_module(module) is not None
