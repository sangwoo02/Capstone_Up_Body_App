# app/core/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Gamified Fitness"

    DATABASE_URL: str = ""
    PUBLIC_DATA_API_KEY: str = "default_key"
    KOSIS_API_KEY: str = ""
    OPENAI_API_KEY: str

    # 자동 로그인 / JWT
    SECRET_KEY: str = ""
    ALGORITHM: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # Toss Payments
    TOSS_SECRET_KEY: str = ""
    ALLOW_MOCK_PAYMENTS: bool = False

    class Config:
        env_file = ".env"


settings = Settings()