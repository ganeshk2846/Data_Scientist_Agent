# Table: customer_segments

- **Data Layer:** Synthetic
- **Grain:** customer_unique_id
- **Primary / Composite Key:** customer_unique_id
- **Synthetic Flag:** True

## Description
Synthetic customer behavioral segmentation (Champions, Loyal, At Risk) based on RFM modeling.

## Caveats & Usage Rules
- Governed joins must match approved keys (customer_unique_id).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
