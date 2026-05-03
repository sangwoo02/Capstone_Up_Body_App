# app/models/game.py

from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    DateTime,
    Boolean,
    UniqueConstraint,
    JSON,
    func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserGameProfile(Base):
    """
    사용자 게임 메인 프로필
    - 레벨/경험치/코인/미션코인
    - 캐릭터 최초 생성 여부
    - 현재 장착 캐릭터/배경
    - 일일 무료 재생성 횟수 관리
    """
    __tablename__ = "user_game_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    level = Column(Integer, default=1, nullable=False)
    current_exp = Column(Integer, default=0, nullable=False)
    total_exp = Column(Integer, default=0, nullable=False)

    total_missions_completed = Column(Integer, default=0, nullable=False)
    total_coins_earned = Column(Integer, default=0, nullable=False)
    total_purchases = Column(Integer, default=0, nullable=False)

    coins = Column(Integer, default=0, nullable=False)
    mission_coins = Column(Integer, default=0, nullable=False)

    has_created_character = Column(Boolean, default=False, nullable=False)

    selected_character_id = Column(String, nullable=True)
    selected_background_id = Column(String, nullable=True)
    equipped_badge_id = Column(String, nullable=True)
    game_nickname = Column(String, nullable=True)

    week_walk_score = Column(Integer, default=0, nullable=False)
    week_walk_tier = Column(String, default="브론즈", nullable=False)

    daily_free_regen_remaining = Column(Integer, default=3, nullable=False)
    daily_regen_date = Column(String, nullable=True)  # "2026-03-29" 형식 저장

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="game_profile")
    owned_characters = relationship(
        "UserOwnedCharacter",
        back_populates="game_profile",
        cascade="all, delete-orphan"
    )
    owned_backgrounds = relationship(
        "UserOwnedBackground",
        back_populates="game_profile",
        cascade="all, delete-orphan"
    )
    achievements = relationship(
        "UserAchievement",
        back_populates="game_profile",
        cascade="all, delete-orphan"
    )


class UserOwnedCharacter(Base):
    """
    사용자가 보유한 캐릭터 목록
    """
    __tablename__ = "user_owned_characters"
    __table_args__ = (
        UniqueConstraint("user_game_profile_id", "character_id", name="uq_user_owned_character"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_game_profile_id = Column(Integer, ForeignKey("user_game_profiles.id", ondelete="CASCADE"), nullable=False, index=True)

    character_id = Column(String, nullable=False)
    is_equipped = Column(Boolean, default=False, nullable=False)
    acquired_at = Column(DateTime(timezone=True), server_default=func.now())

    game_profile = relationship("UserGameProfile", back_populates="owned_characters")
    level = Column(Integer, default=1, nullable=False)
    current_exp = Column(Integer, default=0, nullable=False)


class UserOwnedBackground(Base):
    """
    사용자가 보유한 배경 목록
    """
    __tablename__ = "user_owned_backgrounds"
    __table_args__ = (
        UniqueConstraint("user_game_profile_id", "background_id", name="uq_user_owned_background"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_game_profile_id = Column(Integer, ForeignKey("user_game_profiles.id", ondelete="CASCADE"), nullable=False, index=True)

    background_id = Column(String, nullable=False)
    is_equipped = Column(Boolean, default=False, nullable=False)
    acquired_at = Column(DateTime(timezone=True), server_default=func.now())

    game_profile = relationship("UserGameProfile", back_populates="owned_backgrounds")


class UserAchievement(Base):
    """
    사용자가 획득한 업적/훈장
    """
    __tablename__ = "user_achievements"
    __table_args__ = (
        UniqueConstraint("user_game_profile_id", "achievement_code", name="uq_user_achievement"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_game_profile_id = Column(Integer, ForeignKey("user_game_profiles.id", ondelete="CASCADE"), nullable=False, index=True)

    achievement_code = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)

    is_equipped = Column(Boolean, default=False, nullable=False)
    acquired_at = Column(DateTime(timezone=True), server_default=func.now())

    game_profile = relationship("UserGameProfile", back_populates="achievements")


class UserMissionBehaviorProfile(Base):
    """
    사용자 미션 성향 프로필
    - 최근/누적 미션 해결 이력을 바탕으로 계산한 적응 데이터 영속화
    - GPT 생성, 서버 fallback, game/profile 요약 응답에서 재사용
    """
    __tablename__ = "user_mission_behavior_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    behavior_version = Column(Integer, default=2, nullable=False)
    recent_window_size = Column(Integer, default=12, nullable=False)

    recent_resolved_count = Column(Integer, default=0, nullable=False)
    total_resolved_count = Column(Integer, default=0, nullable=False)
    adaptation_confidence = Column(String, default="low", nullable=False)

    preferred_slot_a_types = Column(JSON, nullable=True)
    preferred_slot_b_types = Column(JSON, nullable=True)
    preferred_slot_c_types = Column(JSON, nullable=True)

    discouraged_slot_a_types = Column(JSON, nullable=True)
    discouraged_slot_b_types = Column(JSON, nullable=True)
    discouraged_slot_c_types = Column(JSON, nullable=True)

    slot_a_difficulty_bias = Column(String, default="neutral", nullable=False)
    slot_b_difficulty_bias = Column(String, default="neutral", nullable=False)
    slot_c_difficulty_bias = Column(String, default="neutral", nullable=False)

    recent_summary_json = Column(JSON, nullable=True)
    cumulative_summary_json = Column(JSON, nullable=True)
    type_scores_json = Column(JSON, nullable=True)
    effective_behavior_json = Column(JSON, nullable=True)
    adaptation_summary_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WeekWalkSeason(Base):
    """
    Week Walk 시즌 테이블
    - weekly: 주간 걸음수 시즌
    - score: 2달 점수 시즌
    """
    __tablename__ = "week_walk_seasons"
    __table_args__ = (
        UniqueConstraint("season_type", "start_at", name="uq_week_walk_season_type_start"),
    )

    id = Column(Integer, primary_key=True, index=True)
    season_type = Column(String, nullable=False)  # weekly / score

    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False, index=True)

    is_settled = Column(Boolean, default=False, nullable=False)
    settled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WeekWalkWeeklyParticipant(Base):
    """
    주간 시즌 참가자
    - 이번 주 Week Walk 참가 여부
    """
    __tablename__ = "week_walk_weekly_participants"
    __table_args__ = (
        UniqueConstraint("season_id", "user_game_profile_id", name="uq_week_walk_weekly_participant"),
    )

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, ForeignKey("week_walk_seasons.id", ondelete="CASCADE"), nullable=False, index=True)
    user_game_profile_id = Column(Integer, ForeignKey("user_game_profiles.id", ondelete="CASCADE"), nullable=False, index=True)

    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PaymentOrder(Base):
    """
    토스 결제 주문 기록
    - 결제 전 READY
    - 토스 승인 성공 후 PAID
    - 실패 시 FAILED
    """
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    order_id = Column(String(64), unique=True, nullable=False, index=True)
    package_id = Column(String(50), nullable=False)

    order_name = Column(String(100), nullable=False)
    amount = Column(Integer, nullable=False)
    coupon_amount = Column(Integer, nullable=False)

    status = Column(String(20), default="READY", nullable=False)

    payment_key = Column(String(200), unique=True, nullable=True)
    payment_method = Column(String(50), nullable=True)

    raw_response_json = Column(JSON, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )