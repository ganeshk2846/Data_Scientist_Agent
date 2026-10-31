# `orders`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

One row per order: its customer, status and lifecycle timestamps.

**Grain:** order.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `order_id` | Order key. | text |
| `customer_id` | Per-order customer key; joins `customers.customer_id`. **Not** the person — see `customer_unique_id`. | text |
| `order_status` | One of 8 states: delivered, shipped, canceled, unavailable, invoiced, processing, created, approved. | text |
| `order_purchase_timestamp` | When the order was placed. **The date column of every governed metric.** | timestamp |
| `order_approved_at` | Payment approval time. | timestamp |
| `order_delivered_carrier_date` | Handed to the carrier. | timestamp |
| `order_delivered_customer_date` | Delivered to the customer; null unless delivered. | timestamp |
| `order_estimated_delivery_date` | Promised delivery date. | timestamp |

## Join keys

- `orders.customer_id = customers.customer_id` (N:1)
- `order_items.order_id`, `order_payments.order_id`, `order_reviews.order_id` (1:N)

## Caveats

- **Truncation:** 2018-09 (16 orders) and 2018-10 (4 orders) are collection artefacts, as is 2016-09; 2016-11 has no orders and 2016-12 one. The last complete month is **2018-08** (`semantic/completeness.py`).
- Completed-order metrics exclude `canceled` and `unavailable`.
