-- order-service schema, applied by the service on every start (idempotent).

CREATE TABLE IF NOT EXISTS stores (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    price           BIGINT NOT NULL,
    warranty_months INT NOT NULL,
    name_unaccent   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS products_name_unaccent_idx ON products (name_unaccent);

CREATE TABLE IF NOT EXISTS inventory (
    product_id TEXT NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    store_id   TEXT NOT NULL REFERENCES stores (id) ON DELETE CASCADE,
    qty        INT NOT NULL DEFAULT 0,
    PRIMARY KEY (product_id, store_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id                 TEXT PRIMARY KEY,
    customer_name      TEXT NOT NULL,
    product_id         TEXT NOT NULL REFERENCES products (id),
    quantity           INT NOT NULL DEFAULT 1,
    unit_price         BIGINT NOT NULL,
    discount           BIGINT NOT NULL DEFAULT 0,
    paid_amount        BIGINT NOT NULL DEFAULT 0,
    payment_method     TEXT NOT NULL,
    installment_months INT,
    order_date         DATE NOT NULL,
    delivered_date     DATE,
    status             TEXT NOT NULL CHECK (status IN ('pending', 'shipping', 'delivered', 'cancelled', 'returned')),
    store_id           TEXT NOT NULL REFERENCES stores (id)
);

-- Added after the first deploys: ALTER keeps existing databases in step with CREATE above.
-- Where send_email may write to; NULL for orders without a known address.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_email TEXT;

CREATE INDEX IF NOT EXISTS orders_product_id_idx ON orders (product_id);
CREATE INDEX IF NOT EXISTS orders_store_id_idx ON orders (store_id);

-- Every line of an order. v1's API still serves one product line per order (orders.product_id);
-- imported orders with several lines keep all of them here.
CREATE TABLE IF NOT EXISTS order_items (
    order_id        TEXT   NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    line_no         INT    NOT NULL,
    product_id      TEXT   NOT NULL REFERENCES products (id),
    color           TEXT   NOT NULL DEFAULT '',
    quantity        INT    NOT NULL,
    unit_list_price BIGINT NOT NULL,
    unit_price      BIGINT NOT NULL,
    line_total      BIGINT NOT NULL,
    PRIMARY KEY (order_id, line_no)
);
