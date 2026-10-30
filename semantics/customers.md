# Table: customers

- **Data Layer:** Real
- **Grain:** customer_instance
- **Primary / Composite Key:** customer_id
- **Synthetic Flag:** False

## Description
Customer order-level keys mapped to customer_unique_id individual entities and state/city.

## Caveats & Usage Rules
- Governed joins must match approved keys (customer_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
