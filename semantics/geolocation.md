# Table: geolocation

- **Data Layer:** Real
- **Grain:** zip_prefix
- **Primary / Composite Key:** geolocation_zip_code_prefix
- **Synthetic Flag:** False

## Description
Geographic coordinates (latitude, longitude) for Brazilian postal codes.

## Caveats & Usage Rules
- Governed joins must match approved keys (geolocation_zip_code_prefix).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
