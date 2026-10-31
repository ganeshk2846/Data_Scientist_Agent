"""Focused tests for the fixed AN-1 analyst registry (ANA-1, ANA-2, SAFE-8)."""

from __future__ import annotations

import inspect

import pytest

from analysts import registry
from analysts.anomaly import AnomalyAnalyst, AnomalyParams
from analysts.driver import DriverAnalyst, DriverParams
from analysts.forecast import ForecastAnalyst, ForecastParams
from analysts.impact import ImpactAnalyst, ImpactParams
from analysts.registry import (
    APPROVED_MODULES,
    AnalystMetadata,
    AnalystRegistryError,
    AnalystUnavailableError,
    UnknownAnalystError,
)
from analysts.scenario import ScenarioAnalyst, ScenarioParams
from analysts.segment import SegmentAnalyst, SegmentParams


IMPLEMENTED_TYPES = {
    "anomaly": AnomalyAnalyst,
    "driver": DriverAnalyst,
    "forecast": ForecastAnalyst,
    "impact": ImpactAnalyst,
    "scenario": ScenarioAnalyst,
    "segment": SegmentAnalyst,
}
PARAMETER_SCHEMAS = {
    "anomaly": AnomalyParams,
    "driver": DriverParams,
    "forecast": ForecastParams,
    "impact": ImpactParams,
    "scenario": ScenarioParams,
    "segment": SegmentParams,
}


@pytest.mark.parametrize("module", tuple(IMPLEMENTED_TYPES), ids=str)
def test_implemented_module_is_registered(module):
    metadata = registry.describe(module)

    assert isinstance(metadata, AnalystMetadata)
    assert metadata.module == module
    assert metadata.status == "implemented"
    assert metadata.callable_available is True
    assert metadata.unavailable_reason is None
    assert metadata.requirement_ids == ("ANA-1", "ANA-2", "SAFE-8")
    assert metadata.params_schema is PARAMETER_SCHEMAS[module]
    assert metadata.params_schema.model_json_schema()["properties"]

    analyst = registry.resolve(module)

    assert isinstance(analyst, IMPLEMENTED_TYPES[module])
    assert analyst.module == module
    assert registry.resolve(module) is analyst


@pytest.mark.parametrize("module", ("risk", "advisor"), ids=str)
def test_planned_module_is_described_but_cannot_run(module):
    metadata = registry.describe(module)

    assert isinstance(metadata, AnalystMetadata)
    assert metadata.module == module
    assert metadata.status == "planned"
    assert metadata.callable_available is False
    assert metadata.unavailable_reason
    assert "not implemented" in metadata.unavailable_reason.lower()

    with pytest.raises(AnalystUnavailableError) as exc_info:
        registry.resolve(module)

    message = str(exc_info.value)
    assert module in message
    assert "planned" in message
    assert "not implemented" in message


@pytest.mark.parametrize(
    "module",
    (
        "freeform_python",
        "analysts.anomaly",
        "Anomaly",
        "",
        "risk2",
        "register",
    ),
    ids=repr,
)
def test_unknown_module_is_rejected_with_useful_message(module):
    with pytest.raises(UnknownAnalystError) as exc_info:
        registry.describe(module)

    message = str(exc_info.value)
    assert repr(module) in message
    for approved in APPROVED_MODULES:
        assert approved in message


def test_registry_rejects_arbitrary_callables_and_objects():
    with pytest.raises(UnknownAnalystError):
        registry.resolve(lambda: None)

    with pytest.raises(UnknownAnalystError):
        registry.describe(object())


def test_registry_has_no_dynamic_registration_api():
    assert not hasattr(registry, "register")
    assert not hasattr(registry, "register_module")

    parameters = list(inspect.signature(registry.resolve).parameters.values())
    assert [parameter.name for parameter in parameters] == ["module"]


def test_registry_metadata_is_deterministic_and_complete():
    first = registry.list_modules()
    second = registry.list_modules()

    assert first == second
    assert tuple(item.module for item in first) == APPROVED_MODULES
    assert registry.approved_module_names() == APPROVED_MODULES
    assert len(first) == len(set(APPROVED_MODULES))
    assert all(item.requirement_ids == ("ANA-1", "ANA-2", "SAFE-8") for item in first)


def test_registry_errors_are_typed():
    assert issubclass(AnalystRegistryError, ValueError)
    assert issubclass(UnknownAnalystError, AnalystRegistryError)
    assert issubclass(AnalystUnavailableError, AnalystRegistryError)


def test_approved_modules_are_the_only_registered_modules():
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
    assert registry.approved_module_names() == (
        "anomaly",
        "driver",
        "forecast",
        "impact",
        "scenario",
        "segment",
        "risk",
        "advisor",
    )
