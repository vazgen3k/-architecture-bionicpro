Перед запуском пайплайна необходимо настроить соединение 

Подключаем Airflow к PostgreSQL — заходим в Admin→ Connections.
Нажимаем Add new record, заполняем и сохраняем данные.

Connection Id  - write_to_postgres
Connection Type  - Postgres
Host - postgres
Database - airflow
Login - airflow
Password - airflow
Port - 5432