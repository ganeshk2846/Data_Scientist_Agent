-- Covering indexes required by the governed metric fast-path.
-- See docs/DB_INDEXES.md for why single-column join-key indexes do NOT work.
-- Apply to a read-write connection: sqlite3 brazil_ecommerce.sqlite < docs/db_indexes.sql

CREATE INDEX IF NOT EXISTS idx_order_items_cover
    ON order_items(order_id, price, freight_value);

CREATE INDEX IF NOT EXISTS idx_orders_status_order_id
    ON orders(order_status, order_id);

CREATE INDEX IF NOT EXISTS idx_order_payments_cover
    ON order_payments(order_id, payment_value);

ANALYZE;
