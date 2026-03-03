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

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_health_checks_service_id ON health_checks(service_id);
CREATE INDEX IF NOT EXISTS idx_health_checks_checked_at ON health_checks(checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_checks_service_checked ON health_checks(service_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_service_id ON alerts(service_id);
CREATE INDEX IF NOT EXISTS idx_alerts_sent_at ON alerts(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_services_is_active ON services(is_active);
CREATE INDEX IF NOT EXISTS idx_services_tags ON services USING GIN(tags);
