# Analytical tables

**Layer:** derived. Rebuilt by `scripts/build_analytical_tables.py` from SQL and
the registered engines; never edited by hand. Each row carries `is_synthetic`
for the KPI it holds, so a reader labels **per row**, not per table (`AT-5`).
Every row carries `catalog_version`; a mismatch is a cache miss (`AT-2`).

| Table | Grain | Holds | Provenance |
| --- | --- | --- | --- |
| `kpi_daily` | kpi x day | `value`, `numerator`, `denominator` | `sql` |
| `analytical_series` | kpi x month x dimension value | `value`, `numerator`, `denominator`, `complete` | `sql` |
| `analytical_anomalies` | kpi x month x dimension value tested | `value`, `expected`, `delta`, `delta_pct`, `direction`, `score`, `flagged`, `correction` | `engine` (`python.anomaly`) |
| `analytical_forecasts` | kpi x dimension value x forecast month | `anchor_period`, `yhat`, `yhat_lower`, `yhat_upper`, `model`, `model_fallback_reason`, `mape` | `engine` (`python.forecast`) |
| `driver_contributions` | kpi x dimension value x month pair | `contribution`, `share`, interval, `grade`, `total_change` | `engine` (`python.driver`) |

## Caveats

- `dimension` is null for the total series.
- Ratio and mean KPIs keep `numerator` and `denominator`: re-aggregate those, never average `value`.
- Anomalies are tested only on complete months with at least 12 complete months of history, and `flagged` survives a Benjamini-Hochberg correction across every test in the table; `correction` names it.
- Forecasts are anchored on each KPI's **last complete month** and fitted only on its latest contiguous run of complete months. A null `mape` means *not backtested*, never zero.
- Driver contributions exist only for additive KPIs (`DRV-2`).
