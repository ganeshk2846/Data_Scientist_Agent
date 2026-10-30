# Table: order_items

- **Data Layer:** Real
- **Grain:** order_item
- **Primary / Composite Key:** order_id, order_item_id
- **Synthetic Flag:** False

## Description
Line items associated with each order, containing price, freight, product_id, and seller_id.

## Caveats & Usage Rules
- Governed joins must match approved keys (order_id, order_item_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
