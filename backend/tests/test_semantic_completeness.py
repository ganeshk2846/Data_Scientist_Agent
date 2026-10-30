"""Tests for completeness metadata and rules (V2-DATA-1, V2-DATA-3)."""

from semantic.completeness import (
    get_completeness_caveats,
    is_period_complete,
    last_complete_period,
)


def test_last_complete_period_per_grain():
    """V2-DATA-1: 2018-08 is the last complete month on the Olist snapshot."""
    assert last_complete_period("revenue", "month") == "2018-08"
    assert last_complete_period("order_count", "month") == "2018-08"
    assert last_complete_period("gmv", "quarter") == "2018-Q2"
    assert last_complete_period("revenue", "year") == "2017"


def test_truncated_periods_flagged_incomplete():
    """V2-DATA-1: 2018-09 (16 orders), 2018-10 (4 orders), and 2016-09 are incomplete."""
    assert not is_period_complete("2018-09", "month")
    assert not is_period_complete("2018-10", "month")
    assert not is_period_complete("2016-09", "month")

    # Historical complete periods
    assert is_period_complete("2017-05", "month")
    assert is_period_complete("2018-08", "month")
    assert is_period_complete("2018-01", "month")


def test_caveat_generation_for_incomplete_periods():
    """V2-DATA-3: Descriptive answers spanning incomplete periods must include caveats."""
    caveats = get_completeness_caveats(["2018-07", "2018-08", "2018-09"], grain="month")
    assert len(caveats) == 1
    assert "2018-09 is truncated in the dataset with only 16 orders" in caveats[0]

    # No caveats for fully complete window
    clean_caveats = get_completeness_caveats(
        ["2018-05", "2018-06", "2018-07"], grain="month"
    )
    assert len(clean_caveats) == 0
