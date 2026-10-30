# Table: order_reviews

- **Data Layer:** Real
- **Grain:** review
- **Primary / Composite Key:** review_id
- **Synthetic Flag:** False

## Description
Customer survey reviews rated from 1 to 5 stars upon order delivery.

## Caveats & Usage Rules
- Governed joins must match approved keys (review_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
