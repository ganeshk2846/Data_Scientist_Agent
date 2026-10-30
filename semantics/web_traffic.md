# Table: web_traffic

- **Data Layer:** Synthetic
- **Grain:** channel_day_state
- **Primary / Composite Key:** date, channel, customer_state
- **Synthetic Flag:** True

## Description
Synthetic web session volume, conversion rate, bounce rate, and funnel drop-offs.

## Caveats & Usage Rules
- Governed joins must match approved keys (date, channel, customer_state).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
