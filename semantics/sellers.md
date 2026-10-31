# `sellers`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

Seller location.

**Grain:** seller.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `seller_id` | Seller key. | text |
| `seller_zip_code_prefix` | Zip prefix. | integer |
| `seller_city` | City. | text |
| `seller_state` | State code. | text |

## Join keys

- `sellers.seller_id = order_items.seller_id` (1:N)

## Caveats

- `seller_state` is where the seller is, not the customer.
