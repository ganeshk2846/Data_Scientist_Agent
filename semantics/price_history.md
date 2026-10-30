# Table: price_history

- **Data Layer:** Synthetic
- **Grain:** product_day
- **Primary / Composite Key:** product_id, date
- **Synthetic Flag:** True

## Description
Synthetic daily product pricing records comparing list prices to effective discounted prices.

## Caveats & Usage Rules
- Governed joins must match approved keys (product_id, date).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
