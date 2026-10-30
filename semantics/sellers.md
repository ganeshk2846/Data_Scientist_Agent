# Table: sellers

- **Data Layer:** Real
- **Grain:** seller
- **Primary / Composite Key:** seller_id
- **Synthetic Flag:** False

## Description
Marketplace merchants fulfilled orders from regional state locations.

## Caveats & Usage Rules
- Governed joins must match approved keys (seller_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
