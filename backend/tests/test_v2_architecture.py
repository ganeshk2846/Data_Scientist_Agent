"""Architecture guard for the V2 path (build-plan 3.7, ANA-2, B0, SAFE-8)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from contracts.v2 import TOOL_NAMES
from test_an1_architecture import (
    DANGEROUS_CALLS,
    DYNAMIC_CALLS,
    DYNAMIC_IMPORT_ROOTS,
    MODEL_CLIENT_ROOTS,
)
from test_engines_architecture import _call_name, _imports
from tools.registry import TOOL_HANDLERS

SRC = Path(__file__).resolve().parents[1] / "src"
V2_FILES = tuple(SRC / name for name in ("intent.py", "grounding.py", "clarify.py", "planner.py", "executor_v2.py", "sanity.py",
                                         "composer.py", "pipeline_v2.py", "service_v2.py", "tools/registry.py", "tools/__init__.py"))


@pytest.mark.parametrize("source", V2_FILES, ids=lambda path: path.name)
def test_v2_modules_have_no_eval_exec_or_import_by_string(source):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = {_call_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not calls & (DANGEROUS_CALLS | DYNAMIC_CALLS), source.name
    assert not {name.split(".")[0] for name in _imports(tree)} & DYNAMIC_IMPORT_ROOTS, source.name


@pytest.mark.parametrize("source", V2_FILES, ids=lambda path: path.name)
def test_no_v2_module_imports_a_model_client(source):
    roots = {name.split(".")[0] for name in _imports(ast.parse(source.read_text(encoding="utf-8")))}
    assert not roots & MODEL_CLIENT_ROOTS, f"{source.name} imports a model client; the model is injected only as a tie-break"


def test_the_tool_registry_is_exactly_the_closed_tool_union():
    assert set(TOOL_HANDLERS) == set(TOOL_NAMES)


def test_the_planner_only_names_tools_from_the_closed_union():
    tree = ast.parse((SRC / "planner.py").read_text(encoding="utf-8"))
    named = {node.args[1].value for node in ast.walk(tree)
             if isinstance(node, ast.Call) and _call_name(node).endswith("draft.add") and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)}
    assert named and named <= set(TOOL_NAMES), named - set(TOOL_NAMES)


def test_tool_handlers_never_accept_sql_from_params():
    text = (SRC / "tools" / "registry.py").read_text(encoding="utf-8")
    assert 'params["sql"]' not in text and "params.get(\"sql\")" not in text
    assert "SQLValidator(" in text, "every statement passes the existing validator"


def test_the_composer_never_writes_causal_wording():
    text = (SRC / "composer.py").read_text(encoding="utf-8").lower()
    for word in (" caused ", " due to ", " because of ", " led to ", " drove "):
        assert word not in text, word
