# app/core/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Gamified Fitness"

    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/fitness_db"
    PUBLIC_DATA_API_KEY: str = "default_key"
    KOSIS_API_KEY: str = ""
    OPENAI_API_KEY: str

    # 자동 로그인 / JWT
    SECRET_KEY: str = "your-secret-key-very-secure"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # Toss Payments
    TOSS_SECRET_KEY: str = ""
    ALLOW_MOCK_PAYMENTS: bool = False

    # AI 미션 생성 실험 설정
    # 기본값은 기존처럼 strict system prompt를 사용하는 안정 버전이다.
    # .env에서 AI_MISSION_SYSTEM_PROMPT_ENABLED=false 로 바꾸면
    # 같은 개인화 정책 payload를 유지한 채 system prompt만 제외하고 실험할 수 있다.
    AI_MISSION_SYSTEM_PROMPT_ENABLED: bool = True
    AI_MISSION_EXPERIMENT_VARIANT: str = "policy_engine_with_strict_prompt"

    class Config:
        env_file = ".env"


settings = Settings()