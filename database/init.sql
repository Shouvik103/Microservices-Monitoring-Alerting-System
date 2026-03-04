-- ============================================================
-- Microservices Monitoring System — Database Schema
-- ============================================================

CREATE TABLE IF NOT EXISTS services (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    url             VARCHAR(2048) NOT NULL,
    check_interval  INTEGER NOT NULL DEFAULT 30,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    custom_headers  JSONB NOT NULL DEFAULT '{}',
    check_method    VARCHAR(10) NOT NULL DEFAULT 'GET' CHECK (check_method IN ('GET', 'POST', 'HEAD', 'TCP')),
    check_body      TEXT,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS health_checks (
    id               SERIAL PRIMARY KEY,
    service_id       INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    status           VARCHAR(10) NOT NULL CHECK (status IN ('UP', 'DOWN')),
    response_time_ms DOUBLE PRECISION,
    status_code      INTEGER,
    error_message    TEXT,
    checked_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    service_id  INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    alert_type  VARCHAR(20) NOT NULL CHECK (alert_type IN ('DOWN', 'SLOW', 'RECOVERED')),
    message     TEXT NOT NULL,
    sent_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS incidents (
    id           SERIAL PRIMARY KEY,
    service_id   INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    started_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMP WITH TIME ZONE,
    duration_s   INTEGER,
    status       VARCHAR(10) NOT NULL DEFAULT 'ongoing' CHECK (status IN ('ongoing', 'resolved'))
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_health_checks_service_id ON health_checks(service_id);
CREATE INDEX IF NOT EXISTS idx_health_checks_checked_at ON health_checks(checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_checks_service_checked ON health_checks(service_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_service_id ON alerts(service_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sent_at ON alerts(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_services_is_active ON services(is_active);
CREATE INDEX IF NOT EXISTS idx_services_tags ON services USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_incidents_service_id ON incidents(service_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_started_at ON incidents(started_at DESC);

-- ============================================================
-- Users (JWT authentication)
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(150) NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'editor', 'viewer')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- Default admin user  (password: admin123  — change in production!)
-- bcrypt hash of 'admin123'
INSERT INTO users (username, hashed_password, role)
VALUES ('admin', '$2b$12$N/.cEmbGqevX8l5BKrrBPujHvqJQuHntTh32DkhF.DAlDy9svDRZG', 'admin')
ON CONFLICT (username) DO NOTHING;

-- ============================================================
-- Custom Alert Rules (per-service thresholds)
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_rules (
    id              SERIAL PRIMARY KEY,
    service_id      INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    metric          VARCHAR(30) NOT NULL CHECK (metric IN ('response_time_ms', 'status_code', 'status')),
    operator        VARCHAR(5)  NOT NULL CHECK (operator IN ('>', '<', '>=', '<=', '==', '!=')),
    threshold       DOUBLE PRECISION NOT NULL,
    severity        VARCHAR(20) NOT NULL DEFAULT 'warning' CHECK (severity IN ('critical', 'warning', 'info')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    cooldown_s      INTEGER NOT NULL DEFAULT 300,
    description     TEXT,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_service ON alert_rules(service_id);
CREATE INDEX IF NOT EXISTS idx_alert_rules_active ON alert_rules(is_active);
