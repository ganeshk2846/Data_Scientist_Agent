# `order_payments`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

One row per payment instalment of an order.

**Grain:** payment.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `order_id` | Order key. | text |
| `payment_sequential` | Sequence of the payment within its order. | integer |
| `payment_type` | credit_card, boleto, voucher, debit_card or not_defined (3 rows). | text |
| `payment_installments` | Number of instalments. | integer |
| `payment_value` | Amount paid. | BRL |

## Join keys

- `order_payments.order_id = orders.order_id` (N:1)

## Caveats

- An order can have several payment rows; revenue sums them. Joining payments to items multiplies rows — never sum payments across an item join.
