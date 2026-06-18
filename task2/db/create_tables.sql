DROP TABLE IF EXISTS report_user_prosthesis_mart;
DROP TABLE IF EXISTS prosthesis_telemetry;
DROP TABLE IF EXISTS crm_prostheses;
DROP TABLE IF EXISTS crm_clients;

CREATE TABLE crm_clients (
    user_id BIGINT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT,
    country_code TEXT
);

CREATE TABLE crm_prostheses (
    prosthesis_id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    model TEXT,
    production_status TEXT
);

CREATE TABLE prosthesis_telemetry (
    event_id BIGINT PRIMARY KEY,
    prosthesis_id BIGINT NOT NULL,
    event_time TIMESTAMP NOT NULL,
    response_time_ms NUMERIC(10, 2),
    battery_level NUMERIC(10, 2),
    movement_type TEXT,
    is_error BOOLEAN DEFAULT FALSE
);

CREATE TABLE report_user_prosthesis_mart (
    user_id BIGINT NOT NULL,
    prosthesis_id BIGINT NOT NULL,
    user_full_name TEXT,
    email TEXT,
    country_code TEXT,
    prosthesis_model TEXT,
    report_date DATE NOT NULL,

    telemetry_events_count BIGINT,
    avg_response_time_ms NUMERIC(10, 2),
    max_response_time_ms NUMERIC(10, 2),
    avg_battery_level NUMERIC(10, 2),
    min_battery_level NUMERIC(10, 2),
    total_movements BIGINT,
    error_events_count BIGINT,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (user_id, prosthesis_id, report_date)
);

CREATE INDEX idx_report_user_id
    ON report_user_prosthesis_mart(user_id);

CREATE INDEX idx_report_user_date
    ON report_user_prosthesis_mart(user_id, report_date);

CREATE INDEX idx_report_prosthesis_id
    ON report_user_prosthesis_mart(prosthesis_id);