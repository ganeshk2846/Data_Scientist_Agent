# Table: regional_targets

- **Data Layer:** Synthetic
- **Grain:** state_month_metric
- **Primary / Composite Key:** month, customer_state, metric_id
- **Synthetic Flag:** True

## Description
Synthetic commercial quotas setting regional monthly revenue and order volume targets.

## Caveats & Usage Rules
- Governed joins must match approved keys (month, customer_state, metric_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
