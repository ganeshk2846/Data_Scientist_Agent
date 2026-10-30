# Database Covering Indexes (docs/DB_INDEXES.md)

To optimize query latency across the 18+ table schema and support low-latency fast-path queries,
the following covering indexes are applied in `data/brazil_ecommerce_v2.sqlite`:

## Synthetic Table Indexes

| Index Name | Table | Columns | Purpose |
| --- | --- | --- | --- |
| `idx_synth_marketing_date` | `marketing_spend` | `(date)` | Fast filtering on marketing spend date windows. |
| `idx_synth_marketing_channel_state` | `marketing_spend` | `(channel, customer_state)` | Fast grouping and slicing by channel and state. |
| `idx_synth_inventory_date_prod` | `inventory_daily` | `(date, product_id)` | Fast lookup on inventory levels by date and product. |
| `idx_synth_inventory_stockout` | `inventory_daily` | `(stockout_flag)` | Instant filtering of stockout events (E2). |
| `idx_synth_traffic_date_channel` | `web_traffic` | `(date, channel)` | Web session volume aggregation and funnel tracking. |
| `idx_synth_price_product_date` | `price_history` | `(product_id, date)` | Historical price tracking and price elasticity modeling. |
| `idx_synth_competitor_prod_date` | `competitor_prices` | `(product_id, date)` | Cross-merchant price comparison queries. |
| `idx_synth_cust_seg_id` | `customer_segments` | `(customer_unique_id)` | Fast joining on unique customer entity. |
| `idx_synth_regional_month_st` | `regional_targets` | `(month, customer_state)` | Monthly quota and target attainment lookups. |
| `idx_synth_returns_order` | `returns` | `(order_id, order_item_id)` | Direct joins to order_items for return rate analysis. |
| `idx_synth_sla_date_carrier` | `delivery_sla` | `(date, carrier, customer_state)` | Regional carrier delay and breach rate detection (E4). |

## Analytical Table Indexes

| Index Name | Table | Columns | Purpose |
| --- | --- | --- | --- |
| `idx_anom_kpi_date` | `analytical_anomalies` | `(kpi, date)` | Instant single-read lookup for S5 spike questions. |
| `idx_anom_flagged` | `analytical_anomalies` | `(flagged)` | Filtering flagged statistical anomalies. |
| `idx_fc_kpi_ds` | `analytical_forecasts` | `(kpi, ds)` | Cached forecast projections retrieval. |
| `idx_series_kpi_dim` | `analytical_series` | `(kpi, dimension, date)` | Precomputed monthly series slicing. |
