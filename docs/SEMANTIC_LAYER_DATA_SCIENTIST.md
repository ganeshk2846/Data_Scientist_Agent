# Data Scientist Semantic Layer Specification

This document records the formal semantic layer additions, governed metric definitions, dimension bindings, and join-graph specifications added to the **Enterprise Data Scientist Agent**.

---

## 1. Architectural Overview

The Semantic Layer sits between user business intent and the database engine. In contrast to unconstrained text-to-SQL (which often hallucinates columns, introduces fanout duplicate aggregations, or uses inconsistent business logic), this semantic layer enforces **strict deterministic metric governance**:

* **Mathematical Single-Source-of-Truth**: Each metric is defined once with an exact SQL formula and reconciliation query.
* **Join Governance**: Aggregations only traverse pre-approved join paths with explicit cardinality (`1:N`, `N:1`), preventing cross-product explosion.
* **Filter Governance**: Status filters (e.g., excluding canceled/unavailable orders) are automatically enforced across all revenue and volume calculations.
* **Dimensional Conformance**: Metrics declare the exact dimensions they are allowed to slice by.

---

## 2. Complete Inventory of Governed Metrics

### 2.1. Gross Merchandise Value (`gmv`)
* **Metric ID:** `gmv`
* **Display Name:** Gross Merchandise Value
* **Business Definition:** Total value of ordered items including freight for completed (non-canceled, non-unavailable) transactions.
* **Base Table:** `order_items`
* **Grain:** `order_item`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `SUM({{ order_items }}.price + {{ order_items }}.freight_value)`
* **Required Filters:** `{{ orders }}.order_status NOT IN ('canceled', 'unavailable')`
* **Allowed Dimensions:** `customer_state`, `customer_city`, `order_status`, `product_category`, `seller_state`, `month`, `year`
* **Approved Joins:**
  * `order_items.order_id = orders.order_id` (N:1)
  * `customers.customer_id = orders.customer_id` (1:N)
  * `order_items.product_id = products.product_id` (N:1)
  * `order_items.seller_id = sellers.seller_id` (N:1)
* **Reconciliation Query:**
  ```sql
  SELECT SUM(oi.price + oi.freight_value)
  FROM order_items oi
  JOIN orders o ON oi.order_id = o.order_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable');
  ```
* **Olist Dataset Benchmark:** `15,735,527.03`
* **Synonyms:** `gmv`, `gross merchandise value`, `gross merchandise volume`, `merchandise value`

---

### 2.2. Revenue (`revenue`)
* **Metric ID:** `revenue`
* **Display Name:** Revenue
* **Business Definition:** Total recognized monetary payments received for completed transactions.
* **Base Table:** `order_payments`
* **Grain:** `order`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `SUM({{ order_payments }}.payment_value)`
* **Required Filters:** `{{ orders }}.order_status NOT IN ('canceled', 'unavailable')`
* **Allowed Dimensions:** `customer_state`, `customer_city`, `order_status`, `payment_type`, `month`, `year`
* **Approved Joins:**
  * `order_payments.order_id = orders.order_id` (N:1)
  * `customers.customer_id = orders.customer_id` (1:N)
* **Reconciliation Query:**
  ```sql
  SELECT SUM(op.payment_value)
  FROM order_payments op
  JOIN orders o ON op.order_id = o.order_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable');
  ```
* **Olist Dataset Benchmark:** `15,739,137.01`
* **Synonyms:** `revenue`, `total revenue`, `sales`, `total sales`, `net sales`, `turnover`

---

### 2.3. Order Count (`order_count`)
* **Metric ID:** `order_count`
* **Display Name:** Order Count
* **Business Definition:** Total count of unique orders placed across all statuses.
* **Base Table:** `orders`
* **Grain:** `order`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `COUNT(DISTINCT {{ orders }}.order_id)`
* **Required Filters:** None (includes all order statuses)
* **Allowed Dimensions:** `customer_state`, `customer_city`, `order_status`, `month`, `year`
* **Approved Joins:**
  * `customers.customer_id = orders.customer_id` (1:N)
* **Reconciliation Query:**
  ```sql
  SELECT COUNT(DISTINCT order_id) FROM orders;
  ```
* **Olist Dataset Benchmark:** `99,441`
* **Synonyms:** `order count`, `order volume`, `number of orders`, `how many orders`

---

### 2.4. Average Order Value (`aov`)
* **Metric ID:** `aov`
* **Display Name:** Average Order Value
* **Business Definition:** Average revenue generated per distinct completed order.
* **Base Table:** `order_payments`
* **Grain:** `order`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `SUM({{ order_payments }}.payment_value) * 1.0 / NULLIF(COUNT(DISTINCT {{ orders }}.order_id), 0)`
* **Required Filters:** `{{ orders }}.order_status NOT IN ('canceled', 'unavailable')`
* **Allowed Dimensions:** `customer_state`, `customer_city`, `order_status`, `payment_type`, `month`, `year`
* **Approved Joins:**
  * `order_payments.order_id = orders.order_id` (N:1)
  * `customers.customer_id = orders.customer_id` (1:N)
* **Reconciliation Query:**
  ```sql
  SELECT SUM(op.payment_value) * 1.0 / NULLIF(COUNT(DISTINCT o.order_id), 0)
  FROM order_payments op
  JOIN orders o ON op.order_id = o.order_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable');
  ```
* **Olist Dataset Benchmark:** `160.27`
* **Synonyms:** `aov`, `average order value`, `average basket`, `average order size`, `average order amount`

---

### 2.5. Customer Satisfaction Score (`review_score`)
* **Metric ID:** `review_score`
* **Display Name:** Customer Satisfaction Score (CSAT)
* **Business Definition:** Arithmetic mean of customer survey review ratings (1 to 5 scale).
* **Base Table:** `order_reviews`
* **Grain:** `review`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `AVG({{ order_reviews }}.review_score)`
* **Required Filters:** None
* **Allowed Dimensions:** `customer_state`, `customer_city`, `order_status`, `month`, `year`
* **Approved Joins:**
  * `order_reviews.order_id = orders.order_id` (N:1)
  * `customers.customer_id = orders.customer_id` (1:N)
* **Reconciliation Query:**
  ```sql
  SELECT AVG(review_score) FROM order_reviews;
  ```
* **Olist Dataset Benchmark:** `4.086`
* **Synonyms:** `csat`, `customer satisfaction`, `customer rating`, `customer ratings`, `satisfaction score`, `satisfaction rating`

---

### 2.6. Freight Value (`freight_value`)
* **Metric ID:** `freight_value`
* **Display Name:** Freight Value
* **Business Definition:** Total logistics and shipping charge incurred on completed orders.
* **Base Table:** `order_items`
* **Grain:** `order_item`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `SUM({{ order_items }}.freight_value)`
* **Required Filters:** `{{ orders }}.order_status NOT IN ('canceled', 'unavailable')`
* **Allowed Dimensions:** `customer_state`, `customer_city`, `order_status`, `product_category`, `seller_state`, `month`, `year`
* **Approved Joins:**
  * `order_items.order_id = orders.order_id` (N:1)
  * `customers.customer_id = orders.customer_id` (1:N)
  * `order_items.product_id = products.product_id` (N:1)
  * `order_items.seller_id = sellers.seller_id` (N:1)
* **Reconciliation Query:**
  ```sql
  SELECT SUM(oi.freight_value)
  FROM order_items oi
  JOIN orders o ON oi.order_id = o.order_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable');
  ```
* **Olist Dataset Benchmark:** `2,241,126.29`
* **Synonyms:** `freight`, `freight value`, `freight cost`, `shipping cost`, `delivery fee`, `shipping fee`, `total freight`

---

### 2.7. Item Count (`item_count`)
* **Metric ID:** `item_count`
* **Display Name:** Item Count / Units Sold
* **Business Definition:** Total number of individual items/units purchased in non-canceled orders.
* **Base Table:** `order_items`
* **Grain:** `order_item`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `COUNT({{ order_items }}.order_item_id)`
* **Required Filters:** `{{ orders }}.order_status NOT IN ('canceled', 'unavailable')`
* **Allowed Dimensions:** `customer_state`, `customer_city`, `order_status`, `product_category`, `seller_state`, `month`, `year`
* **Approved Joins:**
  * `order_items.order_id = orders.order_id` (N:1)
  * `customers.customer_id = orders.customer_id` (1:N)
  * `order_items.product_id = products.product_id` (N:1)
  * `order_items.seller_id = sellers.seller_id` (N:1)
* **Reconciliation Query:**
  ```sql
  SELECT COUNT(oi.order_item_id)
  FROM order_items oi
  JOIN orders o ON oi.order_id = o.order_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable');
  ```
* **Olist Dataset Benchmark:** `112,101`
* **Synonyms:** `item count`, `units sold`, `quantity sold`, `number of items`, `total items`, `volume of items`, `items sold`

---

### 2.8. Unique Customers (`customer_count`)
* **Metric ID:** `customer_count`
* **Display Name:** Unique Customers
* **Business Definition:** Total distinct individuals (by `customer_unique_id`) registered in the platform.
* **Base Table:** `customers`
* **Grain:** `customer`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `COUNT(DISTINCT {{ customers }}.customer_unique_id)`
* **Required Filters:** None
* **Allowed Dimensions:** `customer_state`, `customer_city`, `month`, `year`
* **Approved Joins:**
  * `customers.customer_id = orders.customer_id` (1:N)
* **Reconciliation Query:**
  ```sql
  SELECT COUNT(DISTINCT customer_unique_id) FROM customers;
  ```
* **Olist Dataset Benchmark:** `96,096`
* **Synonyms:** `unique customers`, `customer count`, `active customers`, `buyer count`, `number of customers`, `customer volume`, `distinct buyers`

---

### 2.9. Cancellation Rate (`cancellation_rate`)
* **Metric ID:** `cancellation_rate`
* **Display Name:** Order Cancellation Rate
* **Business Definition:** Percentage of placed orders with status `'canceled'`.
* **Base Table:** `orders`
* **Grain:** `order`
* **Date Column:** `orders.order_purchase_timestamp`
* **Formula:** `SUM(CASE WHEN {{ orders }}.order_status = 'canceled' THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT({{ orders }}.order_id), 0)`
* **Required Filters:** None
* **Allowed Dimensions:** `customer_state`, `customer_city`, `month`, `year`
* **Approved Joins:**
  * `customers.customer_id = orders.customer_id` (1:N)
* **Reconciliation Query:**
  ```sql
  SELECT SUM(CASE WHEN order_status = 'canceled' THEN 1.0 ELSE 0.0 END) / COUNT(order_id) FROM orders;
  ```
* **Olist Dataset Benchmark:** `0.006285` (0.63%)
* **Synonyms:** `cancellation rate`, `canceled rate`, `order cancellation rate`, `cancelled rate`, `churn rate`

---

## 3. Dimensions and Granularities

| Dimension Name | Underlying Table | Column Name | Synonyms / Search Aliases | Supported Metrics |
| :--- | :--- | :--- | :--- | :--- |
| `customer_state` | `customers` | `customer_state` | `state`, `customer state`, `customer states`, `region` | All metrics |
| `customer_city` | `customers` | `customer_city` | `city`, `customer city`, `town` | All metrics |
| `seller_state` | `sellers` | `seller_state` | `seller state`, `seller region`, `origin state` | `gmv`, `freight_value`, `item_count` |
| `product_category`| `products` | `product_category_name` | `category`, `product category`, `product categories` | `gmv`, `freight_value`, `item_count` |
| `order_status` | `orders` | `order_status` | `status`, `order status`, `order statuses` | All order/item metrics |
| `payment_type` | `order_payments` | `payment_type` | `payment type`, `payment method`, `payment types` | `revenue`, `aov` |
| `month` | `orders` | `order_purchase_timestamp` | `month`, `monthly`, `by month` | All metrics |
| `year` | `orders` | `order_purchase_timestamp` | `year`, `yearly`, `by year` | All metrics |

---

## 4. Approved Join Topology

```
                  ┌──────────────────────┐
                  │      customers       │
                  └──────────┬───────────┘
                             │ customer_id = customer_id (1:N)
                             ▼
                  ┌──────────────────────┐
   ┌─────────────►│        orders        │◄────────────┐
   │              └──────────┬───────────┘             │
   │                         │                         │
   │ order_id = order_id     │ order_id = order_id     │ order_id = order_id
   │ (N:1)                   │ (N:1)                   │ (N:1)
   │                         ▼                         │
┌──┴────────────┐     ┌──────────────┐          ┌──────┴─────────┐
│order_payments │     │ order_items  │          │ order_reviews  │
└───────────────┘     └──────┬───────┘          └────────────────┘
                             │
            ┌────────────────┴────────────────┐
            │ product_id = product_id         │ seller_id = seller_id
            │ (N:1)                           │ (N:1)
            ▼                                 ▼
     ┌──────────────┐                  ┌──────────────┐
     │   products   │                  │   sellers    │
     └──────────────┘                  └──────────────┘
```

