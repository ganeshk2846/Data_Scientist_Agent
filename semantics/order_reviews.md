# `order_reviews`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

Customer review of an order.

**Grain:** review.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `review_id` | Review key (a few ids repeat across orders). | text |
| `order_id` | Order key. | text |
| `review_score` | 1 to 5. | integer |
| `review_comment_title` | Free text; sensitive, never sent to a prompt. | text |
| `review_comment_message` | Free text; sensitive, never sent to a prompt. | text |
| `review_creation_date` | When the review survey was sent. | timestamp |
| `review_answer_timestamp` | When it was answered. | timestamp |

## Join keys

- `order_reviews.order_id = orders.order_id` (N:1)

## Caveats

- `review_score` is a **mean** metric: decompose it into score total over review count, never sum shares of it.
