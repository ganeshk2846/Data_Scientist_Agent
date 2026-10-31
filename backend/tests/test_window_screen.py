"""Diagnostic window screen, indicator priors and the promotion indicator (WHY, DRV-5, SAFE-8)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from engines.diagnostic import DiagnosticParams, window_screen
from engines.prep import monthly_promotion_intensity
from tools.registry import indicator_sign


def _monthly(values, start="2016-10"):
    labels = [str(period) for period in pd.period_range(start, periods=len(values), freq="M")]
    return pd.Series(values, index=labels, dtype=float)


def _params(current=("2018-04-01", "2018-05-01"), comparison=("2018-03-01", "2018-04-01"), max_lag=2):
    return DiagnosticParams(metric="revenue", grain="month", max_lag=max_lag,
                            current_period={"start": current[0], "end": current[1]},
                            comparison_period={"start": comparison[0], "end": comparison[1]})


def _noisy(count=23, seed=4, level=100.0, slope=1.0):
    rng = np.random.default_rng(seed)
    return level + np.arange(count) * slope + rng.normal(0.0, 1.5, count)


def test_a_cut_level_in_the_window_is_flagged_and_a_quiet_candidate_is_not():
    cut = _noisy(seed=1)
    cut[17:20] *= 0.6  # 2018-03..2018-05, the E1 shape
    quiet = _noisy(seed=2)
    result = {item["name"]: item for item in window_screen({"spend": _monthly(cut), "quiet": _monthly(quiet)}, _params(),
                                                           outcome_sign=-1.0, signs={"spend": 1, "quiet": 1})}
    assert result["spend"]["q"] < 0.05 and result["spend"]["z"] < 0
    assert result["spend"]["change_pct"] < -25
    assert result["spend"]["consistent"] is True
    assert result["quiet"]["q"] >= 0.05


def test_a_return_to_normal_after_an_abnormal_month_is_not_an_unusual_level():
    """The month after a promotion ends is a large change but a normal level."""
    series = _noisy(seed=3)
    series[15:17] *= 1.4  # 2018-01..2018-02 elevated, 2018-03 back to normal
    result = window_screen({"conversion": _monthly(series)}, _params(current=("2018-03-01", "2018-04-01"),
                                                                       comparison=("2018-02-01", "2018-03-01"), max_lag=0))
    assert result[0]["q"] >= 0.05


def test_the_screen_finds_the_lag_and_a_move_against_the_prior_is_not_consistent():
    series = _noisy(seed=5)
    series[17] *= 0.5  # only 2018-03, one period before the April window
    result = window_screen({"spend": _monthly(series)}, _params(), outcome_sign=1.0, signs={"spend": 1})
    assert result[0]["lag"] == 1 and result[0]["q"] < 0.05
    assert result[0]["consistent"] is False  # spend fell while the outcome rose


def test_a_candidate_without_a_prior_is_never_called_consistent():
    series = _noisy(seed=6)
    series[18] += 40
    result = window_screen({"boleto_share": _monthly(series)}, _params(), outcome_sign=-1.0, signs={})
    assert result[0]["q"] < 0.05 and result[0]["consistent"] is None


def test_too_little_history_tests_nothing():
    assert window_screen({"short": _monthly([1.0, 2.0, 3.0, 4.0, 5.0], start="2018-01")}, _params()) == []


def test_indicator_priors_follow_the_outcome_class():
    assert indicator_sign("spend_paid_search", "revenue") == 1
    assert indicator_sign("spend_paid_search", "aov") is None
    assert indicator_sign("promo_discount", "order_count") == 1
    assert indicator_sign("promo_discount", "aov") == -1
    assert indicator_sign("stockout_rate", "order_count") == -1
    assert indicator_sign("sla_breach_rate", "review_score") == -1
    assert indicator_sign("sla_breach_rate", "return_rate") == 1
    assert indicator_sign("boleto_share", "aov") is None
    assert indicator_sign("sessions", "sessions") is None


def test_promotion_intensity_weights_days_by_discount_and_is_zero_without_promotions():
    promotions = pd.DataFrame({"category": ["a", "b"], "start_date": ["2018-01-01", "2018-01-16"],
                               "end_date": ["2018-02-28", "2018-01-31"], "discount_pct": [20.0, 10.0]})
    frame = monthly_promotion_intensity(promotions, ["2017-12", "2018-01", "2018-02", "2018-03"]).set_index("month")
    assert frame.loc["2017-12", "promo_discount"] == 0.0
    assert frame.loc["2018-01", "promo_discount"] == (20.0 * 31 + 10.0 * 16) / 31
    assert frame.loc["2018-02", "promo_discount"] == 20.0
    assert frame.loc["2018-03", "promo_discount"] == 0.0


def test_the_live_why_path_names_the_planted_spend_cut_and_never_the_outcome_itself(v2_build):
    from pipeline_v2 import PipelineV2
    from service import build_runtime

    runtime = build_runtime(v2_build["db"], reasoning_client=False)
    try:
        pipeline = PipelineV2(guard=runtime.guard, catalog=runtime.catalog, manager=runtime.manager)
        sessions = pipeline.run("Why did web sessions drop in April 2018?", run_id="ws-1").envelope
        assert sessions.status == "answered"
        assert "paid search" in sessions.conclusion and "not evidence of a cause" in sessions.conclusion
        assert "co-moves with sessions" not in sessions.conclusion
        stockouts = pipeline.run("Why did the stockout rate spike in December 2017?", run_id="ws-2").envelope
        assert "co-moves with stockout rate" not in stockouts.conclusion
    finally:
        runtime.close()
