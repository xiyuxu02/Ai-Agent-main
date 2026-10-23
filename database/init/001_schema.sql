SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS orders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id VARCHAR(32) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    quantity INT UNSIGNED NOT NULL DEFAULT 1,
    amount DECIMAL(12, 2) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT '处理中',
    create_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    delivery_time DATETIME(6) NULL,
    express_company VARCHAR(128) NULL,
    tracking_number VARCHAR(64) NULL,
    idempotency_key VARCHAR(64) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_orders_order_id (order_id),
    UNIQUE KEY uq_orders_idempotency_key (idempotency_key),
    KEY idx_orders_user_created (user_id, create_time),
    KEY idx_orders_status (status),
    KEY idx_orders_tracking_number (tracking_number),
    CONSTRAINT chk_orders_quantity CHECK (quantity BETWEEN 1 AND 99),
    CONSTRAINT chk_orders_amount CHECK (amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS logistics_tracking (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id VARCHAR(32) NULL,
    tracking_number VARCHAR(64) NOT NULL,
    tracking_time DATETIME(6) NOT NULL,
    location VARCHAR(255) NOT NULL,
    status VARCHAR(64) NOT NULL,
    description VARCHAR(500) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_tracking_event (tracking_number, tracking_time, status),
    KEY idx_tracking_number_time (tracking_number, tracking_time),
    KEY idx_tracking_order_id (order_id),
    CONSTRAINT fk_tracking_order
        FOREIGN KEY (order_id) REFERENCES orders (order_id)
        ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id VARCHAR(32) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(128) NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    create_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    update_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (ticket_id),
    KEY idx_tickets_user_created (user_id, create_time),
    KEY idx_tickets_conversation (conversation_id),
    KEY idx_tickets_status_priority (status, priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS pending_actions (
    action_token VARCHAR(36) NOT NULL,
    conversation_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    action_type VARCHAR(32) NOT NULL,
    payload_json JSON NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    created_request_id VARCHAR(64) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at DATETIME(6) NOT NULL,
    result_ref VARCHAR(128) NULL,
    PRIMARY KEY (action_token),
    KEY idx_pending_actions_lookup (conversation_id, action_type, status),
    KEY idx_pending_actions_user_status (user_id, status),
    KEY idx_pending_actions_expiry (status, expires_at),
    KEY idx_pending_actions_request (created_request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
