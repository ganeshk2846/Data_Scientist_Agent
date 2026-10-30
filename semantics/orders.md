# Table: orders

- **Data Layer:** Real
- **Grain:** order
- **Primary / Composite Key:** order_id
- **Synthetic Flag:** False

## Description
Core table recording order placement, status lifecycle, and timestamp milestones.

## Caveats & Usage Rules
- Governed joins must match approved keys (order_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
