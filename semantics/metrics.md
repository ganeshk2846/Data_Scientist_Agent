# Governed & Synthetic Metrics Definition Guide

| Metric ID | Name | Aggregation | Formula / Computation | Base Table | Grains | Caveats |
| --- | --- | --- | --- | --- | --- | --- |
| `revenue` | Net Sales Revenue | `sum` | `SUM(order_items.price)` | `order_items` | order, day, month, year | Excludes freight. Filters out canceled and unavailable orders. |
| `gmv` | Gross Merchandise Value | `sum` | `SUM(order_items.price + order_items.freight_value)` | `order_items` | order, month, year | Includes freight charges paid by buyer. |
| `order_count` | Order Volume | `count` | `COUNT(DISTINCT orders.order_id)` | `orders` | day, month, year | Count of delivered order transactions. |
| `aov` | Average Order Value | `ratio` | `revenue / order_count` | `order_items` | month, quarter, year | Ratio metric; non-additive. Decomposed into revenue and orders. |
| `review_score` | CSAT Review Score | `mean` | `AVG(order_reviews.review_score)` | `order_reviews` | month, year, category | Values range from 1 to 5. |
| `cancellation_rate` | Cancellation Rate | `ratio` | `canceled_orders / total_orders` | `orders` | month, year | Ratio metric; non-additive. |
| `freight_value` | Freight Expenses | `sum` | `SUM(order_items.freight_value)` | `order_items` | month, year | Shipping charges billed to customers. |
| `item_count` | Units Sold | `count` | `COUNT(order_items.order_item_id)` | `order_items` | day, month, year | Individual items purchased across orders. |
| `customer_count` | Unique Customers | `count` | `COUNT(DISTINCT customers.customer_unique_id)` | `customers` | month, year, state | Distinct individuals, not order instances. |
| `marketing_spend` | Marketing Spend | `sum` | `SUM(marketing_spend.spend)` | `marketing_spend` | day, month, channel | Synthetic operational expenditure. |
| `sessions` | Web Sessions | `sum` | `SUM(web_traffic.sessions)` | `web_traffic` | day, month, channel | Synthetic web visitor volume. |
| `conversion_rate` | Conversion Rate | `ratio` | `order_count / sessions` | `web_traffic` | month, channel | Synthetic digital marketing conversion efficiency. |
| `stockout_rate` | Stockout Rate | `ratio` | `stockout_days / total_catalog_days` | `inventory_daily` | month, category | Proportion of catalog inventory experiencing stockouts. |
| `return_rate` | Return Rate | `ratio` | `returned_units / total_units` | `returns` | month, category | Customer merchandise return percentage. |
| `margin` | Gross Product Margin | `ratio` | `(revenue - cost) / revenue` | `order_items` | month, category | Product profitability margin. |
| `target_attainment` | Regional Attainment | `ratio` | `actual_revenue / revenue_target` | `regional_targets` | month, state | Achievement percentage against governed monthly quotas. |

