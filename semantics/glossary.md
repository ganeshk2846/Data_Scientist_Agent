# Business Terms & Semantic Glossary

This glossary maps common executive and conversational business expressions to governed schema columns and metrics.

| Business Term | Governed Concept / Column | Notes |
| --- | --- | --- |
| **Gross Revenue / Topline** | `gmv` | Total transaction value including freight charges. |
| **Net Revenue / Sales** | `revenue` | Order item product prices only (excluding freight). |
| **Active Customer** | `customers.customer_unique_id` with orders in window | Must use `customer_unique_id`, not `customer_id`. |
| **Buyer / Client** | `customers` | Refers to purchaser entities. |
| **Merchant / Vendor** | `sellers` | Third-party sellers on the marketplace. |
| **Geography / Region** | `customer_state` or `seller_state` | 2-letter Brazilian state code (SP, RJ, MG, RS, PR...). |
| **Shipping / Delivery SLA** | `delivery_sla.actual_days` vs `delivery_sla.promised_days` | Logistics SLA adherence and breach rates. |
| **Churn / Churn Risk** | `customer_segments.segment = 'At Risk'` | Inactivity or low RFM score indicator. |
| **Marketing Spend / CAC** | `marketing_spend.spend` | Paid media advertising expenditure by channel. |
| **Stockout / OOS** | `inventory_daily.stockout_flag = 1` | Zero units on hand for customer fulfillment. |
| **AOV / Basket Size** | `aov` (`revenue / order_count`) | Average expenditure per completed order. |
| **CSAT / Rating** | `review_score` | Average customer review rating between 1.0 and 5.0. |
