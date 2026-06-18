import os
from datetime import date
from typing import List, Optional

import jwt
import psycopg2
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from jwt import PyJWKClient
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel


app = FastAPI(
    title="BionicPRO Reports API",
    description="API для получения подготовленных отчётов по работе протезов",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "airflow")
DB_USER = os.getenv("DB_USER", "airflow")
DB_PASSWORD = os.getenv("DB_PASSWORD", "airflow")

KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "reports-realm")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "reports-frontend")

KEYCLOAK_ISSUER = os.getenv(
    "KEYCLOAK_ISSUER",
    f"http://localhost:8080/realms/{KEYCLOAK_REALM}",
)

KEYCLOAK_JWKS_URL = os.getenv(
    "KEYCLOAK_JWKS_URL",
    f"http://host.docker.internal:8080/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs",
)

jwks_client = PyJWKClient(KEYCLOAK_JWKS_URL)


class ReportItem(BaseModel):
    user_id: int
    prosthesis_id: int
    user_full_name: Optional[str]
    email: Optional[str]
    country_code: Optional[str]
    prosthesis_model: Optional[str]
    report_date: str
    telemetry_events_count: int
    avg_response_time_ms: Optional[float]
    max_response_time_ms: Optional[float]
    avg_battery_level: Optional[float]
    min_battery_level: Optional[float]
    total_movements: int
    error_events_count: int
    updated_at: str


class CurrentUser(BaseModel):
    keycloak_subject: str
    email: Optional[str]
    preferred_username: Optional[str]
    user_id: int


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def decode_token(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization header должен быть в формате Bearer token",
        )

    token = authorization.replace("Bearer ", "")

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_ISSUER,
            options={
                "verify_aud": False,
            },
        )

        token_client_id = payload.get("azp")
        if token_client_id and token_client_id != KEYCLOAK_CLIENT_ID:
            raise HTTPException(
                status_code=401,
                detail="Токен выпущен не для ожидаемого клиента",
            )

        return payload

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=401,
            detail=f"Невалидный access token: {str(error)}",
        )


def get_current_user(payload: dict = Depends(decode_token)) -> CurrentUser:
    email = payload.get("email")
    preferred_username = payload.get("preferred_username")
    subject = payload.get("sub")

    if not subject:
        raise HTTPException(
            status_code=401,
            detail="В токене отсутствует subject пользователя",
        )

    if not email and not preferred_username:
        raise HTTPException(
            status_code=401,
            detail="В токене отсутствуют email и preferred_username",
        )

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT user_id
                    FROM crm_clients
                    WHERE email = %s
                       OR email = %s
                    LIMIT 1;
                    """,
                    (email, preferred_username),
                )
                row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=403,
                detail="Пользователь из токена не найден в CRM",
            )

        return CurrentUser(
            keycloak_subject=subject,
            email=email,
            preferred_username=preferred_username,
            user_id=row["user_id"],
        )

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при поиске пользователя в CRM: {str(error)}",
        )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/reports", response_model=List[ReportItem])
def get_reports(
    requested_user_id: Optional[int] = Query(
        None,
        alias="user_id",
        description="Опциональный ID пользователя. Если передан, должен совпадать с пользователем из токена.",
    ),
    prosthesis_id: Optional[int] = Query(
        None,
        description="ID протеза, если нужен отчёт по конкретному протезу",
    ),
    date_from: Optional[date] = Query(
        None,
        description="Начало периода отчёта. Формат: YYYY-MM-DD",
    ),
    date_to: Optional[date] = Query(
        None,
        description="Конец периода отчёта. Формат: YYYY-MM-DD",
    ),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Возвращает подготовленный отчёт только для текущего пользователя.

    user_id определяется из access token.
    Клиент не может получить отчёт другого пользователя.
    API читает только готовую витрину report_user_prosthesis_mart.
    Если за указанный период данных нет, значит этот период ещё не обработан Airflow
    или по нему отсутствует телеметрия.
    """

    if requested_user_id is not None and requested_user_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="Доступ к отчёту другого пользователя запрещён",
        )

    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=400,
            detail="date_from не может быть больше date_to",
        )

    query = """
        SELECT
            user_id,
            prosthesis_id,
            user_full_name,
            email,
            country_code,
            prosthesis_model,
            report_date::text,
            telemetry_events_count,
            avg_response_time_ms,
            max_response_time_ms,
            avg_battery_level,
            min_battery_level,
            total_movements,
            error_events_count,
            updated_at::text
        FROM report_user_prosthesis_mart
        WHERE user_id = %s
    """

    params = [current_user.user_id]

    if prosthesis_id is not None:
        query += " AND prosthesis_id = %s"
        params.append(prosthesis_id)

    if date_from is not None:
        query += " AND report_date >= %s"
        params.append(date_from)

    if date_to is not None:
        query += " AND report_date <= %s"
        params.append(date_to)

    query += " ORDER BY report_date DESC, prosthesis_id"

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()

        if not rows:
            if date_from is not None or date_to is not None:
                raise HTTPException(
                    status_code=404,
                    detail="Отчёт за указанный период ещё не подготовлен Airflow или данные за этот период отсутствуют",
                )

            raise HTTPException(
                status_code=404,
                detail="Отчёты текущего пользователя не найдены",
            )

        return rows

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении отчёта: {str(error)}",
        )