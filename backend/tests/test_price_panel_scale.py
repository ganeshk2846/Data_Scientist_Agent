"""The price panel behind 'what if we raise prices X%?' at real-catalogue scale (X6, must-answer).

At 32,951 products the per-product list-price loop took ~80 s, the plan's wall-clock budget
skipped the baseline step and the scenario returned insufficient_evidence. The vectorised
version must give the same panel, fast.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from engines.prep import daily_list_price


def _reference(price_history: pd.DataFrame, products: pd.DataFrame, dates) -> pd.DataFrame:
    """The previous per-product implementation: each product's last price carried forward, then the category mean."""
    index = pd.Index(sorted({str(value)[:10] for value in dates}), name="date")
    history = price_history.merge(products[["product_id", "product_category_name"]], on="product_id", how="inner")
    history = history.dropna(subset=["product_category_name"]).sort_values(["product_id", "date"], kind="mergesort")
    frames = []
    for product_id, rows in history.groupby("product_id", sort=True):
        steps = rows.assign(date=rows["date"].astype(str).str[:10]).drop_duplicates("date", keep="last").set_index("date")["price"]
        daily = steps.reindex(steps.index.union(index)).sort_index().ffill().reindex(index)
        frames.append(pd.DataFrame({"date": index, "category": rows["product_category_name"].iloc[0], "product_id": product_id,
                                    "list_price": daily.to_numpy(dtype=float)}))
    panel = pd.concat(frames, ignore_index=True).dropna(subset=["list_price"])
    return panel.groupby(["date", "category"], as_index=False)["list_price"].mean()


def _history(products: int, seed: int = 3):
    rng = np.random.default_rng(seed)
    ids = [f"p{index}" for index in range(products)]
    categories = [None if index % 37 == 0 else f"c{index % 7}" for index in range(products)]
    rows = []
    for product_id in ids:
        for _ in range(int(rng.integers(1, 6))):
            day = pd.Timestamp("2016-08-01") + pd.Timedelta(days=int(rng.integers(0, 900)))  # some before, some after the panel
            rows.append((product_id, f"{day:%Y-%m-%d} 00:00:00", round(float(rng.lognormal(4, 0.5)), 2)))
    rows.append((ids[1], rows[0][1], 1.0))  # a second change on an existing day: the last row wins
    history = pd.DataFrame(rows, columns=["product_id", "date", "price"])
    catalogue = pd.DataFrame({"product_id": ids, "product_category_name": categories})
    dates = [f"{day:%Y-%m-%d}" for day in pd.date_range("2016-10-01", "2018-08-31", freq="D")]
    return history, catalogue, dates


def test_the_vectorised_list_price_equals_carrying_every_product_forward():
    history, catalogue, dates = _history(300)
    expected = _reference(history, catalogue, dates).reset_index(drop=True)
    got = daily_list_price(history, catalogue, dates).reset_index(drop=True)
    assert list(got.columns) == ["date", "category", "list_price"]
    pd.testing.assert_frame_equal(got[["date", "category"]], expected[["date", "category"]])
    np.testing.assert_allclose(got["list_price"].to_numpy(), expected["list_price"].to_numpy(), rtol=1e-12, atol=1e-9)


def test_the_list_price_panel_scales_to_a_real_catalogue():
    history, catalogue, dates = _history(20_000, seed=5)
    started = time.perf_counter()
    panel = daily_list_price(history, catalogue, dates)
    assert time.perf_counter() - started < 10.0  # was minutes with one loop iteration per product
    assert not panel.empty and panel["list_price"].notna().all()


def test_no_price_history_names_what_is_missing_instead_of_contradicting_itself(tmp_path):
    from pipeline_v2 import PipelineV2
    from service import build_runtime

    from scripts.synth.fixture import build_fixture

    runtime = build_runtime(build_fixture(tmp_path / "olist.sqlite"), reasoning_client=False)
    try:
        envelope = PipelineV2(guard=runtime.guard, catalog=runtime.catalog, manager=runtime.manager).run(
            "What if we raise prices 5%?", run_id="no-prices").envelope
    finally:
        runtime.close()
    assert envelope.status == "insufficient_evidence"  # nothing to fit on, so no figure (SAFE-8)
    reason = next(step.reason for step in envelope.step_results if step.tool == "python.scenario")
    assert "no price history" in reason and "price_history" in reason
    assert "Only price-change scenarios" not in reason


@pytest.mark.parametrize("empty", ["history", "dates"])
def test_empty_inputs_give_an_empty_panel(empty):
    history, catalogue, dates = _history(5)
    if empty == "history":
        history = history.iloc[0:0]
    else:
        dates = []
    assert daily_list_price(history, catalogue, dates).empty
