# Analysis Rules for Brazil E-Commerce Warehouse (V2-DATA-1..3, SAFE-8)

This document specifies the normative analytical and reasoning rules of this warehouse.
These rules are retrieved into agent context for reasoning discipline, never as a source of figures.

---

## 1. The Truncation Trap (V2-DATA-1, V2-DATA-2, V2-DATA-3)

- **The last complete month is 2018-08.**
- The Olist collection window officially ended in October 2018, but the volume collapsed abruptly:
  - `2018-08`: 6,512 orders (Complete)
  - `2018-09`: **16 orders** (Truncated collection artefact)
  - `2018-10`: **4 orders** (Truncated collection artefact)
  - `2016-09`: Inception ramp (Incomplete)
- **Normative Rules:**
  - Any model fitting (forecasts, scenarios, trends) MUST anchor on **2018-08** and refuse to fit across 2018-09/2018-10.
  - Descriptive queries spanning September or October 2018 MUST include an explicit caveat declaring the period truncated.

---

## 2. Customer Identity Rule (customer_id vs customer_unique_id)

- In the Olist schema:
  - `customer_id` is an **order-level instance key** (one generated per order placed).
  - `customer_unique_id` is the **true individual customer identifier**.
- **Normative Rules:**
  - Customer retention, repeat purchase rate, churn, and LTV analyses MUST group or join on `customer_unique_id`.
  - Never join `customer_segments` on `customer_id`; always join on `customer_unique_id`.

---

## 3. Order Status & Completed Business Filtering

- Delivered, valid business transactions are filtered by:
  ```sql
  WHERE orders.order_status NOT IN ('canceled', 'unavailable')
  ```
- Unapproved cancellations must not be included in gross revenue calculations.

---

## 4. Synthetic Data Disclaimers (V2-SYN-4)

- The synthetic layer consists of 10 tables:
  `marketing_spend`, `promotions`, `inventory_daily`, `web_traffic`, `price_history`,
  `competitor_prices`, `customer_segments`, `regional_targets`, `returns`, `delivery_sla`.
- All figures derived from these tables MUST carry the `synthetic` data layer flag and be presented with explicit synthetic disclosure to avoid misrepresenting generated indicators as real-world audited financial data.

---

## 5. Non-Additive Metrics & Ratio Decomposition

- Ratio metrics (`aov`, `cancellation_rate`, `conversion_rate`, `stockout_rate`, `margin`) are **non-additive**:
  - You cannot sum AOV across states or months.
  - Decompositions must analyze the numerator (`revenue`) and denominator (`order_count`) independently.

