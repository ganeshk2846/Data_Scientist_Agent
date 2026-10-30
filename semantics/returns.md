# Table: returns

- **Data Layer:** Synthetic
- **Grain:** order_item
- **Primary / Composite Key:** order_id, order_item_id
- **Synthetic Flag:** True

## Description
Synthetic merchandise return transactions capturing return reasons and refund values.

## Caveats & Usage Rules
- Governed joins must match approved keys (order_id, order_item_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
