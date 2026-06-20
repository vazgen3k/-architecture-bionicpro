from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from datetime import datetime
import csv
import os


default_args = {
    "owner": "airflow",
    "start_date": datetime(2024, 12, 1),
}


BASE_INPUT_DIR = "/opt/airflow/sample_files"
SQL_OUTPUT_DIR = "/opt/airflow/dags/sql"
CREATE_TABLES_SQL = "/opt/airflow/db/create_tables.sql"


def sql_text(value):
    if value is None or value == "":
        return "NULL"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def generate_insert_queries():
    insert_queries = []

    clients_csv = os.path.join(BASE_INPUT_DIR, "crm_clients.csv")
    with open(clients_csv, "r", encoding="utf-8") as csvfile:
        csvreader = csv.DictReader(csvfile)
        for row in csvreader:
            insert_queries.append(
                "INSERT INTO crm_clients (user_id, full_name, email, country_code) "
                f"VALUES ({row['user_id']}, {sql_text(row['full_name'])}, {sql_text(row['email'])}, {sql_text(row['country_code'])});"
            )

    prostheses_csv = os.path.join(BASE_INPUT_DIR, "crm_prostheses.csv")
    with open(prostheses_csv, "r", encoding="utf-8") as csvfile:
        csvreader = csv.DictReader(csvfile)
        for row in csvreader:
            insert_queries.append(
                "INSERT INTO crm_prostheses (prosthesis_id, user_id, model, production_status) "
                f"VALUES ({row['prosthesis_id']}, {row['user_id']}, {sql_text(row['model'])}, {sql_text(row['production_status'])});"
            )

    telemetry_csv = os.path.join(BASE_INPUT_DIR, "prosthesis_telemetry.csv")
    with open(telemetry_csv, "r", encoding="utf-8") as csvfile:
        csvreader = csv.DictReader(csvfile)
        for row in csvreader:
            insert_queries.append(
                "INSERT INTO prosthesis_telemetry "
                "(event_id, prosthesis_id, event_time, response_time_ms, battery_level, movement_type, is_error) "
                f"VALUES ({row['event_id']}, {row['prosthesis_id']}, "
                f"{sql_text(row['event_time'])}, {row['response_time_ms']}, {row['battery_level']}, "
                f"{sql_text(row['movement_type'])}, {row['is_error']});"
            )

    output_file = os.path.join(SQL_OUTPUT_DIR, "insert_queries.sql")
    with open(output_file, "w", encoding="utf-8") as f:
        for query in insert_queries:
            f.write(f"{query}\n")


def generate_refresh_mart_query():
    query = """
TRUNCATE TABLE report_user_prosthesis_mart;

INSERT INTO report_user_prosthesis_mart (
    user_id,
    prosthesis_id,
    user_full_name,
    email,
    country_code,
    prosthesis_model,
    report_date,
    telemetry_events_count,
    avg_response_time_ms,
    max_response_time_ms,
    avg_battery_level,
    min_battery_level,
    total_movements,
    error_events_count,
    updated_at
)
SELECT
    c.user_id,
    p.prosthesis_id,
    c.full_name AS user_full_name,
    c.email,
    c.country_code,
    p.model AS prosthesis_model,
    DATE(t.event_time) AS report_date,

    COUNT(*) AS telemetry_events_count,
    ROUND(AVG(t.response_time_ms), 2) AS avg_response_time_ms,
    MAX(t.response_time_ms) AS max_response_time_ms,
    ROUND(AVG(t.battery_level), 2) AS avg_battery_level,
    MIN(t.battery_level) AS min_battery_level,
    COUNT(t.movement_type) AS total_movements,
    SUM(CASE WHEN t.is_error THEN 1 ELSE 0 END) AS error_events_count,
    CURRENT_TIMESTAMP AS updated_at
FROM prosthesis_telemetry t
JOIN crm_prostheses p
    ON p.prosthesis_id = t.prosthesis_id
JOIN crm_clients c
    ON c.user_id = p.user_id
GROUP BY
    c.user_id,
    p.prosthesis_id,
    c.full_name,
    c.email,
    c.country_code,
    p.model,
    DATE(t.event_time);
"""

    output_file = os.path.join(SQL_OUTPUT_DIR, "refresh_reports_mart.sql")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(query)


with DAG(
    dag_id="prepare_reports_mart_dag",
    default_args=default_args,
    schedule="0 * * * *",
    catchup=False,
    tags=["bionicpro", "etl", "reports"],
    template_searchpath=[
        "/opt/airflow/db",
        "/opt/airflow/dags/sql",
    ],
) as dag:

    create_tables = SQLExecuteQueryOperator(
        task_id="create_tables",
        conn_id="write_to_postgres",
        sql="create_tables.sql",
    )

    generate_insert_sql = PythonOperator(
        task_id="generate_insert_sql",
        python_callable=generate_insert_queries,
    )

    run_insert_sql = SQLExecuteQueryOperator(
        task_id="run_insert_sql",
        conn_id="write_to_postgres",
        sql="insert_queries.sql",
    )

    generate_mart_sql = PythonOperator(
        task_id="generate_mart_sql",
        python_callable=generate_refresh_mart_query,
    )

    refresh_reports_mart = SQLExecuteQueryOperator(
        task_id="refresh_reports_mart",
        conn_id="write_to_postgres",
        sql="refresh_reports_mart.sql",
    )

    create_tables >> generate_insert_sql >> run_insert_sql >> generate_mart_sql >> refresh_reports_mart