# Table: marketing_spend

- **Data Layer:** Synthetic
- **Grain:** channel_day_state
- **Primary / Composite Key:** date, channel, customer_state
- **Synthetic Flag:** True

## Description
Synthetic advertising investments across digital marketing channels (paid search, social, email).

## Caveats & Usage Rules
- Governed joins must match approved keys (date, channel, customer_state).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
