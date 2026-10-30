# Database Indexes — `brazil_ecommerce.sqlite`

| | |
|---|---|
| **Status** | Required for `backend/tests/test_metric_compiler.py` to pass |
| **Applies to** | A locally built `brazil_ecommerce.sqlite` (Olist Brazilian E-Commerce dataset) |
| **Verified on** | 2026-10-28, SQLite via Python 3.14, 99,441 `orders` rows |

The database ships with **no indexes**. Without the three covering indexes below,
the governed metric fast-path exceeds its 1,000 ms budget and
`test_each_governed_metric_compiles_executes_and_is_deterministic` fails on the
`gmv` / `aov` metrics.

## Apply

Run against your own copy (this writes to the file, so stop any server first):

```sql
CREATE INDEX IF NOT EXISTS idx_order_items_cover
    ON order_items(order_id, price, freight_value);

CREATE INDEX IF NOT EXISTS idx_orders_status_order_id
    ON orders(order_status, order_id);

CREATE INDEX IF NOT EXISTS idx_order_payments_cover
    ON order_payments(order_id, payment_value);

ANALYZE;
```

From the workspace root, the same statements are kept ready to run in
[`db_indexes.sql`](db_indexes.sql):

```bash
sqlite3 brazil_ecommerce.sqlite < docs/db_indexes.sql
```

Or, without the `sqlite3` CLI:

```bash
python -c "import sqlite3; c=sqlite3.connect('brazil_ecommerce.sqlite'); c.executescript(open('docs/db_indexes.sql').read()); c.commit()"
```

`ANALYZE` matters — it writes the `sqlite_stat1` statistics the query planner
needs to choose these indexes over a full scan.

## Why these three, and why covering

Each index lists **every column the query reads from that table**, so SQLite
answers the query from the index alone and never looks up the table row
(`COVERING INDEX` in the query plan). The column order matters: the join or
filter key comes first, the aggregated columns after.

| Index | Serves |
|---|---|
| `idx_order_items_cover` | `SUM(price + freight_value)` joined on `order_id` — GMV and AOV |
| `idx_orders_status_order_id` | the `order_status NOT IN ('canceled','unavailable')` required filter |
| `idx_order_payments_cover` | `SUM(payment_value)` joined on `order_id` — revenue |

### Single-column indexes on the join keys do not work

A plain `CREATE INDEX ... ON order_items(order_id)` makes the metric queries
**slower than having no index at all**:

| Configuration | `aov` median |
|---|---|
| No indexes | 1,203 ms |
| Single-column indexes on all join keys | 2,183 ms |
| The three covering indexes above | 121 ms |

With no index, SQLite builds a transient *automatic covering index* per query and
never touches the table. A single-column index looks cheaper to the planner, so
it stops building the automatic one — but it only covers `order_id`, so every
matched row then needs a rowid lookup to fetch `price` and `freight_value`. That
random I/O costs more than the scan it replaced.

So do not "optimise" by adding single-column join-key indexes; they regress the
fast path. Verify with:

```sql
EXPLAIN QUERY PLAN
SELECT SUM(oi.price + oi.freight_value) / COUNT(DISTINCT o.order_id)
FROM order_items oi JOIN orders o ON oi.order_id = o.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable');
```

Both table accesses should say `COVERING INDEX`:

```
SCAN o USING COVERING INDEX idx_orders_status_order_id
SEARCH oi USING COVERING INDEX idx_order_items_cover (order_id=?)
```

If either says `AUTOMATIC COVERING INDEX` or a bare `SEARCH ... USING INDEX`,
the indexes are missing or `ANALYZE` has not been run.

## Notes

* Indexes are a property of the built database, not of the backend — no backend
  code depends on them by name.
* The gateway opens SQLite strictly read-only (`?mode=ro`), so these statements
  must be run through a separate read-write connection.
* Back up first: `cp brazil_ecommerce.sqlite brazil_ecommerce.backup.sqlite`.
* If you write a loader script, create these indexes as its final step so a
  rebuilt database does not reintroduce the failure.

---

## V2 database — `data/brazil_ecommerce_v2.sqlite`

The V2 build is generated, so its indexes are created by the generator
(`scripts/synth/generate.py`, `INDEXES`), followed by `ANALYZE`. Nothing has
to be applied by hand. The real snapshot is opened read-only and is never
indexed by the build.

The same rule applies: every index is **covering**, with the join or filter
key first and the columns the queries read after it.

| Index | Serves |
|---|---|
| the three indexes above | the governed metric fast path, unchanged |
| `idx_orders_purchase_cover` on `orders(order_purchase_timestamp, order_id, order_status, customer_id)` | per-day and per-month KPI builds |
| `idx_customers_unique_cover` on `customers(customer_unique_id, customer_id, customer_state)` | `customer_segments` ⇄ `customers` |
| `idx_order_items_product_cover` on `order_items(product_id, order_id, order_item_id, price)` | `price_history` / `competitor_prices` ⇄ `order_items` (margin) |
| `idx_returns_item_cover` on `returns(order_id, order_item_id, refund_value, reason)` | `returns` ⇄ `order_items` (return rate) |
| `idx_price_history_cover` on `price_history(product_id, date, price, unit_cost)` | point-in-time price and cost lookups |
| `idx_competitor_prices_cover` on `competitor_prices(product_id, date, competitor, price)` | elasticity controls |
| `idx_customer_segments_cover` on `customer_segments(customer_unique_id, segment, ltv_band)` | segment breakdowns |
| `idx_regional_targets_cover` on `regional_targets(state, month, revenue_target)` | target attainment |
| `idx_web_traffic_cover` on `web_traffic(state, date, sessions, conversion_rate)` | sessions and conversion by state |
| `idx_inventory_daily_cover` on `inventory_daily(category, date, units_sold, stockout_flag)` | stockout rate by category |
| `idx_marketing_spend_cover` on `marketing_spend(category, date, channel, spend)` | spend by category and channel |
| `idx_delivery_sla_cover` on `delivery_sla(state, date, carrier, actual_days, promised_days)` | SLA by state and carrier |
| `idx_promotions_category` on `promotions(category, start_date, end_date, discount_pct)` | active-promotion lookups |

### Pointing the backend at the V2 database

```bash
export DS_AGENT_DB=data/brazil_ecommerce_v2.sqlite
```

`DS_AGENT_DB` takes precedence over the older `DS_AGENT_DATABASE`. With
neither set, the backend still opens `brazil_ecommerce.sqlite`, as before.
