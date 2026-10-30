# Table: competitor_prices

- **Data Layer:** Synthetic
- **Grain:** product_day
- **Primary / Composite Key:** date, product_id
- **Synthetic Flag:** True

## Description
Synthetic benchmark competitor price observations across competing e-commerce platforms.

## Caveats & Usage Rules
- Governed joins must match approved keys (date, product_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
