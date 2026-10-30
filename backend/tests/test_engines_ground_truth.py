"""Each engine recovers the planted effects in SYNTHETIC_GROUND_TRUTH.md (DATA-4, ANA-5).

Runs on the seeded V2 build (``v2_build``). Expected sizes come from the
generator's manifest - the same facts the Markdown answer key renders - and
are read only here, by scoring code; no engine ever sees them (DATA-9).
Every confounder and the negative control are checked too: recovering a
planted effect while naming its confounder as the driver is a failure.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from engines import execute, prep
from engines.base import EngineData

PROMOTED = ("cama_mesa_banho", "beleza_saude", "esporte_lazer", "moveis_decoracao", "informatica_acessorios",
            "utilidades_domesticas", "relogios_presentes")


@pytest.fixture(scope="module")
def truth(v2_build):
    return {fact.fact_id: fact for fact in v2_build["generation"].manifest.facts}


@pytest.fixture(scope="module")
def db(v2_build):
    connection = sqlite3.connect(v2_build["db"])
    yield lambda sql: pd.read_sql(sql, connection)
    connection.close()


@pytest.fixture(scope="module")
def sales(db):
    inventory = db("SELECT * FROM inventory_daily")
    products = db("SELECT product_id, product_category_name FROM products")
    list_price = prep.daily_list_price(db("SELECT product_id, date, price FROM price_history"), products, inventory["date"])
    discount = prep.daily_discount(db("SELECT * FROM promotions"), inventory["date"], inventory["category"])
    return {
        "sales": prep.category_sales(inventory, list_price, discount),
        "competitor": prep.competitor_by_category(db("SELECT * FROM competitor_prices"), products),
    }


def _data(tables, sources, seed=11):
    return EngineData(tables=tables, source_tables=sources, seed=seed, run_id="RUN-GROUND-TRUTH")


def _ranked(run):
    return run.report.table("ranked_drivers").rows


# --------------------------------------------------------------------------- #
# Descriptive - E1
# --------------------------------------------------------------------------- #


def test_descriptive_finds_the_e1_paid_search_cut_as_the_largest_channel_drop(db, truth):
    spend = db("SELECT date, channel, spend FROM marketing_spend")
    run = execute("descriptive", {
        "operation": "aggregate", "measure": "spend", "dimensions": ("channel",), "period_column": "date",
        "start": "2018-03-01", "end": "2018-06-01", "comparison_start": "2017-12-01", "comparison_end": "2018-03-01",
        "order": "asc", "unit": "R$",
    }, _data({"spend": prep.as_table(spend, "GT-SPEND", roles={"date": "time"})}, ("marketing_spend",)))
    assert run.result.tool == "sql" and run.result.provenance.data_layer == "synthetic"
    rows = {row[0]: row for row in run.result.rows.rows}
    assert run.result.rows.rows[0][0] == "paid_search"
    others = [rows[name][4] for name in rows if name != "paid_search"]
    relative = (1 + rows["paid_search"][4] / 100) / (1 + sum(others) / len(others) / 100) - 1
    assert relative == pytest.approx(truth["E1-spend"].expected_pct, abs=0.05)


# --------------------------------------------------------------------------- #
# Diagnostic - E1, E2, E3, E4
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def e1_diagnosis(db):
    sessions = db("SELECT date, state, sessions AS value FROM web_traffic")
    spend = db("SELECT date, channel, category, spend FROM marketing_spend")
    channels = ("paid_search", "social", "display", "email", "affiliate")
    drivers = [{"name": name, "table": "marketing_spend", "value": "spend", "where": {"channel": (name,)},
                "relative_to_rest": True, "expected_sign": 1} for name in channels]
    drivers.append({"name": "social_top3_share", "table": "marketing_spend", "value": "spend",
                    "where": {"category": ("cama_mesa_banho", "beleza_saude", "esporte_lazer")}, "share_of": {"channel": ("social",)}})
    return execute("diagnostic", {
        "metric": "sessions", "current_period": {"start": "2018-03-15", "end": "2018-06-15"},
        "comparison_period": {"start": "2017-12-01", "end": "2018-03-01"},
        "target_where": {"state": ("SP", "RJ")}, "target_relative_to_rest": True, "grain": "week", "max_lag": 4,
        "drivers": drivers, "specificity": {"dimension": "state", "treated": ("SP", "RJ"), "date": "date"},
    }, _data({"contrib": prep.as_table(sessions, "GT-SESSIONS", roles={"date": "time"}),
              "marketing_spend": prep.as_table(spend, "GT-SPEND", roles={"date": "time"})}, ("web_traffic", "marketing_spend")))


def test_diagnostic_e1_names_paid_search_at_the_planted_lag_and_rejects_the_mix_confounder(e1_diagnosis, truth):
    correlations = [row for row in _ranked(e1_diagnosis) if row[1] == "correlation"]
    top = correlations[0]
    assert top[0] == truth["E1-spend"].dimension_values[0] == "paid_search"
    assert top[7] == 2 and top[2] > 0.5
    assert 1 <= top[9] <= 3, "the 14-day lag is two weekly periods"
    confounder = next(row for row in correlations if row[0] == "social_top3_share")
    assert truth["E1-mix-confounder"].is_cause is False
    assert confounder[7] == 1 and "reallocation" in confounder[11]
    assert all(row[7] < 2 for row in _ranked(e1_diagnosis) if row[0] == "social_top3_share")


def test_diagnostic_e1_locates_the_session_drop_in_sp_and_rj(e1_diagnosis, truth):
    did = next(row for row in _ranked(e1_diagnosis) if row[1] == "difference_in_differences")
    assert did[7] == 3 and did[2] < 0
    assert did[10] == pytest.approx(truth["E1-sessions"].expected_pct * 100, abs=8.0)
    assert "SP" in did[0] and "RJ" in did[0]


def test_diagnostic_e2_attributes_the_dip_to_stockouts_not_the_seasonal_peak(sales, truth):
    frame = sales["sales"][["date", "category", "quantity", "stockout_flag"]]
    affected = truth["E2-stockout"].dimension_values
    run = execute("diagnostic", {
        "metric": "units_sold", "current_period": {"start": "2017-11-20", "end": "2017-12-11"},
        "comparison_period": {"start": "2017-10-20", "end": "2017-11-20"}, "dimensions": ("category",), "grain": "day",
        "specificity": {"dimension": "category", "treated": affected, "date": "date", "measures": ("quantity", "stockout_flag")},
    }, _data({"contrib": prep.as_table(frame.rename(columns={"quantity": "value"}).assign(quantity=frame["quantity"]), "GT-UNITS",
                                       roles={"date": "time", "category": "dimension"})}, ("inventory_daily",)))
    did = {row[0]: row for row in _ranked(run) if row[1] == "difference_in_differences"}
    units = next(row for name, row in did.items() if "(quantity)" in name)
    stockouts = next(row for name, row in did.items() if "(stockout_flag)" in name)
    assert units[7] == 3 and units[2] < 0, "units fall specifically in the stocked-out categories"
    assert stockouts[7] == 3 and stockouts[2] > 0.8, "the stockout flag is set specifically there"
    # The seasonal peak lifts every category, so it cannot be specific to the affected three.
    assert truth["E2-peak-confounder"].dimension_values == ("all",)


def test_diagnostic_e3_explains_aov_by_price_not_volume_and_keeps_boleto_at_correlation(sales, truth, db):
    frame = sales["sales"]
    contrib = frame.assign(numerator=frame["price"] * frame["quantity"], denominator=frame["quantity"])[
        ["date", "category", "numerator", "denominator"]]
    boleto = db("SELECT date, AVG(boleto_share) AS boleto_share FROM web_traffic GROUP BY date")
    run = execute("diagnostic", {
        "metric": "average_selling_price", "aggregation": "ratio", "dimensions": ("category",), "grain": "week",
        "current_period": {"start": "2018-01-01", "end": "2018-03-01"}, "comparison_period": {"start": "2017-09-01", "end": "2017-11-01"},
        "pvm": {"table": "sales", "period": "date", "dimension": "category"},
        "specificity": {"dimension": "category", "treated": PROMOTED, "table": "sales", "date": "date", "measures": ("price",)},
        "drivers": ({"name": "boleto_share", "table": "web_traffic", "value": "boleto_share", "agg": "mean"},),
    }, _data({"contrib": prep.as_table(contrib, "GT-ASP", roles={"date": "time"}),
              "sales": prep.as_table(frame, "GT-SALES", roles={"date": "time"}),
              "web_traffic": prep.as_table(boleto, "GT-BOLETO", roles={"date": "time"})},
             ("inventory_daily", "price_history", "promotions", "web_traffic")))
    report = run.report
    assert report.number("asp_change") < 0
    assert report.number("asp_rate_effect") < 0
    assert abs(report.number("asp_rate_effect")) > abs(report.number("asp_mix_effect")), "AOV falls for a price reason"
    assert report.number("asp_rate_effect") + report.number("asp_mix_effect") == pytest.approx(report.number("asp_change"))
    assert report.number("volume_effect") > 0 and report.number("price_effect") < 0, "orders up, price down"
    assert report.number("units_change_pct") > 0
    promo = next(row for row in _ranked(run) if row[1] == "difference_in_differences")
    assert promo[7] == 3
    assert promo[10] == pytest.approx(truth["E3-promo"].expected_pct * 100, abs=3.0)
    assert truth["E3-boleto-confounder"].is_cause is False
    assert max(row[7] for row in _ranked(run) if row[0] == "boleto_share") <= 2, "boleto only co-moves"


def test_diagnostic_e4_isolates_jadlog_and_does_not_blame_freight(db, truth):
    south = truth["E4-late-returns"].dimension_values
    rows = db("SELECT date, carrier, state, sla_breach_flag AS numerator, 1 AS denominator, "
              "actual_days - promised_days AS delay_days, freight_cost FROM delivery_sla "
              f"WHERE state IN ({', '.join(repr(state) for state in south)})")
    run = execute("diagnostic", {
        "metric": "sla_breach_rate", "aggregation": "ratio", "dimensions": ("carrier", "state"), "grain": "day",
        "current_period": {"start": "2018-06-01", "end": "2018-07-01"}, "comparison_period": {"start": "2018-05-01", "end": "2018-06-01"},
        "specificity": {"dimension": "carrier", "treated": truth["E4-delay"].dimension_values, "date": "date",
                        "measures": ("delay_days", "freight_cost")},
    }, _data({"contrib": prep.as_table(rows, "GT-SLA", roles={"date": "time", "delay_days": "measure", "freight_cost": "measure"})},
             ("delivery_sla",)))
    did = {row[0]: row for row in _ranked(run) if row[1] == "difference_in_differences"}
    delay = next(row for name, row in did.items() if "(delay_days)" in name)
    freight = next(row for name, row in did.items() if "(freight_cost)" in name)
    assert delay[7] == 3 and delay[2] == pytest.approx(6.0, abs=1.0)
    assert truth["E4-freight-confounder"].is_cause is False and freight[7] < 3
    top_carrier = next(row for row in run.report.table("drill_down").rows if row[0] == "carrier")
    assert top_carrier[1] == "jadlog"


# --------------------------------------------------------------------------- #
# Impact - E1, E2
# --------------------------------------------------------------------------- #


def _periods(frame, column, windows):
    out = []
    for label, (start, end) in windows.items():
        part = frame[(frame["date"] >= start) & (frame["date"] < end)]
        out.append(pd.DataFrame({"period": label, "value": part[column].to_numpy()}))
    return pd.concat(out, ignore_index=True)


def test_impact_sizes_e1_sessions_against_peer_states(db, truth):
    sessions = db("SELECT date, state, SUM(sessions) AS sessions FROM web_traffic GROUP BY date, state")
    treated = truth["E1-sessions"].dimension_values
    windows = {"baseline": ("2017-12-01", "2018-03-01"), "current": ("2018-03-15", "2018-06-15")}
    daily = lambda frame: frame.groupby("date", as_index=False)["sessions"].sum()  # noqa: E731
    run = execute("impact", {"metric": "sessions", "unit": "sessions", "aggregation": "mean",
                             "current_period": "current", "baseline_period": "baseline", "peer_label": "other states"},
                  _data({"measurements": prep.as_table(_periods(daily(sessions[sessions.state.isin(treated)]), "sessions", windows), "GT-T"),
                         "peers": prep.as_table(_periods(daily(sessions[~sessions.state.isin(treated)]), "sessions", windows), "GT-P")},
                        ("web_traffic",)))
    result = run.result.analyst_output.result
    assert result.significant is True and result.delta < 0
    relative = (1 + result.delta_pct / 100) / (1 + run.report.number("peer_delta_pct") / 100) - 1
    assert relative == pytest.approx(truth["E1-sessions"].expected_pct, abs=0.04)


def test_impact_sizes_e2_units_at_minus_100_percent_while_peers_rise(sales, truth):
    frame = sales["sales"]
    affected = truth["E2-units"].dimension_values
    windows = {"baseline": ("2017-10-20", "2017-11-20"), "current": ("2017-11-20", "2017-12-11")}
    daily = lambda rows: rows.groupby("date", as_index=False)["quantity"].sum()  # noqa: E731
    run = execute("impact", {"metric": "units_sold", "unit": "units", "aggregation": "mean",
                             "current_period": "current", "baseline_period": "baseline"},
                  _data({"measurements": prep.as_table(_periods(daily(frame[frame.category.isin(affected)]), "quantity", windows), "GT-A"),
                         "peers": prep.as_table(_periods(daily(frame[~frame.category.isin(affected)]), "quantity", windows), "GT-U")},
                        ("inventory_daily",)))
    result = run.result.analyst_output.result
    assert result.delta_pct == pytest.approx(truth["E2-units"].expected_pct * 100, abs=0.5)
    assert result.significant is True
    assert run.report.number("peer_delta_pct") > 0, "the seasonal peak lifts the unaffected categories"


def test_anomaly_scan_flags_exactly_the_e2_stockout_weeks(sales, truth):
    frame = sales["sales"]
    affected = frame[frame.category.isin(truth["E2-units"].dimension_values)]
    series = affected.groupby("date", as_index=False)["quantity"].sum().rename(columns={"quantity": "value"})
    run = execute("impact", {"mode": "anomaly", "metric": "value", "grain": "week",
                             "scan_window": {"start": "2017-10-30", "end": "2018-01-29"}},
                  _data({"series": prep.as_table(series, "GT-SERIES", roles={"date": "time"})}, ("inventory_daily",)))
    flagged = [row[0] for row in run.report.table("anomalies").rows if row[5] == "unusual"]
    assert flagged == ["2017-11-20", "2017-11-27", "2017-12-04"]
    assert truth["E2-stockout"].period_start <= flagged[0] and flagged[-1] <= truth["E2-stockout"].period_end


# --------------------------------------------------------------------------- #
# Forecast - held-out actuals (no effect is planted for forecasting)
# --------------------------------------------------------------------------- #


def test_forecast_tracks_held_out_months_and_reports_both_backtests(sales):
    frame = sales["sales"].assign(month=sales["sales"]["date"].str[:7])
    monthly = frame.groupby("month", as_index=False)["quantity"].sum().rename(columns={"quantity": "value"})
    run = execute("forecast", {"metric": "units", "anchor": "2018-08", "question": "What will units be over the next 2 months?"},
                  _data({"series": prep.as_table(monthly[monthly.month <= "2018-08"], "GT-F", roles={"month": "time"})},
                        ("inventory_daily",)))
    points = run.result.analyst_output.result.points
    actual = dict(monthly[["month", "value"]].itertuples(index=False, name=None))
    assert [point.ds for point in points] == ["2018-09", "2018-10"]
    errors = [abs(point.yhat - actual[point.ds]) / actual[point.ds] for point in points]
    assert max(errors) < 0.15
    assert any(point.yhat_lower <= actual[point.ds] <= point.yhat_upper for point in points)
    assert run.report.number("backtest_mape") is not None and run.report.number("arima_backtest_mape") is not None


# --------------------------------------------------------------------------- #
# Scenario - E5
# --------------------------------------------------------------------------- #


def test_scenario_recovers_the_e5_elasticity_and_does_not_blame_competitors(sales, truth):
    run = execute("scenario", {"question": "What happens to revenue if we raise moveis_decoracao prices by 10%?"},
                  _data({"sales": prep.as_table(sales["sales"], "GT-SALES", roles={"date": "time"}),
                         "competitor": prep.as_table(sales["competitor"], "GT-COMP", roles={"date": "time"})},
                        ("inventory_daily", "price_history", "promotions", "competitor_prices", "products")))
    result = run.result.analyst_output.result
    planted = -1.5
    assert truth["E5-units"].expected_pct == pytest.approx(1.10 ** planted - 1, abs=1e-4)
    assert result.elasticity == pytest.approx(planted, abs=0.25)
    assert result.elasticity_interval[0] <= planted <= result.elasticity_interval[1]
    assert result.price_change_pct == pytest.approx(truth["E5-price"].expected_pct * 100)
    assert len(result.disclosures) >= 5 and result.synthetic_data
    assert truth["E5-competitor-control"].role == "negative_control"
    assert run.report.number("competitor_p_value") >= 0.05, "competitor pricing is not attributed the demand change"


# --------------------------------------------------------------------------- #
# Prescriptive - E4, E2
# --------------------------------------------------------------------------- #


def test_prescriptive_segments_group_the_e4_south_states(db, truth):
    states = db("SELECT state, AVG(actual_days - promised_days) AS delay_days, AVG(sla_breach_flag) AS breach_rate, "
                "AVG(freight_cost) AS freight FROM delivery_sla WHERE date >= '2018-06-01' AND date < '2018-07-01' GROUP BY state")
    run = execute("prescriptive", {"mode": "segments", "entity": "states", "key": "state", "n_clusters": 3},
                  _data({"states": prep.as_table(states, "GT-STATES", roles={"state": "key"})}, ("delivery_sla",), seed=4))
    members = dict(run.report.table("membership").rows)
    south = truth["E4-late-returns"].dimension_values
    labels = {members[state] for state in south}
    assert len(labels) == 1
    assert sorted(state for state, label in members.items() if label in labels) == sorted(south)


def test_prescriptive_reorder_restocks_the_e2_categories(db, sales, truth):
    snapshot = db("SELECT category, stock_on_hand FROM inventory_daily WHERE date = '2017-11-25'")
    history = sales["sales"]
    history = history[(history.date >= "2017-10-20") & (history.date < "2017-11-20") & (history.stockout_flag == 0)]
    demand = history.groupby("category", as_index=False).agg(daily=("quantity", "mean"), price=("price", "mean"))
    costs = db("SELECT p.product_category_name AS category, AVG(ph.unit_cost) AS unit_cost FROM price_history ph "
               "JOIN products p ON p.product_id = ph.product_id GROUP BY 1")
    items = snapshot.merge(demand, on="category").merge(costs, on="category")
    items = pd.DataFrame({"item": items.category, "forecast_demand": items.daily * 14, "stock_on_hand": items.stock_on_hand,
                          "unit_cost": items.unit_cost, "unit_margin": items.price - items.unit_cost})
    budget = float((items.unit_cost * (items.forecast_demand - items.stock_on_hand).clip(lower=0)).sum()) * 0.8
    run = execute("prescriptive", {"mode": "reorder", "budget": budget},
                  _data({"items": prep.as_table(items, "GT-ITEMS")}, ("inventory_daily", "price_history"), seed=4))
    plan = {row[0]: row for row in run.report.table("reorder_plan").rows}
    affected = truth["E2-stockout"].dimension_values
    assert all(items.set_index("item").loc[name, "stock_on_hand"] == 0 for name in affected)
    assert all(plan[name][1] > 0 for name in affected), "every stocked-out category is reordered"
    assert run.report.number("spend") <= budget + 1e-6
    assert run.result.analyst_output.result.actions[0].action_id == "optimized_reorder"
