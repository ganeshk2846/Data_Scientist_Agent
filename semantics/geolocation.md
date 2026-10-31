# `geolocation`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

Latitude and longitude points per zip prefix.

**Grain:** zip prefix point.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `geolocation_zip_code_prefix` | Zip prefix. | integer |
| `geolocation_lat` | Latitude. | degrees |
| `geolocation_lng` | Longitude. | degrees |
| `geolocation_city` | City. | text |
| `geolocation_state` | State code. | text |

## Join keys

- `geolocation_zip_code_prefix = customers.customer_zip_code_prefix` (N:N — aggregate first)

## Caveats

- About a million rows with many points per prefix: joining without aggregating multiplies rows.
