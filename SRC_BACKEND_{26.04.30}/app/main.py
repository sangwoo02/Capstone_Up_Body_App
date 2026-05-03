# app/main.py
# 개발자 : 박상우, 장서빈, 오유나, 조병진
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text as sql_text

from app.core.database import engine, Base
from app.models import user, game
from app.api import auth, missions, healthcare, week_walk, payments
from app.api import game as game_api

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
# httpx 기본 INFO 로그는 전체 요청 URL을 찍을 수 있어 serviceKey 노출 위험이 있다.
# 공공데이터 호출 여부는 app.services.public_api의 마스킹 로그로 확인한다.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

Base.metadata.create_all(bind=engine)


def ensure_runtime_schema():
    """
    기존 users 테이블에 새 프로필 컬럼이 없을 때 자동으로 추가한다.
    create_all()은 이미 존재하는 테이블에 새 컬럼을 추가하지 않으므로 별도 보정이 필요하다.
    """
    inspector = inspect(engine)

    if "users" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("users")
    }

    dialect = engine.dialect.name
    statements = []

    def add_column(column_name: str, postgres_type: str, fallback_type: str):
        if column_name in existing_columns:
            return

        if dialect == "postgresql":
            statements.append(
                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column_name} {postgres_type}"
            )
        else:
            statements.append(
                f"ALTER TABLE users ADD COLUMN {column_name} {fallback_type}"
            )

    add_column(
        "created_at",
        "TIMESTAMPTZ DEFAULT NOW()",
        "DATETIME",
    )

    add_column(
        "profile_image_data_url",
        "TEXT",
        "TEXT",
    )

    add_column(
        "image_permission_granted",
        "BOOLEAN NOT NULL DEFAULT FALSE",
        "BOOLEAN DEFAULT 0",
    )

    add_column(
        "image_permission_status",
        "VARCHAR(30) DEFAULT 'unknown'",
        "VARCHAR(30) DEFAULT 'unknown'",
    )

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(sql_text(statement))

        if dialect == "postgresql":
            cleanup_statements = [
                "UPDATE users SET created_at = NOW() WHERE created_at IS NULL",
                "UPDATE users SET image_permission_granted = FALSE WHERE image_permission_granted IS NULL",
                "UPDATE users SET image_permission_status = 'unknown' WHERE image_permission_status IS NULL",
            ]
        else:
            cleanup_statements = [
                "UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL",
                "UPDATE users SET image_permission_granted = 0 WHERE image_permission_granted IS NULL",
                "UPDATE users SET image_permission_status = 'unknown' WHERE image_permission_status IS NULL",
            ]

        for statement in cleanup_statements:
            connection.execute(sql_text(statement))


try:
    ensure_runtime_schema()
except Exception:
    logging.exception("users 테이블 런타임 스키마 보정 실패")
    raise


app = FastAPI(
    description="Inbody 데이터 기반 AI 운동 미션 제공 서비스",
    title="Gamified Fitness Challenge API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(missions.router)
app.include_router(healthcare.router)
app.include_router(game_api.router)
app.include_router(week_walk.router)
app.include_router(payments.router)


@app.get("/")
def read_root():
    return {"message": "DB가 연동된 API 서버입니다."}