# app/models/user.py

from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Float,
    DateTime,
    Date,
    Boolean,
    Text,
    JSON,
    func,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class User(Base):
    """회원 정보 테이블"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    nickname = Column(String)
    exp = Column(Integer, default=0)
    birth_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    profile_image_data_url = Column(Text, nullable=True)
    image_permission_granted = Column(Boolean, default=False, nullable=False)
    image_permission_status = Column(String, nullable=True)

    inbody_records = relationship("UserInbody", back_populates="owner")
    missions = relationship("UserMission", back_populates="owner")
    activities = relationship("UserActivity", back_populates="owner")
    weight_histories = relationship("UserWeightHistory", back_populates="owner")

    # 게임 테이블 연결
    game_profile = relationship(
        "UserGameProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )


class UserInbody(Base):
    """기존 인바디 테이블"""
    __tablename__ = "user_inbody"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    name = Column(String, nullable=False)
    age = Column(Integer)
    gender = Column(String)
    height = Column(Float)
    weight = Column(Float)
    target_weight = Column(Float, nullable=True)
    body_fat = Column(Float)
    muscle_mass = Column(Float)
    goal = Column(String)
    bmi = Column(Float)
    bmr = Column(Float)
    source = Column(String, nullable=True, default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="inbody_records")


class UserMission(Base):
    """
    사용자별 AI 미션 저장 테이블
    기존 구조 + 2단계 구조 확장
    """
    __tablename__ = "user_missions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)

    # 기존 컬럼
    title = Column(String)
    content = Column(Text, nullable=False)
    reason = Column(Text)
    category = Column(String)
    difficulty = Column(String, nullable=True)
    is_completed = Column(Boolean, default=False)
    is_refreshed = Column(Boolean, default=False)

    # 2단계용 핵심 컬럼
    slot_code = Column(String, nullable=True)         # A / B / C
    mission_type = Column(String, nullable=True)      # A1_STEP_TARGET / B1_TIMER_STRETCH ...
    status = Column(String, default="active", nullable=False)  # active / in_progress / completed / refreshed

    params_json = Column(JSON, nullable=True)         # 목표 걸음수, 타이머 시간 등
    progress_json = Column(JSON, nullable=True)       # 현재 진행값

    reward_exp = Column(Integer, default=0, nullable=False)
    reward_coins = Column(Integer, default=0, nullable=False)

    generation_source = Column(String, nullable=True)  # initial / refresh / completed_regen
    validation_status = Column(String, default="approved", nullable=False)  # approved / rejected
    validation_reason = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # UserMission 안에 추가
    generation_provider = Column(String, default="unknown", nullable=False)
    # gpt / server_rebalance / server_fallback / unknown

    generation_attempt_count = Column(Integer, default=0, nullable=False)
    # GPT 호출/검수 시도 횟수

    fallback_reason = Column(Text, nullable=True)
    # fallback 또는 rebalance가 발생한 이유

    generation_meta_json = Column(JSON, nullable=True)
    # 디버깅용 상세 메타

    owner = relationship("User", back_populates="missions")


class UserActivity(Base):
    """웨어러블 기기에서 수집된 일일 활동 데이터"""
    __tablename__ = "user_activities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    steps = Column(Integer, default=0)
    calories = Column(Float, default=0.0)
    source = Column(String, nullable=True, default="manual")
    created_at = Column(DateTime, default=func.now())
    heart_rate = Column(Integer, nullable=True)
    sleep_minutes = Column(Integer, nullable=True)
    recorded_at = Column(DateTime, server_default=func.now())

    owner = relationship("User", back_populates="activities")


class UserWeightHistory(Base):
    """사용자 체중 변화 기록 테이블"""
    __tablename__ = "user_weight_histories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    weight = Column(Float, nullable=False)
    source = Column(String, nullable=True, default="manual")
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    owner = relationship("User", back_populates="weight_histories")


class MissionGenerationLog(Base):
    """
    GPT 미션 생성/검수/fallback 분석 로그
    - 발표/분석용 지표 계산 가능
    """
    __tablename__ = "mission_generation_logs"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    mission_id = Column(Integer, ForeignKey("user_missions.id", ondelete="SET NULL"), nullable=True, index=True)

    mode = Column(String, nullable=False)
    # initial / refresh / retry / complete_regen

    slot_code = Column(String, nullable=True)
    requested_count = Column(Integer, default=1, nullable=False)

    phase = Column(String, nullable=False)
    # initial / strict / relaxed / fallback / final

    attempt_no = Column(Integer, default=0, nullable=False)

    provider = Column(String, nullable=False)
    # gpt / server_rebalance / server_fallback

    outcome = Column(String, nullable=False)
    # approved / rejected / api_error / fallback_used / rebalance_used

    mission_type = Column(String, nullable=True)

    validation_status = Column(String, nullable=True)
    validation_reason = Column(Text, nullable=True)

    fallback_reason = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    raw_response_text = Column(Text, nullable=True)

    input_summary_json = Column(JSON, nullable=True)
    output_mission_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())