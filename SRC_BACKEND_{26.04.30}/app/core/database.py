# SQLAlchemy를 사용해 DB와 연결을 설정하고 세션을 생성

# app/core/database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency: API에서 DB 세션을 사용할 때 사용
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()