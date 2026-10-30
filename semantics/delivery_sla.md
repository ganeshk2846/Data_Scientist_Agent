# Table: delivery_sla

- **Data Layer:** Synthetic
- **Grain:** carrier_day_state
- **Primary / Composite Key:** date, carrier, customer_state
- **Synthetic Flag:** True

## Description
Synthetic carrier delivery reliability tracking promised days versus actual transit days and SLA breaches.

## Caveats & Usage Rules
- Governed joins must match approved keys (date, carrier, customer_state).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
