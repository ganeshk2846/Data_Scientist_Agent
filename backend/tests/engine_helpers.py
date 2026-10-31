"""Small builders shared by the engine tests (not a test module)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from engines.base import EngineData, table_from_frame
from engines.report import EngineReport

REPORT_PARTS = ("tables", "key_numbers", "method", "assumptions", "confidence", "chart_hint")


def table(frame: pd.DataFrame, query_id: str, **roles):
    return table_from_frame(frame, query_id=query_id, roles=roles)


def data(tables: dict, *, sources: tuple[str, ...] = (), seed: int = 7) -> EngineData:
    return EngineData(tables=tables, source_tables=sources, seed=seed, run_id="RUN-ENGINE-TEST", step_id="P1")


def months(start: str = "2016-10", count: int = 23) -> list[str]:
    return [str(period) for period in pd.period_range(start, periods=count, freq="M")]


def trending_series(count: int = 23, *, seed: int = 1, slope: float = 3.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    labels = months(count=count)
    values = 100.0 + np.arange(count) * slope + rng.normal(0.0, 2.0, count)
    return pd.DataFrame({"month": labels, "value": values})


def assert_complete_report(report: EngineReport) -> None:
    """Every ok result returns tables, key numbers, method, assumptions, confidence and a chart hint."""
    assert report.tables, "report has no tables"
    assert report.key_numbers, "report has no key numbers"
    assert report.method
    assert report.assumptions
    assert report.confidence.level in {"high", "medium", "low"}
    assert report.chart_hint is not None
    names = {item.name for item in report.tables}
    assert report.chart_hint.table in names, f"chart hint points at {report.chart_hint.table!r}, not one of {names}"


def stable(result) -> str:
    """A result's JSON without its wall-clock duration (the only non-deterministic field)."""
    return result.model_copy(update={"duration_ms": 0}).model_dump_json()


def day(text: str) -> date:
    return date.fromisoformat(text)
