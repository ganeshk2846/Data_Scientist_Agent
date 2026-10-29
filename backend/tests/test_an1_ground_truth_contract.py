"""GroundTruthManifest contract tests (DATA-4, DATA-9, ANA-5)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from contracts.models import (
    ChurnProcessMetadata,
    Confounder,
    GroundTruthManifest,
    InsufficientEvidenceCase,
    NegativeControl,
    Period,
    PlantedAnomaly,
    PlantedDriver,
    TrueRiskSegment,
    TruthUnit,
)

TRUTH_MODELS = (
    TruthUnit,
    PlantedAnomaly,
    PlantedDriver,
    Confounder,
    NegativeControl,
    TrueRiskSegment,
    ChurnProcessMetadata,
    InsufficientEvidenceCase,
    GroundTruthManifest,
)
FORBIDDEN_FIELD_NAMES = {
    "callable",
    "code",
    "command",
    "exec",
    "eval",
    "import",
    "import_path",
    "module",
    "path",
    "script",
    "shell",
    "sql",
    "subprocess",
    "uri",
}


def _unit() -> TruthUnit:
    return TruthUnit(dimension="region", value="SP")


def _anomaly(**overrides) -> dict:
    payload = {
        "anomaly_id": "ANOM-001",
        "metric": "orders",
        "unit": _unit(),
        "kind": "level_shift",
        "start": date(2024, 3, 1),
        "end": date(2024, 4, 1),
        "magnitude_pct": -25.0,
    }
    payload.update(overrides)
    return payload


def _manifest(**overrides) -> dict:
    payload = {
        "snapshot_id": "synth-build-001",
        "seed": 20261029,
        "generator_version": "be2-gen-0.1.0",
        "split": "build",
        "anomalies": (_anomaly(),),
        "drivers": (
            {
                "anomaly_id": "ANOM-001",
                "cause_kind": "segment",
                "cause": _unit(),
                "true_share": 0.8,
            },
        ),
        "confounders": (
            {
                "anomaly_id": "ANOM-001",
                "moves_with": TruthUnit(dimension="state", value="SP"),
                "is_cause": False,
            },
        ),
        "negative_controls": (
            {
                "control_id": "CTRL-001",
                "metric": "orders",
                "unit": _unit(),
                "period": Period(
                    start=date(2024, 1, 1),
                    end=date(2024, 2, 1),
                ),
                "kind": "ordinary",
            },
        ),
        "churn_process": {
            "process_id": "CHURN-001",
            "description": "Customers lapse after a documented inactivity window.",
            "params": {"lapse_rate": 0.15, "window_days": 60.0},
            "true_risk_segments": (
                {"segment": "repeat_buyer", "relative_risk": 0.4},
            ),
            "label_table": "churn_labels",
        },
        "insufficient_evidence_cases": (
            {
                "case_id": "IE-001",
                "metric": "orders",
                "unit": _unit(),
                "period": Period(
                    start=date(2024, 5, 1),
                    end=date(2024, 6, 1),
                ),
                "reason": "The unit has too few observations in the window.",
            },
        ),
    }
    payload.update(overrides)
    return payload


def test_valid_manifest_parses_with_all_truth_kinds():
    manifest = GroundTruthManifest.model_validate(_manifest())

    assert manifest.snapshot_id == "synth-build-001"
    assert manifest.seed == 20261029
    assert manifest.generator_version == "be2-gen-0.1.0"
    assert manifest.split == "build"
    assert manifest.is_heldout is False
    assert manifest.anomalies[0].kind == "level_shift"
    assert manifest.drivers[0].cause_kind == "segment"
    assert manifest.confounders[0].is_cause is False
    assert manifest.negative_controls[0].kind == "ordinary"
    assert manifest.churn_process is not None
    assert manifest.churn_process.params == {
        "lapse_rate": 0.15,
        "window_days": 60.0,
    }
    assert manifest.insufficient_evidence_cases[0].case_id == "IE-001"


def test_heldout_split_is_distinct_from_build():
    manifest = GroundTruthManifest.model_validate(
        _manifest(split="heldout", snapshot_id="synth-heldout-001")
    )

    assert manifest.split == "heldout"
    assert manifest.is_heldout is True


@pytest.mark.parametrize(
    "kind",
    ("level_shift", "spike", "dip", "gradual_decay"),
)
def test_all_planted_anomaly_kinds_are_accepted(kind):
    anomaly = PlantedAnomaly.model_validate(_anomaly(kind=kind))

    assert anomaly.kind == kind


@pytest.mark.parametrize(
    "kind",
    ("segment", "category", "carrier", "price_change"),
)
def test_all_planted_driver_cause_kinds_are_accepted(kind):
    driver = PlantedDriver.model_validate(
        {
            "anomaly_id": "ANOM-001",
            "cause_kind": kind,
            "cause": _unit(),
            "true_share": 0.5,
        }
    )

    assert driver.cause_kind == kind


@pytest.mark.parametrize(
    "kind",
    ("ordinary", "holiday_peak", "promotion_peak", "small_volume", "noise"),
)
def test_all_negative_control_kinds_are_accepted(kind):
    control = NegativeControl.model_validate(
        {
            "control_id": "CTRL-001",
            "metric": "orders",
            "unit": _unit(),
            "period": Period(start=date(2024, 1, 1), end=date(2024, 2, 1)),
            "kind": kind,
        }
    )

    assert control.kind == kind


@pytest.mark.parametrize(
    "override",
    (
        {"snapshot_id": ""},
        {"seed": -1},
        {"generator_version": ""},
        {"split": "production"},
        {"churn_process": {"process_id": "CHURN-001"}},
    ),
    ids=("snapshot", "seed", "generator", "split", "incomplete-churn"),
)
def test_malformed_manifest_is_rejected(override):
    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(_manifest(**override))


def test_duplicate_ids_and_dangling_references_are_rejected():
    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(
            _manifest(anomalies=(_anomaly(), _anomaly(metric="revenue")))
        )

    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(
            _manifest(
                drivers=(
                    {
                        "anomaly_id": "ANOM-404",
                        "cause_kind": "segment",
                        "cause": _unit(),
                        "true_share": 0.8,
                    },
                )
            )
        )

    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(
            _manifest(
                confounders=(
                    {
                        "anomaly_id": "ANOM-404",
                        "moves_with": _unit(),
                        "is_cause": False,
                    },
                )
            )
        )


def test_unknown_fields_are_rejected_at_every_level():
    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(_manifest(sql="SELECT 1"))

    payload = _manifest()
    payload["anomalies"] = (_anomaly(command="write manifest"),)
    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(payload)

    with pytest.raises(ValidationError):
        PlantedDriver.model_validate(
            {
                "anomaly_id": "ANOM-001",
                "cause_kind": "segment",
                "cause": _unit(),
                "true_share": 0.8,
                "import_path": "os.system",
            }
        )


def test_invalid_dates_are_rejected():
    with pytest.raises(ValidationError):
        PlantedAnomaly.model_validate(
            _anomaly(end=date(2024, 2, 1))
        )

    with pytest.raises(ValidationError):
        NegativeControl.model_validate(
            {
                "control_id": "CTRL-001",
                "metric": "orders",
                "unit": _unit(),
                "period": Period(
                    start=date(2024, 1, 1),
                    end=date(2024, 1, 1),
                ),
                "kind": "ordinary",
            }
        )

    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(_manifest(seed="not-a-seed"))


@pytest.mark.parametrize(
    "field,value",
    (
        ("anomaly_id", "os.system"),
        ("anomaly_id", "a/b"),
        ("anomaly_id", "1ANOM"),
        ("metric", ""),
    ),
)
def test_invalid_identifiers_are_rejected(field, value):
    with pytest.raises(ValidationError):
        PlantedAnomaly.model_validate(_anomaly(**{field: value}))


def test_dotted_and_path_like_identifiers_are_rejected():
    with pytest.raises(ValidationError):
        TruthUnit(dimension="analysts.anomaly", value="SP")

    with pytest.raises(ValidationError):
        ChurnProcessMetadata(
            process_id="CHURN-001",
            description="documented process",
            label_table="../../etc/passwd",
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("magnitude_pct", float("nan")),
        ("magnitude_pct", float("inf")),
        ("magnitude_pct", float("-inf")),
    ),
)
def test_non_finite_anomaly_numbers_are_rejected(field, value):
    with pytest.raises(ValidationError):
        PlantedAnomaly.model_validate(_anomaly(**{field: value}))


def test_non_finite_driver_risk_and_churn_numbers_are_rejected():
    with pytest.raises(ValidationError):
        PlantedDriver.model_validate(
            {
                "anomaly_id": "ANOM-001",
                "cause_kind": "segment",
                "cause": _unit(),
                "true_share": float("nan"),
            }
        )

    with pytest.raises(ValidationError):
        TrueRiskSegment(segment="repeat_buyer", relative_risk=float("inf"))

    with pytest.raises(ValidationError):
        ChurnProcessMetadata(
            process_id="CHURN-001",
            description="documented process",
            params={"lapse_rate": float("nan")},
            label_table="churn_labels",
        )


def test_serialization_is_deterministic():
    first = GroundTruthManifest.model_validate(_manifest())
    second = GroundTruthManifest.model_validate(_manifest())

    first_json = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    second_json = json.dumps(second.model_dump(mode="json"), sort_keys=True)

    assert first_json == second_json
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_churn_parameter_order_does_not_change_serialization():
    forward = {
        "lapse_rate": 0.15,
        "window_days": 60.0,
        "reactivation_rate": 0.05,
    }
    reversed_order = {
        "reactivation_rate": 0.05,
        "window_days": 60.0,
        "lapse_rate": 0.15,
    }
    first = GroundTruthManifest.model_validate(_manifest())
    first_payload = first.model_dump(mode="json")
    first_payload["churn_process"]["params"] = forward
    second_payload = first.model_dump(mode="json")
    second_payload["churn_process"]["params"] = reversed_order

    first_manifest = GroundTruthManifest.model_validate(first_payload)
    second_manifest = GroundTruthManifest.model_validate(second_payload)

    assert first_manifest.model_dump(mode="json") == second_manifest.model_dump(
        mode="json"
    )


def test_manifest_has_no_executable_or_runtime_instruction_fields():
    for model in TRUTH_MODELS:
        field_names = set(model.model_fields)
        offenders = field_names & FORBIDDEN_FIELD_NAMES
        assert not offenders, f"{model.__name__} exposes unsafe fields: {offenders}"

    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(_manifest(path="data_gen/manifest.json"))

    with pytest.raises(ValidationError):
        GroundTruthManifest.model_validate(_manifest(callable="run_planted_truth"))
