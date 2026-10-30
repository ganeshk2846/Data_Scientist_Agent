# `order_items`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

One row per item in an order.

**Grain:** order item.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `order_id` | Order key. | text |
| `order_item_id` | Sequence number of the item within its order (1, 2, …). | integer |
| `product_id` | Product key. | text |
| `seller_id` | Seller key. | text |
| `shipping_limit_date` | Seller's shipping deadline. | timestamp |
| `price` | Item price. | BRL |
| `freight_value` | Freight charged for the item. | BRL |

## Join keys

- `order_items.order_id = orders.order_id` (N:1)
- `order_items.product_id = products.product_id` (N:1)
- `order_items.seller_id = sellers.seller_id` (N:1)
- `(order_id, order_item_id) = returns.(order_id, order_item_id)` (1:1, synthetic)

## Caveats

- GMV is `price + freight_value` at order-item grain; revenue is payments at order grain. They differ.
