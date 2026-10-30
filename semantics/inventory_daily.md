# Table: inventory_daily

- **Data Layer:** Synthetic
- **Grain:** product_day
- **Primary / Composite Key:** date, product_id
- **Synthetic Flag:** True

## Description
Synthetic stock level monitoring capturing units on hand, units sold, and stockout occurrences.

## Caveats & Usage Rules
- Governed joins must match approved keys (date, product_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
