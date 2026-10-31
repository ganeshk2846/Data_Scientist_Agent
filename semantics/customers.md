# `customers`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

One row per order-customer.

**Grain:** customer per order.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `customer_id` | Per-order key; 99,441 rows, one per order. | text |
| `customer_unique_id` | **The person.** Use it for unique-customer counts and for `customer_segments`. | text |
| `customer_zip_code_prefix` | First five digits of the zip code. | integer |
| `customer_city` | City. | text |
| `customer_state` | Two-letter state code (27 values). | text |

## Join keys

- `customers.customer_id = orders.customer_id` (1:N)
- `customers.customer_unique_id = customer_segments.customer_unique_id` (N:1, synthetic)

## Caveats

- Counting `customer_id` counts orders, not people. Age, gender and income are **not held** in any layer.
