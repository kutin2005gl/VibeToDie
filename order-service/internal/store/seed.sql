-- Seed data for order-service, loaded only when ORDERS_SEED=1.
-- Uses ON CONFLICT DO NOTHING for safe idempotency.

-- Stores
INSERT INTO stores (id, name) VALUES
    ('STORE_Q1', 'CN Quận 1'),
    ('STORE_TD', 'CN Thủ Đức'),
    ('STORE_BT', 'CN Bình Thạnh'),
    ('STORE_GV', 'CN Gò Vấp')
ON CONFLICT (id) DO NOTHING;

-- Products (P001-P003 exact match to seed.json, plus 8 diverse items)
INSERT INTO products (id, name, price, warranty_months, name_unaccent) VALUES
    ('P001', 'iPhone 16 128GB', 22990000, 12, 'iphone 16 128gb'),
    ('P002', 'Samsung Galaxy S25 256GB', 18490000, 12, 'samsung galaxy s25 256gb'),
    ('P003', 'Xiaomi 15 256GB', 14990000, 18, 'xiaomi 15 256gb'),
    ('P004', 'iPhone 16 256GB', 25990000, 12, 'iphone 16 256gb'),
    ('P005', 'Samsung Galaxy S25 Ultra 512GB', 29990000, 12, 'samsung galaxy s25 ultra 512gb'),
    ('P006', 'Xiaomi 14T 256GB', 12990000, 18, 'xiaomi 14t 256gb'),
    ('P007', 'OPPO Reno 12 256GB', 11990000, 12, 'oppo reno 12 256gb'),
    ('P008', 'iPad Air M2 128GB', 16990000, 12, 'ipad air m2 128gb'),
    ('P009', 'Tai nghe AirPods Pro 2', 5990000, 12, 'tai nghe airpods pro 2'),
    ('P010', 'Samsung Galaxy Z Flip 6 256GB', 23990000, 12, 'samsung galaxy z flip 6 256gb'),
    ('P011', 'iPhone 15 128GB', 18990000, 12, 'iphone 15 128gb')
ON CONFLICT (id) DO NOTHING;

-- Inventory (P001 total: 14, P002 total: 6, P003 total: 0)
INSERT INTO inventory (product_id, store_id, qty) VALUES
    ('P001', 'STORE_Q1', 8),
    ('P001', 'STORE_TD', 6),
    ('P001', 'STORE_BT', 0),
    ('P001', 'STORE_GV', 0),
    ('P002', 'STORE_Q1', 4),
    ('P002', 'STORE_TD', 2),
    ('P002', 'STORE_BT', 0),
    ('P002', 'STORE_GV', 0),
    ('P003', 'STORE_Q1', 0),
    ('P003', 'STORE_TD', 0),
    ('P003', 'STORE_BT', 0),
    ('P003', 'STORE_GV', 0),
    -- P004: in stock at Q1, out of stock at TD
    ('P004', 'STORE_Q1', 5),
    ('P004', 'STORE_TD', 0),
    -- P005: out of stock at Q1, in stock at TD
    ('P005', 'STORE_Q1', 0),
    ('P005', 'STORE_TD', 3),
    -- P006
    ('P006', 'STORE_Q1', 10),
    ('P006', 'STORE_TD', 5),
    -- P007
    ('P007', 'STORE_BT', 8),
    ('P007', 'STORE_GV', 4),
    -- P008
    ('P008', 'STORE_Q1', 2),
    ('P008', 'STORE_BT', 2),
    -- P009
    ('P009', 'STORE_Q1', 20),
    ('P009', 'STORE_TD', 15),
    -- P010
    ('P010', 'STORE_TD', 1),
    ('P010', 'STORE_GV', 0),
    -- P011
    ('P011', 'STORE_Q1', 7),
    ('P011', 'STORE_BT', 3)
ON CONFLICT (product_id, store_id) DO NOTHING;

-- Orders (DH1001-DH1003 exact match to seed.json, plus 10 diverse orders)
-- Only DH1001 has a real inbox (the demo's); every other address is @example.com, which never delivers.
-- Existing orders only get their email filled in.
INSERT INTO orders (id, customer_name, customer_email, product_id, quantity, unit_price, discount, paid_amount, payment_method, installment_months, order_date, delivered_date, status, store_id) VALUES
    ('DH1001', 'Huỳnh Phúc Hoàng Nhật', 'nhattin1402@gmail.com', 'P001', 1, 22990000, 1000000, 21990000, 'chuyển khoản', NULL, '2026-10-15', '2026-10-17', 'delivered', 'STORE_Q1'),
    ('DH1002', 'Trần Thị Bình', 'binh.tran@example.com', 'P002', 1, 18490000, 0, 0, 'trả góp qua thẻ tín dụng', 6, '2026-10-19', NULL, 'shipping', 'STORE_TD'),
    ('DH1003', 'Lê Minh Châu', 'chau.le@example.com', 'P003', 1, 14990000, 500000, 14490000, 'tiền mặt', NULL, '2026-08-28', '2026-09-01', 'delivered', 'STORE_Q1'),
    ('DH1004', 'Phạm Quốc Dũng', 'dung.pham@example.com', 'P004', 1, 25990000, 1000000, 24990000, 'chuyển khoản', NULL, '2026-10-20', NULL, 'shipping', 'STORE_Q1'),
    ('DH1005', 'Hoàng Thu Thảo', 'thao.hoang@example.com', 'P001', 1, 22990000, 0, 0, 'tiền mặt', NULL, '2026-10-21', NULL, 'cancelled', 'STORE_TD'),
    ('DH1006', 'Đỗ Thành Nam', 'nam.do@example.com', 'P002', 1, 18490000, 500000, 17990000, 'chuyển khoản', NULL, '2026-10-10', '2026-10-12', 'returned', 'STORE_Q1'),
    ('DH1007', 'Vũ Thanh Hà', 'ha.vu@example.com', 'P005', 1, 29990000, 0, 0, 'trả góp qua thẻ tín dụng', 12, '2026-10-22', NULL, 'pending', 'STORE_TD'),
    ('DH1008', 'Ngô Đức Thắng', 'thang.ngo@example.com', 'P006', 1, 12990000, 0, 12990000, 'thẻ ATM', NULL, '2026-10-18', '2026-10-20', 'delivered', 'STORE_BT'),
    ('DH1009', 'Bùi Thúy Hằng', 'hang.bui@example.com', 'P007', 1, 11990000, 200000, 11790000, 'chuyển khoản', NULL, '2026-10-23', NULL, 'shipping', 'STORE_GV'),
    ('DH1010', 'Trịnh Văn Long', 'long.trinh@example.com', 'P008', 1, 16990000, 0, 0, 'trả góp qua thẻ tín dụng', 12, '2026-10-14', '2026-10-16', 'delivered', 'STORE_Q1'),
    ('DH1011', 'Đinh Thị Mai', 'mai.dinh@example.com', 'P009', 2, 5990000, 500000, 11480000, 'tiền mặt', NULL, '2026-10-24', NULL, 'pending', 'STORE_TD'),
    ('DH1012', 'Phan Bá Tùng', 'tung.phan@example.com', 'P010', 1, 23990000, 1000000, 22990000, 'chuyển khoản', NULL, '2026-10-12', '2026-10-15', 'delivered', 'STORE_TD'),
    ('DH1013', 'Mai Xuân Trường', 'truong.mai@example.com', 'P011', 1, 18990000, 500000, 18490000, 'tiền mặt', NULL, '2026-10-05', '2026-10-08', 'returned', 'STORE_BT'),
    -- Demo for the Slack approval card: a recent delivered order whose refund stays under 10,000,000 so no CEO approval is needed first.
    ('DH1014', 'Huỳnh Phúc Hoàng Nhật', 'nhattin1425@gmail.com', 'P007', 1, 11990000, 200000, 11790000, 'chuyển khoản', NULL, '2026-10-28', '2026-10-30', 'delivered', 'STORE_Q1')
ON CONFLICT (id) DO UPDATE SET customer_email = EXCLUDED.customer_email;
