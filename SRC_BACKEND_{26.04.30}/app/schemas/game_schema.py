# app/schemas/game_schema.py

from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class OwnedCharacterSchema(BaseModel):
    id: str
    level: int
    exp: int


class EquippedAchievementResponse(BaseModel):
    achievement_code: str
    title: str
    description: Optional[str] = None


class AchievementResponse(BaseModel):
    achievement_code: str
    title: str
    description: Optional[str] = None
    is_equipped: bool
    acquired_at: Optional[str] = None


class BehaviorPublicSummary(BaseModel):
    preferred_styles: List[str] = Field(default_factory=list)
    avoided_styles: List[str] = Field(default_factory=list)
    difficulty_tendency: Dict[str, str] = Field(default_factory=dict)
    confidence: str = "low"
    top_preferred_types: List[str] = Field(default_factory=list)
    top_avoided_types: List[str] = Field(default_factory=list)
    recent_resolved_count: int = 0
    total_resolved_count: int = 0
    updated_at: Optional[str] = None


class GameProfileResponse(BaseModel):
    user_id: int
    nickname: Optional[str] = None
    game_nickname: Optional[str] = None

    level: int
    current_exp: int
    total_exp: int

    coins: int
    mission_coins: int

    has_created_character: bool
    selected_character_id: Optional[str] = None
    selected_background_id: Optional[str] = None
    equipped_badge_id: Optional[str] = None

    daily_free_regen_remaining: int
    daily_regen_date: Optional[str] = None
    active_missions_count: int

    owned_characters: List[OwnedCharacterSchema] = Field(default_factory=list)
    owned_background_ids: List[str] = Field(default_factory=list)

    equipped_achievement: Optional[EquippedAchievementResponse] = None
    completed_achievement_codes: List[str] = Field(default_factory=list)
    equipped_achievement_codes: List[str] = Field(default_factory=list)
    achievements: List[AchievementResponse] = Field(default_factory=list)

    total_missions_completed: int = 0
    total_coins_earned: int = 0
    total_purchases: int = 0

    adaptation_summary: Optional[BehaviorPublicSummary] = None

    next_level_required_exp: int
    can_level_up: bool
    character_stage: str
    max_level: int


class GameProfileEnvelope(BaseModel):
    ok: bool
    game_initialized: bool
    profile: Optional[GameProfileResponse] = None


class ResetDailyRegenResponse(BaseModel):
    ok: bool
    reset_applied: bool
    daily_free_regen_remaining: int
    daily_regen_date: Optional[str] = None
    profile: GameProfileResponse
