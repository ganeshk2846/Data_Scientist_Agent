"""Deterministic table shaping for the engines (pure pandas, no I/O).

Upstream ``sql`` steps return warehouse rows; these helpers reshape them
into the tables the engines read - a category-day sales panel with
effective price, a category-month elasticity panel, state and customer
feature rows. Every output value is a sum, mean, carry-forward or ratio of
input rows; nothing is estimated here (SAFE-8).
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from contracts.models import TableRef

from .base import derived_query_id, frame_from_table, table_from_frame


def _dates(values: Iterable[str]) -> pd.Index:
    return pd.Index(sorted({str(value)[:10] for value in values}), name="date")


def daily_list_price(price_history: pd.DataFrame, products: pd.DataFrame, dates: Iterable[str]) -> pd.DataFrame:
    """Mean list price per category and day, each product's last price carried forward.

    ``price_history`` holds one row per list-price change (product_id, date,
    price); ``products`` maps product_id to product_category_name.
    """
    index = _dates(dates)
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


def daily_discount(promotions: pd.DataFrame, dates: Iterable[str], categories: Iterable[str]) -> pd.DataFrame:
    """The deepest active promotion discount (%) per category and day (0 when none)."""
    index = _dates(dates)
    grid = pd.MultiIndex.from_product([index, sorted(set(categories))], names=["date", "category"])
    discount = pd.Series(0.0, index=grid)
    for row in promotions.sort_values(["category", "start_date", "promo_id"], kind="mergesort").itertuples(index=False):
        active = (index >= str(row.start_date)[:10]) & (index <= str(row.end_date)[:10])
        for day in index[active]:
            key = (day, row.category)
            if key in discount.index:
                discount[key] = max(discount[key], float(row.discount_pct))
    return discount.rename("discount_pct").reset_index()


def monthly_promotion_intensity(promotions: pd.DataFrame, months: Iterable[str]) -> pd.DataFrame:
    """Discount-weighted promotion days per calendar day, one row per month (0 when nothing ran).

    Each promotion contributes ``discount_pct x days active in the month``;
    the sum is divided by the days in the month. A sum and a ratio of input
    rows only.
    """
    rows = []
    for month in sorted({str(value)[:7] for value in months}):
        first = pd.Timestamp(f"{month}-01")
        last = first + pd.offsets.MonthEnd(0)
        total = 0.0
        for row in promotions.itertuples(index=False):
            start = max(first, pd.Timestamp(str(row.start_date)[:10]))
            end = min(last, pd.Timestamp(str(row.end_date)[:10]))
            if end >= start:
                total += float(row.discount_pct) * ((end - start).days + 1)
        rows.append({"month": month, "promo_discount": total / last.day})
    return pd.DataFrame(rows, columns=["month", "promo_discount"])


#: Multiplicative what-ifs that can be applied to measured governed totals without any fitted response.
#: Each maps the shocked metric to the outcome it is sized on and the measured inputs that outcome needs.
SHOCK_OUTCOMES = {
    "freight_value": ("freight_value", ("freight_value",)),
    "revenue": ("revenue", ("revenue",)),
    "gmv": ("gmv", ("gmv",)),
    "aov": ("revenue", ("revenue",)),
    "order_count": ("revenue", ("revenue",)),
    "item_count": ("gmv", ("gmv",)),
    "cancellation_rate": ("revenue", ("revenue", "cancellation_rate", "order_count", "aov")),
}


def shock_measurements(totals: dict[str, float], shocks: list[tuple[str, float]]) -> tuple[str, pd.DataFrame]:
    """Baseline and shocked value of the outcome, from measured window totals and stated multipliers.

    Revenue = orders x AOV, so order-count and AOV multipliers compose by product on revenue (orders or
    AOV held fixed otherwise). A cancellation-rate multiplier ``k`` recovers ``(1 - k)`` of the cancelled
    orders at the measured AOV - an upper bound, since a recovered order need not be an average one.
    Products and sums of measured inputs only; nothing is estimated here (SAFE-8).
    """
    outcomes = {SHOCK_OUTCOMES[target][0] for target, _ in shocks}
    if len(outcomes) != 1:
        raise ValueError("every shock must size the same outcome")
    outcome = outcomes.pop()
    baseline = float(totals[outcome])
    current = baseline
    for target, multiplier in shocks:
        if target == "cancellation_rate":
            cancelled = totals["cancellation_rate"] * totals["order_count"]
            current += (1.0 - multiplier) * cancelled * totals["aov"]
        else:
            current *= multiplier
    return outcome, pd.DataFrame({"baseline": [baseline], "current": [current]})


def category_sales(inventory: pd.DataFrame, list_price: pd.DataFrame, discount: pd.DataFrame) -> pd.DataFrame:
    """Category-day panel: units sold and effective price = list price x (1 - discount)."""
    panel = inventory[["date", "category", "units_sold", "stockout_flag"]].copy()
    panel["date"] = panel["date"].astype(str).str[:10]
    panel = panel.merge(list_price, on=["date", "category"], how="inner").merge(discount, on=["date", "category"], how="left")
    panel["discount_pct"] = panel["discount_pct"].fillna(0.0)
    panel["price"] = panel["list_price"] * (1.0 - panel["discount_pct"] / 100.0)
    panel = panel.rename(columns={"units_sold": "quantity"})
    return panel.sort_values(["date", "category"], kind="mergesort").reset_index(drop=True)


def elasticity_panel(sales: pd.DataFrame, competitor: pd.DataFrame | None = None, *, grain: str = "month") -> dict[str, pd.DataFrame]:
    """Category-period panel for the log-log fit, with two-way fixed effects removed.

    Units are the mean daily units on in-stock days (a stockout censors
    demand). Log price, log units, log competitor price and the discount are
    each demeaned by category and by period (the within transformation), so
    the existing pooled OLS estimates the within-category elasticity net of
    common trend and seasonality. Values are passed back as positive levels
    (``exp`` of the demeaned logs) because the estimator takes logs itself.

    The competitor control is the competitor price *relative to our
    category's average price over the window*, not relative to our current
    price. Measured against our current price, the control is almost exactly
    minus our own log price whenever competitor prices move little, which
    makes the two regressors collinear and the elasticity unidentified. The
    estimator's ``log(competitor / price)`` term therefore receives the
    demeaned log competitor price.
    """
    rows = sales[sales["stockout_flag"] == 0].copy()
    rows["period"] = rows["date"].astype(str).str[: 7 if grain == "month" else 10]
    grouped = rows.groupby(["category", "period"], as_index=False).agg(
        units=("quantity", "mean"), list_price=("list_price", "mean"), discount=("discount_pct", "mean")
    )
    if competitor is not None and not competitor.empty:
        comp = competitor.copy()
        comp["period"] = comp["date"].astype(str).str[: 7 if grain == "month" else 10]
        comp = comp.groupby(["category", "period"], as_index=False)["competitor_price"].mean()
        grouped = grouped.merge(comp, on=["category", "period"], how="left")
        grouped["competitor_price"] = grouped["competitor_price"].fillna(grouped["list_price"])
    else:
        grouped["competitor_price"] = grouped["list_price"]
    grouped = grouped[(grouped["units"] > 0) & (grouped["list_price"] > 0) & (grouped["competitor_price"] > 0)]
    for column, source in (("lp", "list_price"), ("lu", "units"), ("lc", "competitor_price"), ("d", "discount")):
        values = np.log(grouped[source]) if column != "d" else grouped[source].astype(float)
        grouped[column] = (
            values
            - values.groupby(grouped["category"]).transform("mean")
            - values.groupby(grouped["period"]).transform("mean")
            + values.mean()
        )
    keys = grouped["category"] + "|" + grouped["period"]
    date = grouped["period"] + ("-01" if grain == "month" else "")
    price = pd.DataFrame({"date": date, "product_id": keys, "effective_price": np.exp(grouped["lp"]),
                          "promotion_pct": grouped["d"], "product_category": grouped["category"]})
    comp = pd.DataFrame({"date": date, "product_id": keys, "competitor_price": np.exp(grouped["lc"] + grouped["lp"])})
    demand = pd.DataFrame({"date": date, "product_id": keys, "units_sold": np.exp(grouped["lu"])})
    return {"price_history": price.reset_index(drop=True), "competitor_prices": comp.reset_index(drop=True),
            "demand": demand.reset_index(drop=True)}


def competitor_by_category(competitor_prices: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    rows = competitor_prices.merge(products[["product_id", "product_category_name"]], on="product_id", how="inner")
    rows = rows.rename(columns={"product_category_name": "category", "price": "competitor_price"})
    return rows[["date", "category", "competitor_price"]]


def as_table(frame: pd.DataFrame, prefix: str, *, roles: dict | None = None) -> TableRef:
    return table_from_frame(frame, query_id=derived_query_id(prefix, frame.to_dict("list")), roles=roles or {})


def frame(table: TableRef) -> pd.DataFrame:
    return frame_from_table(table)


__all__ = [
    "SHOCK_OUTCOMES",
    "as_table",
    "category_sales",
    "competitor_by_category",
    "daily_discount",
    "daily_list_price",
    "elasticity_panel",
    "frame",
    "monthly_promotion_intensity",
    "shock_measurements",
]
