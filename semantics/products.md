# Table: products

- **Data Layer:** Real
- **Grain:** product
- **Primary / Composite Key:** product_id
- **Synthetic Flag:** False

## Description
Product master data with dimensions, weights, and Portuguese category names.

## Caveats & Usage Rules
- Governed joins must match approved keys (product_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
