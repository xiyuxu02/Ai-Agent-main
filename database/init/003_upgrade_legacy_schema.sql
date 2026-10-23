SET NAMES utf8mb4;

-- Upgrade databases created by the original demo without breaking fresh installs.
SET @has_quantity = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'orders' AND column_name = 'quantity'
);
SET @sql = IF(
    @has_quantity = 0,
    'ALTER TABLE orders ADD COLUMN quantity INT UNSIGNED NOT NULL DEFAULT 1 AFTER product_name',
    'SELECT 1'
);
PREPARE migration_statement FROM @sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;

SET @has_idempotency_key = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'orders' AND column_name = 'idempotency_key'
);
SET @sql = IF(
    @has_idempotency_key = 0,
    'ALTER TABLE orders ADD COLUMN idempotency_key VARCHAR(64) NULL AFTER tracking_number',
    'SELECT 1'
);
PREPARE migration_statement FROM @sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;

SET @has_idempotency_index = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'orders'
      AND index_name = 'uq_orders_idempotency_key'
);
SET @sql = IF(
    @has_idempotency_index = 0,
    'ALTER TABLE orders ADD UNIQUE KEY uq_orders_idempotency_key (idempotency_key)',
    'SELECT 1'
);
PREPARE migration_statement FROM @sql;
EXECUTE migration_statement;
DEALLOCATE PREPARE migration_statement;

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
