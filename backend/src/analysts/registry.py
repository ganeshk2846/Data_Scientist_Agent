"""Fixed safe registry for AN-1 analyst modules (ANA-1, ANA-2, SAFE-8).

The registry is deliberately a closed mapping. Callers name a module; they
cannot register a function, import a path, supply a class, or provide code.
Implemented modules are resolved to fixed in-process analyst instances.
Planned modules are described for planning and UI purposes but fail closed when
a caller tries to run them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol

from contracts.models import AnalystInput, AnalystOutput, ContractModel

from .anomaly import AnomalyAnalyst, AnomalyParams
from .driver import DriverAnalyst, DriverParams
from .forecast import ForecastAnalyst
from .forecast import ForecastParams
from .impact import ImpactAnalyst, ImpactParams
from .scenario import ScenarioAnalyst, ScenarioParams
from .segment import SegmentAnalyst, SegmentParams

AnalystName = Literal[
    "anomaly",
    "driver",
    "risk",
    "advisor",
    "forecast",
    "impact",
    "scenario",
    "segment",
]
AnalystModuleStatus = Literal["implemented", "planned"]

APPROVED_MODULES: tuple[AnalystName, ...] = (
    "anomaly",
    "driver",
    "forecast",
    "impact",
    "scenario",
    "segment",
    "risk",
    "advisor",
)

_REGISTRY_REQUIREMENTS: tuple[str, ...] = ("ANA-1", "ANA-2", "SAFE-8")


class AnalystRegistryError(ValueError):
    """Base error for invalid or unavailable analyst registry lookups."""


class UnknownAnalystError(AnalystRegistryError):
    """The requested module is not part of the fixed approved set."""


class AnalystUnavailableError(AnalystRegistryError):
    """The requested module is approved but planned and cannot be run."""


class RegisteredAnalyst(Protocol):
    """The minimal callable contract exposed by the registry."""

    module: str

    def run(self, analyst_input: AnalystInput) -> AnalystOutput:
        ...


@dataclass(frozen=True, slots=True)
class AnalystMetadata:
    """Deterministic, immutable metadata for one approved module."""

    module: AnalystName
    status: AnalystModuleStatus
    requirement_ids: tuple[str, ...]
    callable_available: bool
    unavailable_reason: str | None = None
    params_schema: type[ContractModel] | None = None


_IMPLEMENTED_ANALYSTS: Mapping[str, RegisteredAnalyst] = MappingProxyType(
    {
        "anomaly": AnomalyAnalyst(),
        "driver": DriverAnalyst(),
        "forecast": ForecastAnalyst(),
        "impact": ImpactAnalyst(),
        "scenario": ScenarioAnalyst(),
        "segment": SegmentAnalyst(),
    }
)

_METADATA: Mapping[str, AnalystMetadata] = MappingProxyType(
    {
        "anomaly": AnalystMetadata(
            module="anomaly",
            status="implemented",
            requirement_ids=_REGISTRY_REQUIREMENTS,
            callable_available=True,
            params_schema=AnomalyParams,
        ),
        "driver": AnalystMetadata(
            module="driver",
            status="implemented",
            requirement_ids=_REGISTRY_REQUIREMENTS,
            callable_available=True,
            params_schema=DriverParams,
        ),
        "forecast": AnalystMetadata(
            module="forecast",
            status="implemented",
            requirement_ids=_REGISTRY_REQUIREMENTS,
            callable_available=True,
            params_schema=ForecastParams,
        ),
        "impact": AnalystMetadata(
            module="impact",
            status="implemented",
            requirement_ids=_REGISTRY_REQUIREMENTS,
            callable_available=True,
            params_schema=ImpactParams,
        ),
        "scenario": AnalystMetadata(
            module="scenario",
            status="implemented",
            requirement_ids=_REGISTRY_REQUIREMENTS,
            callable_available=True,
            params_schema=ScenarioParams,
        ),
        "segment": AnalystMetadata(
            module="segment",
            status="implemented",
            requirement_ids=_REGISTRY_REQUIREMENTS,
            callable_available=True,
            params_schema=SegmentParams,
        ),
        "risk": AnalystMetadata(
            module="risk",
            status="planned",
            requirement_ids=_REGISTRY_REQUIREMENTS,
            callable_available=False,
            unavailable_reason=(
                "Risk Analyst is planned for a later AN-1 phase and is not "
                "implemented in Phase 1."
            ),
        ),
        "advisor": AnalystMetadata(
            module="advisor",
            status="planned",
            requirement_ids=_REGISTRY_REQUIREMENTS,
            callable_available=False,
            unavailable_reason=(
                "Advisor is planned for a later AN-1 phase and is not "
                "implemented in Phase 1."
            ),
        ),
    }
)


def describe(module: str) -> AnalystMetadata:
    """Return metadata for an approved module, including planned modules.

    Raises:
        UnknownAnalystError: If ``module`` is not one of ``APPROVED_MODULES``.
    """

    try:
        return _METADATA[module]
    except (KeyError, TypeError):
        approved = ", ".join(APPROVED_MODULES)
        raise UnknownAnalystError(
            f"unknown analyst module {module!r}; approved modules are: "
            f"{approved}"
        ) from None


def resolve(module: str) -> RegisteredAnalyst:
    """Return the fixed analyst instance for an implemented module.

    Planned modules fail closed instead of returning a placeholder that could
    be mistaken for an implementation.

    Raises:
        UnknownAnalystError: If ``module`` is not approved.
        AnalystUnavailableError: If ``module`` is planned, not implemented.
    """

    metadata = describe(module)
    analyst = _IMPLEMENTED_ANALYSTS.get(module)
    if analyst is None:
        reason = (
            metadata.unavailable_reason
            or "no implementation is registered for this module."
        )
        raise AnalystUnavailableError(
            f"analyst module {module!r} is {metadata.status}: {reason}"
        )
    return analyst


def list_modules() -> tuple[AnalystMetadata, ...]:
    """List metadata in the fixed approved order."""

    return tuple(_METADATA[module] for module in APPROVED_MODULES)


def approved_module_names() -> tuple[AnalystName, ...]:
    """Return the fixed approved module names in deterministic order."""

    return APPROVED_MODULES


if tuple(metadata.module for metadata in _METADATA.values()) != APPROVED_MODULES:
    raise RuntimeError("analyst registry metadata does not match approved modules")

for _module, _metadata in _METADATA.items():
    if _metadata.callable_available != (_module in _IMPLEMENTED_ANALYSTS):
        raise RuntimeError(
            f"analyst registry callable availability is inconsistent for {_module!r}"
        )
if set(_IMPLEMENTED_ANALYSTS) - set(APPROVED_MODULES):
    raise RuntimeError("analyst registry contains an unapproved implementation")


__all__ = [
    "APPROVED_MODULES",
    "AnalystMetadata",
    "AnalystModuleStatus",
    "AnalystName",
    "AnalystRegistryError",
    "AnalystUnavailableError",
    "RegisteredAnalyst",
    "UnknownAnalystError",
    "approved_module_names",
    "describe",
    "list_modules",
    "resolve",
]
