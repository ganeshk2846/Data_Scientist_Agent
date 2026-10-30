"""SAFE-8 guardrails for the V2 semantic layer (build plan gate G2).

The semantic layer may read the warehouse through SQLAlchemy, but it never
imports a model client, opens a network connection, spawns a shell, or runs
code from a string.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_an1_architecture import (
    DANGEROUS_CALLS,
    MODEL_CLIENT_ROOTS,
    NETWORK_ROOTS,
    SHELL_ROOTS,
    _call_names,
    _dynamic_import_calls,
    _matching_imports,
    _parse,
    _shell_calls,
)

SEMANTIC_DIR = Path(__file__).resolve().parents[1] / "src" / "semantic"
SEMANTIC_FILES = tuple(sorted(SEMANTIC_DIR.glob("*.py"), key=lambda path: path.name))


def test_semantic_package_is_scanned():
    names = {path.name for path in SEMANTIC_FILES}
    assert {"completeness.py", "aggregation.py", "tables.py", "layers.py"} <= names


@pytest.mark.parametrize("source", SEMANTIC_FILES, ids=lambda path: path.name)
def test_no_model_network_or_shell_imports(source):
    assert _matching_imports(source, MODEL_CLIENT_ROOTS | NETWORK_ROOTS | SHELL_ROOTS) == ()


@pytest.mark.parametrize("source", SEMANTIC_FILES, ids=lambda path: path.name)
def test_no_eval_exec_or_dynamic_import(source):
    tree = _parse(source)
    assert not set(_call_names(tree)) & DANGEROUS_CALLS
    assert tuple(_shell_calls(tree)) == ()
    assert tuple(_dynamic_import_calls(tree)) == ()
