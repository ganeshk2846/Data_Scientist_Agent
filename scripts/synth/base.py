"""Base (un-planted) synthetic tables, keyed to real Olist values.

Each builder is pure: a :class:`SourceContext`, a seeded generator and the
calendar in, a DataFrame out. The planted effects are applied afterwards by
``plants/``, so the difference between a base frame and its planted version
is exactly the effect, and is measured into the manifest.

Shared structural truths, recorded in ``SYNTHETIC_GROUND_TRUTH.md`` through
the E5 plant:

* Category demand (``inventory_daily.units_sold``) responds to the category
  list-price index with a constant elasticity of ``TRUE_ELASTICITY``.
* Competitor prices follow their own random walk, independent of our prices.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .context import WINDOW_END, WINDOW_START, SourceContext

CHANNELS = ("paid_search", "social", "display", "email", "affiliate")
CHANNEL_WEIGHT = np.array([0.40, 0.25, 0.15, 0.10, 0.10])
CARRIERS = ("correios", "jadlog", "loggi", "total_express")
COMPETITORS = ("competitor_a", "competitor_b")
SEGMENTS = ("one_time", "repeat", "high_value", "at_risk")
RETURN_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind", "late_delivery")
RETURN_REASON_P = np.array([0.30, 0.15, 0.25, 0.25, 0.05])
TRUE_ELASTICITY = -1.5
BASE_RETURN_RATE = 0.03

REGION_OF = {
    **dict.fromkeys(("SP",), "SP"),
    **dict.fromkeys(("RJ", "MG", "ES"), "SE"),
    **dict.fromkeys(("PR", "SC", "RS"), "S"),
    **dict.fromkeys(("DF", "GO", "MT", "MS"), "CO"),
    **dict.fromkeys(("BA", "PE", "CE", "MA", "PB", "PI", "RN", "AL", "SE"), "NE"),
    **dict.fromkeys(("PA", "AM", "AC", "AP", "RR", "RO", "TO"), "N"),
}
PROMISED_DAYS = {"SP": 6, "SE": 9, "S": 11, "CO": 13, "NE": 17, "N": 21}
FREIGHT_BASE = {"SP": 15.0, "SE": 19.0, "S": 21.0, "CO": 24.0, "NE": 28.0, "N": 33.0}


def calendar() -> pd.DatetimeIndex:
    return pd.date_range(WINDOW_START, WINDOW_END, freq="D")


def growth_trend(dates: pd.DatetimeIndex) -> np.ndarray:
    """A smooth ramp from 0.35 to 1.0 centred on mid-2017."""
    t = (dates - pd.Timestamp("2017-06-01")).days.to_numpy() / 120.0
    return 0.35 + 0.65 / (1.0 + np.exp(-t))


def weekday_factor(dates: pd.DatetimeIndex) -> np.ndarray:
    return np.array([1.06, 1.08, 1.05, 1.02, 0.98, 0.88, 0.93])[dates.dayofweek.to_numpy()]


def _iso(dates) -> np.ndarray:
    return pd.DatetimeIndex(dates).strftime("%Y-%m-%d").to_numpy()


def _grid(**levels) -> pd.DataFrame:
    index = pd.MultiIndex.from_product(list(levels.values()), names=list(levels))
    return index.to_frame(index=False)


# --------------------------------------------------------------------------- #


def marketing_spend(ctx: SourceContext, rng: np.random.Generator) -> pd.DataFrame:
    dates = calendar()
    frame = _grid(date=dates, channel=list(CHANNELS), category=ctx.category_names)
    day = np.repeat(np.arange(len(dates)), len(CHANNELS) * len(ctx.category_names))
    channel_w = np.tile(np.repeat(CHANNEL_WEIGHT, len(ctx.category_names)), len(dates))
    cat_share = ctx.categories["share"].to_numpy()
    cat_w = np.tile(cat_share, len(dates) * len(CHANNELS))
    level = growth_trend(dates)[day] * weekday_factor(dates)[day]
    noise = rng.lognormal(0.0, 0.15, size=len(frame))
    frame["spend"] = np.round(25000.0 * channel_w * cat_w * level * noise, 2)
    frame["date"] = _iso(frame["date"])
    return frame


def promotions(ctx: SourceContext, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for month in pd.period_range(WINDOW_START, WINDOW_END, freq="M"):
        for _ in range(int(rng.poisson(3))):
            start = month.start_time + pd.Timedelta(days=int(rng.integers(0, month.days_in_month)))
            end = min(start + pd.Timedelta(days=int(rng.integers(2, 10))), WINDOW_END)
            rows.append((
                ctx.category_names[int(rng.integers(0, len(ctx.category_names)))],
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
                float(rng.choice([5.0, 10.0, 15.0])),
            ))
    frame = pd.DataFrame(rows, columns=["category", "start_date", "end_date", "discount_pct"])
    frame = frame.sort_values(["start_date", "category"], kind="mergesort").reset_index(drop=True)
    frame.insert(0, "promo_id", [f"P{i + 1:04d}" for i in range(len(frame))])
    return frame


def category_price_steps(ctx: SourceContext, rng: np.random.Generator) -> pd.DataFrame:
    """Base list-price repricing steps per category: (category, date, multiplier)."""
    rows = []
    span = (WINDOW_END - WINDOW_START).days
    for category in ctx.category_names:
        for _ in range(int(rng.integers(3, 7))):
            day = WINDOW_START + pd.Timedelta(days=int(rng.integers(30, span)))
            rows.append((category, day.strftime("%Y-%m-%d"), float(1.0 + rng.choice([-1, 1]) * rng.uniform(0.01, 0.06))))
    return pd.DataFrame(rows, columns=["category", "date", "multiplier"]).sort_values(
        ["category", "date"], kind="mergesort"
    ).reset_index(drop=True)


def price_history(ctx: SourceContext, steps: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """One row per product per list-price change; unit_cost constant per product."""
    products = ctx.products.copy()
    products["category"] = products["category"].fillna("")
    products["unit_cost"] = np.round(products["base_price"] * rng.uniform(0.45, 0.70, size=len(products)), 2)
    first = products[["product_id", "base_price", "unit_cost"]].assign(date=WINDOW_START.strftime("%Y-%m-%d"))
    first = first.rename(columns={"base_price": "price"})
    frames = [first[["product_id", "date", "price", "unit_cost"]]]
    cumulative = steps.copy()
    cumulative["index"] = cumulative.groupby("category")["multiplier"].cumprod()
    merged = products.merge(cumulative, on="category", how="inner")
    if not merged.empty:
        merged["price"] = merged["base_price"] * merged["index"]
        frames.append(merged[["product_id", "date", "price", "unit_cost"]])
    frame = pd.concat(frames, ignore_index=True)
    frame["price"] = np.round(frame["price"], 2)
    return frame.sort_values(["product_id", "date"], kind="mergesort").reset_index(drop=True)


def category_price_index(ctx: SourceContext, steps: pd.DataFrame) -> pd.DataFrame:
    """Daily list-price index per category (1.0 at the window start)."""
    dates = calendar()
    frame = _grid(date=dates, category=ctx.category_names)
    frame["date"] = _iso(frame["date"])
    frame["multiplier"] = 1.0
    frame = frame.merge(steps, on=["date", "category"], how="left", suffixes=("", "_step"))
    frame["multiplier"] = frame["multiplier_step"].fillna(1.0)
    frame["price_index"] = frame.groupby("category")["multiplier"].cumprod()
    return frame[["date", "category", "price_index"]]


def inventory_demand(ctx: SourceContext, price_index: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Category-day demand before stock limits; stock is simulated last."""
    dates = calendar()
    days = len(dates)
    frame = price_index.copy()
    per_day = (ctx.categories.set_index("category")["items"] / days).reindex(ctx.category_names)
    lam = per_day.to_numpy()[np.tile(np.arange(len(ctx.category_names)), days)]
    day = np.repeat(np.arange(days), len(ctx.category_names))
    level = growth_trend(dates)[day] * weekday_factor(dates)[day] * 2.0
    frame["expected_demand"] = lam * level * frame["price_index"].to_numpy() ** TRUE_ELASTICITY
    frame["demand_noise"] = rng.gamma(20.0, 1.0 / 20.0, size=len(frame))
    frame["forced_out"] = 0
    return frame


def finalize_inventory(frame: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Simulate stock: reorder to 30 days of cover when under 7, 4-day lead time."""
    frame = frame.sort_values(["category", "date"], kind="mergesort").reset_index(drop=True)
    demand = rng.poisson(np.maximum(frame["expected_demand"] * frame["demand_noise"], 0.0))
    sold = np.zeros(len(frame), dtype=np.int64)
    stock = np.zeros(len(frame), dtype=np.int64)
    for _, rows in frame.groupby("category", sort=False).indices.items():
        expected = frame["expected_demand"].to_numpy()[rows]
        forced = frame["forced_out"].to_numpy()[rows]
        cover = max(float(np.mean(expected)), 0.2)
        on_hand = int(np.ceil(20 * cover)) + 1
        pipeline: list[tuple[int, int]] = []
        for step, row in enumerate(rows):
            on_hand += sum(qty for due, qty in pipeline if due == step)
            pipeline = [(due, qty) for due, qty in pipeline if due > step]
            if forced[step]:
                on_hand = 0
                pipeline = []
            units = min(int(demand[row]), on_hand)
            on_hand -= units
            sold[row], stock[row] = units, on_hand
            if not forced[step] and on_hand < 7 * cover and not pipeline:
                pipeline.append((step + 4, int(np.ceil(30 * cover))))
    out = frame[["date", "category"]].copy()
    out["stock_on_hand"] = stock
    out["units_sold"] = sold
    out["stockout_flag"] = (stock == 0).astype(np.int64)
    return out


def web_traffic(ctx: SourceContext, rng: np.random.Generator) -> pd.DataFrame:
    dates = calendar()
    frame = _grid(date=dates, state=ctx.state_codes)
    day = np.repeat(np.arange(len(dates)), len(ctx.state_codes))
    share = np.tile(ctx.states["share"].to_numpy(), len(dates))
    level = growth_trend(dates)[day] * weekday_factor(dates)[day]
    frame["sessions"] = np.round(60000.0 * share * level * rng.lognormal(0.0, 0.08, size=len(frame))).astype(np.int64)
    frame["conversion_rate"] = np.clip(rng.normal(0.021, 0.0012, size=len(frame)), 0.005, 0.2)
    frame["boleto_share"] = np.clip(rng.normal(0.19, 0.01, size=len(frame)), 0.0, 1.0)
    frame["date"] = _iso(frame["date"])
    return frame


def competitor_prices(ctx: SourceContext, rng: np.random.Generator, top_n: int = 300) -> pd.DataFrame:
    top = ctx.products[ctx.products["items"] > 0].sort_values(
        ["items", "product_id"], ascending=[False, True], kind="mergesort"
    ).head(top_n)
    weeks = pd.date_range(WINDOW_START, WINDOW_END, freq="W-MON")
    frames = []
    for competitor in COMPETITORS:
        offset = rng.normal(0.0, 0.06, size=len(top))
        walk = np.cumsum(rng.normal(0.0, 0.01, size=(len(weeks), len(top))), axis=0)
        price = top["base_price"].to_numpy()[None, :] * (1.0 + offset)[None, :] * np.exp(walk)
        frames.append(pd.DataFrame({
            "product_id": np.tile(top["product_id"].to_numpy(), len(weeks)),
            "date": np.repeat(_iso(weeks), len(top)),
            "competitor": competitor,
            "price": np.round(price.ravel(), 2),
        }))
    frame = pd.concat(frames, ignore_index=True)
    return frame.sort_values(["product_id", "date", "competitor"], kind="mergesort").reset_index(drop=True)


def customer_segments(ctx: SourceContext, rng: np.random.Generator) -> pd.DataFrame:
    customers = ctx.customers
    high = customers["total"].quantile(0.90)
    segment = np.where(customers["orders"] >= 2, "repeat", "one_time")
    segment = np.where(customers["total"] >= high, "high_value", segment)
    stale = customers["last_purchase"] < pd.Timestamp("2018-03-01")
    at_risk = (segment == "repeat") & stale.to_numpy() & (rng.random(len(customers)) < 0.5)
    segment = np.where(at_risk, "at_risk", segment)
    bands = pd.qcut(customers["total"].rank(method="first"), 3, labels=["low", "mid", "high"])
    channel = rng.choice(list(CHANNELS) + ["organic"], size=len(customers), p=[0.25, 0.15, 0.08, 0.07, 0.05, 0.40])
    assigned = customers["first_purchase"].clip(lower=WINDOW_START, upper=WINDOW_END)
    return pd.DataFrame({
        "customer_unique_id": customers["customer_unique_id"],
        "segment": segment,
        "ltv_band": bands.astype(str),
        "acquisition_channel": channel,
        "assigned_at": _iso(assigned),
    })


def regional_targets(ctx: SourceContext, rng: np.random.Generator) -> pd.DataFrame:
    from .context import COMPLETE_MONTHS

    months = pd.period_range(WINDOW_START, WINDOW_END, freq="M")
    revenue = ctx.state_month_revenue
    complete = revenue[revenue["month"].isin([str(m) for m in COMPLETE_MONTHS])]
    state_mean = complete.groupby("state")["revenue"].mean().reindex(ctx.state_codes).fillna(0.0)
    plan = growth_trend(pd.DatetimeIndex([m.start_time for m in months]))
    plan = plan / plan[[str(m) in {str(c) for c in COMPLETE_MONTHS} for m in months]].mean()
    frame = _grid(state=ctx.state_codes, month=[str(m) for m in months])
    month_pos = np.tile(np.arange(len(months)), len(ctx.state_codes))
    base = np.repeat(state_mean.to_numpy(), len(months))
    frame["revenue_target"] = np.round(base * plan[month_pos] * 1.10 * rng.normal(1.0, 0.02, size=len(frame)), 2)
    return frame


def returns(ctx: SourceContext, rng: np.random.Generator) -> pd.DataFrame:
    items = ctx.items[ctx.items["status"] == "delivered"].reset_index(drop=True)
    picked = items[rng.random(len(items)) < BASE_RETURN_RATE].copy()
    anchor = picked["delivered"].fillna(picked["purchase"] + pd.Timedelta(days=10))
    picked["return_date"] = anchor.dt.normalize() + pd.to_timedelta(rng.integers(2, 31, size=len(picked)), unit="D")
    picked["reason"] = rng.choice(RETURN_REASONS, size=len(picked), p=RETURN_REASON_P)
    picked = picked[picked["return_date"] <= WINDOW_END]
    return pd.DataFrame({
        "order_id": picked["order_id"],
        "order_item_id": picked["order_item_id"].astype(np.int64),
        "return_date": _iso(picked["return_date"]),
        "reason": picked["reason"],
        "refund_value": np.round(picked["price"], 2),
    }).reset_index(drop=True)


def delivery_sla(ctx: SourceContext, rng: np.random.Generator) -> pd.DataFrame:
    dates = calendar()
    frame = _grid(date=dates, carrier=list(CARRIERS), state=ctx.state_codes)
    region = frame["state"].map(REGION_OF).fillna("N")
    promised = region.map(PROMISED_DAYS).to_numpy()
    frame["promised_days"] = promised.astype(np.int64)
    actual = np.maximum(1, np.round(promised * rng.normal(0.85, 0.12, size=len(frame))))
    frame["actual_days"] = actual.astype(np.int64)
    frame["sla_breach_flag"] = (frame["actual_days"] > frame["promised_days"]).astype(np.int64)
    frame["freight_cost"] = np.round(region.map(FREIGHT_BASE).to_numpy() * rng.normal(1.0, 0.05, size=len(frame)), 2)
    frame["date"] = _iso(frame["date"])
    return frame


__all__ = [
    "CARRIERS",
    "CHANNELS",
    "TRUE_ELASTICITY",
    "calendar",
    "category_price_index",
    "category_price_steps",
    "competitor_prices",
    "customer_segments",
    "delivery_sla",
    "finalize_inventory",
    "inventory_demand",
    "marketing_spend",
    "price_history",
    "promotions",
    "regional_targets",
    "returns",
    "web_traffic",
]
