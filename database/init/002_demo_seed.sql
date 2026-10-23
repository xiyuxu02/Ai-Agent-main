SET NAMES utf8mb4;

INSERT IGNORE INTO orders (
    order_id,
    user_id,
    product_name,
    quantity,
    amount,
    status,
    create_time,
    delivery_time,
    express_company,
    tracking_number,
    idempotency_key
) VALUES
    (
        'ORD2026001',
        'USER001',
        '无线蓝牙耳机',
        1,
        299.00,
        '已发货',
        '2026-09-20 02:00:00',
        NULL,
        '顺丰速运',
        'SF2026001001',
        'demo-order-2026001'
    ),
    (
        'ORD2026002',
        'USER001',
        '智能手环',
        1,
        199.00,
        '处理中',
        '2026-09-22 03:30:00',
        NULL,
        NULL,
        NULL,
        'demo-order-2026002'
    ),
    (
        'ORD2026003',
        'USER001',
        '移动电源',
        2,
        258.00,
        '已完成',
        '2026-09-10 06:00:00',
        '2026-09-13 08:15:00',
        '中通快递',
        'ZT2026003001',
        'demo-order-2026003'
    );

INSERT IGNORE INTO logistics_tracking (
    order_id,
    tracking_number,
    tracking_time,
    location,
    status,
    description
) VALUES
    (
        'ORD2026001',
        'SF2026001001',
        '2026-09-20 04:20:00',
        '上海市浦东新区',
        '已揽收',
        '快件已由顺丰速运揽收'
    ),
    (
        'ORD2026001',
        'SF2026001001',
        '2026-09-21 01:10:00',
        '上海转运中心',
        '运输中',
        '快件已到达上海转运中心'
    ),
    (
        'ORD2026001',
        'SF2026001001',
        '2026-09-22 00:45:00',
        '杭州市余杭区',
        '派送中',
        '快件正在派送，请保持电话畅通'
    ),
    (
        'ORD2026003',
        'ZT2026003001',
        '2026-09-13 08:15:00',
        '杭州市西湖区',
        '已签收',
        '快件已由本人签收'
    );
