# Table: promotions

- **Data Layer:** Synthetic
- **Grain:** promotion
- **Primary / Composite Key:** promo_id
- **Synthetic Flag:** True

## Description
Synthetic promotional discount campaigns, timelines, and category eligibility rules.

## Caveats & Usage Rules
- Governed joins must match approved keys (promo_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
