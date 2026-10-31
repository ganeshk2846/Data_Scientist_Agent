"""Architecture guardrails for AN-1-owned analyst sources (SAFE-8)."""

from __future__ import annotations

import ast
import importlib
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ANALYST_DIR = Path(__file__).resolve().parents[1] / "src" / "analysts"
ANALYST_FILES = tuple(sorted(ANALYST_DIR.glob("*.py"), key=lambda path: path.name))

MODEL_CLIENT_ROOTS = {
    "anthropic",
    "google.generativeai",
    "litellm",
    "models",
    "ollama",
    "openai",
}
DATABASE_ROOTS = {
    "MySQLdb",
    "asyncpg",
    "duckdb",
    "psycopg",
    "psycopg2",
    "pymysql",
    "sqlalchemy",
    "sqlite3",
}
NETWORK_ROOTS = {
    "aiohttp",
    "boto3",
    "ftplib",
    "http",
    "httpx",
    "paramiko",
    "requests",
    "socket",
    "smtplib",
    "telnetlib",
    "urllib",
    "urllib3",
    "websockets",
}
SHELL_ROOTS = {"pty", "subprocess"}
DYNAMIC_IMPORT_ROOTS = {"importlib", "runpy"}
# pandas, scipy, scikit-learn, statsmodels and prophet are the approved V2 engine stack
# (build-plan-v2.md section 4); prophet is confined to _prophet.py.
ALLOWED_THIRD_PARTY_ROOTS = {
    "numpy",
    "pandas",
    "prophet",
    "pydantic",
    "scipy",
    "sklearn",
    "statsmodels",
}
ALLOWED_LOCAL_ROOTS = {"analysts", "contracts"}
STDLIB_ROOTS = frozenset(sys.stdlib_module_names)
SHELL_CALLS = {
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "os.popen",
    "os.system",
    "pty.spawn",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    "subprocess.run",
}
DANGEROUS_CALLS = {"builtins.eval", "builtins.exec", "eval", "exec"}
DYNAMIC_CALLS = {"__import__", "builtins.__import__"}
SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
)
SENSITIVE_NAME = re.compile(
    r"(?i)(api[_-]?key|apikey|secret|password|passwd|private[_-]?key|"
    r"access[_-]?key|auth[_-]?token|bearer[_-]?token)"
)


def _parse(source: Path) -> ast.Module:
    return ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


def _normalize_import(name: str) -> str | None:
    if not name:
        return None
    if name.startswith("."):
        if not name.startswith(".."):
            return None
        name = name.lstrip(".")
    return name or None


def _import_candidates(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            base = f"{prefix}{node.module}" if node.module else prefix
            if base:
                yield base
            for alias in node.names:
                if alias.name == "*":
                    continue
                yield f"{base}.{alias.name}" if base else alias.name


def _matches_root(name: str, roots: set[str]) -> bool:
    normalized = _normalize_import(name)
    if normalized is None:
        return False
    return any(
        normalized == root or normalized.startswith(f"{root}.")
        for root in roots
    )


def _matching_imports(source: Path, roots: set[str]) -> tuple[str, ...]:
    candidates = _import_candidates(_parse(source))
    return tuple(sorted({name for name in candidates if _matches_root(name, roots)}))


def _absolute_import_roots(tree: ast.Module) -> Iterator[str]:
    for candidate in _import_candidates(tree):
        normalized = _normalize_import(candidate)
        if normalized is not None:
            yield normalized.split(".", 1)[0]


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _call_names(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name:
                yield name


def _shell_calls(tree: ast.Module) -> Iterator[str]:
    for name in _call_names(tree):
        if (
            name in SHELL_CALLS
            or name.startswith("os.spawn")
            or name.startswith("os.exec")
            or name.endswith(".create_subprocess_exec")
            or name.endswith(".create_subprocess_shell")
        ):
            yield name


def _dynamic_import_calls(tree: ast.Module) -> Iterator[str]:
    for name in _call_names(tree):
        if (
            name in DYNAMIC_CALLS
            or name.endswith(".import_module")
            or name.startswith("runpy.")
        ):
            yield name


def _target_names(target: ast.AST) -> Iterator[str]:
    if isinstance(target, (ast.Tuple, ast.List)):
        for item in target.elts:
            yield from _target_names(item)
        return
    if isinstance(target, ast.Name):
        yield target.id
        return
    if isinstance(target, ast.Attribute):
        name = _call_name(target)
        if name:
            yield name
        return
    if isinstance(target, ast.Subscript):
        key = target.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            yield key.value


def _secret_assignments(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue

        if not (
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value.strip()
        ):
            continue

        for target in targets:
            for name in _target_names(target):
                if SENSITIVE_NAME.search(name):
                    yield f"{name} at line {node.lineno}"


def _secret_literals(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for pattern in SECRET_PATTERNS:
            match = pattern.search(node.value)
            if match:
                yield f"line {node.lineno}: {match.group(0)[:8]}..."


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_analyst_sources_do_not_import_model_clients(source):
    offenders = _matching_imports(source, MODEL_CLIENT_ROOTS)
    assert not offenders, f"{source.name} imports model-client modules: {offenders}"


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_prophet_import_is_confined_to_adapter(source):
    offenders = _matching_imports(source, {"prophet"})
    assert not offenders or source.name == "_prophet.py", (
        f"{source.name} imports Prophet outside the optional adapter: {offenders}"
    )


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_analyst_sources_do_not_import_databases(source):
    offenders = _matching_imports(source, DATABASE_ROOTS)
    assert not offenders, f"{source.name} imports database modules: {offenders}"


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_analyst_sources_do_not_import_network_modules(source):
    offenders = _matching_imports(source, NETWORK_ROOTS)
    assert not offenders, f"{source.name} imports network modules: {offenders}"


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_analyst_sources_use_only_approved_dependencies(source):
    roots = set(_absolute_import_roots(_parse(source)))
    unexpected = sorted(
        roots - STDLIB_ROOTS - ALLOWED_THIRD_PARTY_ROOTS - ALLOWED_LOCAL_ROOTS
    )
    assert not unexpected, (
        f"{source.name} uses unapproved dependency roots: {unexpected}"
    )


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_analyst_sources_do_not_use_shell_execution(source):
    tree = _parse(source)
    import_offenders = _matching_imports(source, SHELL_ROOTS)
    call_offenders = tuple(_shell_calls(tree))
    assert not import_offenders, (
        f"{source.name} imports shell modules: {import_offenders}"
    )
    assert not call_offenders, f"{source.name} uses shell calls: {call_offenders}"


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_analyst_sources_do_not_use_eval_or_exec(source):
    tree = _parse(source)
    offenders = tuple(
        name for name in _call_names(tree) if name in DANGEROUS_CALLS
    )
    assert not offenders, f"{source.name} uses eval/exec calls: {offenders}"


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_analyst_sources_do_not_use_dynamic_imports(source):
    tree = _parse(source)
    import_offenders = _matching_imports(source, DYNAMIC_IMPORT_ROOTS)
    call_offenders = tuple(_dynamic_import_calls(tree))
    assert not import_offenders, (
        f"{source.name} imports dynamic-import modules: {import_offenders}"
    )
    assert not call_offenders, (
        f"{source.name} uses dynamic-import calls: {call_offenders}"
    )


@pytest.mark.parametrize("source", ANALYST_FILES, ids=lambda path: path.name)
def test_analyst_sources_do_not_contain_hard_coded_secrets(source):
    tree = _parse(source)
    offenders = tuple(_secret_assignments(tree)) + tuple(_secret_literals(tree))
    assert not offenders, f"{source.name} contains secret-like values: {offenders}"


@pytest.mark.parametrize(
    "module_name",
    (
        "analysts",
        "analysts.anomaly",
        "analysts.driver",
        "analysts.forecast",
        "analysts.harness",
        "analysts.impact",
        "analysts.elasticity",
        "analysts.registry",
        "analysts.scenario",
        "analysts.segment",
    ),
)
def test_analyst_modules_remain_importable(module_name):
    assert importlib.import_module(module_name) is not None


def test_registry_exposes_only_the_fixed_approved_modules():
    registry = importlib.import_module("analysts.registry")

    assert registry.APPROVED_MODULES == (
        "anomaly",
        "driver",
        "forecast",
        "impact",
        "scenario",
        "segment",
        "risk",
        "advisor",
    )
    assert tuple(item.module for item in registry.list_modules()) == (
        "anomaly",
        "driver",
        "forecast",
        "impact",
        "scenario",
        "segment",
        "risk",
        "advisor",
    )
    assert registry.resolve("anomaly").module == "anomaly"
    assert registry.resolve("driver").module == "driver"
    assert registry.resolve("forecast").module == "forecast"
    assert registry.resolve("impact").module == "impact"
    assert registry.resolve("scenario").module == "scenario"
    assert registry.resolve("segment").module == "segment"
    assert not hasattr(registry, "register")
    assert not hasattr(registry, "register_module")
