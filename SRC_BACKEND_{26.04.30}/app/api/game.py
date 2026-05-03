# app/api/game.py

from typing import Any, Dict, Optional

from app.services.game_catalog import (
    CHARACTER_CATALOG,
    BACKGROUND_CATALOG,
    get_character_price,
    get_background_price,
    is_starter_character,
    is_starter_background,
    is_valid_character_id,
    is_valid_background_id,
    get_game_nickname_change_price,
)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.config import settings

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User, UserMission
from app.models.game import (
    UserGameProfile,
    UserOwnedCharacter,
    UserOwnedBackground,
    UserAchievement,
)
from app.services.mission_behavior_service import (
    get_public_behavior_summary,
    ensure_user_behavior_profile,
)

import re
from sqlalchemy import func

from app.services.achievement_service import (
    evaluate_and_grant_achievements,
    get_user_achievements,
    get_completed_achievement_codes,
    get_equipped_achievement_codes,
    serialize_achievement,
    evaluate_and_grant_achievements
)

router = APIRouter(prefix="/game", tags=["Game"])



# -----------------------------
# request models
# -----------------------------
class InitializeCharacterRequest(BaseModel):
    character_id: str = Field(..., min_length=1, max_length=100)
    background_id: str = Field(..., min_length=1, max_length=100)


class PurchaseCharacterRequest(BaseModel):
    character_id: str = Field(..., min_length=1, max_length=100)


class PurchaseBackgroundRequest(BaseModel):
    background_id: str = Field(..., min_length=1, max_length=100)


class EquipCharacterRequest(BaseModel):
    character_id: str = Field(..., min_length=1, max_length=100)


class EquipBackgroundRequest(BaseModel):
    background_id: str = Field(..., min_length=1, max_length=100)

class UpdateGameNicknameRequest(BaseModel):
    game_nickname: str = Field(..., min_length=2, max_length=5)
    consume_coins: bool = False

class CheckGameNicknameRequest(BaseModel):
    game_nickname: str = Field(..., min_length=2, max_length=5)

class EquipAchievementsRequest(BaseModel):
    achievement_codes: list[str] = Field(default_factory=list)

class PurchaseMissionCoinsRequest(BaseModel):
    package_id: str

# -----------------------------
# helpers
# -----------------------------
def get_today_kst_str():
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def ensure_game_profile(db: Session, user_id: int) -> UserGameProfile:
    """
    유저의 게임 프로필이 없으면 자동 생성
    """
    profile = (
        db.query(UserGameProfile)
        .filter(UserGameProfile.user_id == user_id)
        .first()
    )

    if profile:
        return profile

    profile = UserGameProfile(
        user_id=user_id,
        level=1,
        current_exp=0,
        total_exp=0,
        coins=0,
        mission_coins=0,
        has_created_character=False,
        selected_character_id=None,
        selected_background_id=None,
        equipped_badge_id=None,
        daily_free_regen_remaining=3,
        daily_regen_date=get_today_kst_str(),
        total_missions_completed=0,
        total_coins_earned=0,
        total_purchases=0,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def get_existing_game_profile(db: Session, user_id: int) -> UserGameProfile:
    profile = (
        db.query(UserGameProfile)
        .filter(UserGameProfile.user_id == user_id)
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="게임 프로필이 없습니다. 먼저 AI 미션을 생성해주세요."
        )
    return profile


def reset_daily_regen_if_needed_internal(profile: UserGameProfile) -> bool:
    """
    날짜가 바뀌었으면 무료 재생성 횟수를 3으로 복구.
    절대 3을 넘기지 않음.
    """
    today_str = get_today_kst_str()

    # 첫 접근 시 날짜 세팅
    if not profile.daily_regen_date:
        profile.daily_regen_date = today_str
        if profile.daily_free_regen_remaining is None:
            profile.daily_free_regen_remaining = 3
        profile.daily_free_regen_remaining = min(profile.daily_free_regen_remaining, 3)
        return True

    # 날짜가 바뀌었으면 무조건 3으로 리셋
    if profile.daily_regen_date != today_str:
        profile.daily_regen_date = today_str
        profile.daily_free_regen_remaining = 3
        return True

    # 같은 날이면 혹시 이상치가 있어도 최대 3으로 보정
    if profile.daily_free_regen_remaining is None:
        profile.daily_free_regen_remaining = 3
        return True

    if profile.daily_free_regen_remaining > 3:
        profile.daily_free_regen_remaining = 3
        return True

    if profile.daily_free_regen_remaining < 0:
        profile.daily_free_regen_remaining = 0
        return True

    return False


def validate_character_id(character_id: str):
    if not is_valid_character_id(character_id):
        raise HTTPException(status_code=400, detail="유효하지 않은 캐릭터 ID입니다.")


def validate_background_id(background_id: str):
    if not is_valid_background_id(background_id):
        raise HTTPException(status_code=400, detail="유효하지 않은 배경 ID입니다.")


def require_character_created(profile: UserGameProfile):
    if not profile.has_created_character:
        raise HTTPException(
            status_code=400,
            detail="먼저 캐릭터를 생성해야 합니다."
        )

GAME_NICKNAME_PATTERN = re.compile(r"^[A-Za-z가-힣]{2,5}$")

def normalize_game_nickname(game_nickname: Optional[str]) -> Optional[str]:
    if game_nickname is None:
        return None

    cleaned = game_nickname.strip()

    if cleaned == "":
        return None

    if len(cleaned) < 2:
        raise HTTPException(status_code=400, detail="게임 닉네임은 2자 이상이어야 합니다.")

    if len(cleaned) > 5:
        raise HTTPException(status_code=400, detail="게임 닉네임은 5자 이하여야 합니다.")

    # 한글/영문만 허용
    if not GAME_NICKNAME_PATTERN.fullmatch(cleaned):
        raise HTTPException(
            status_code=400,
            detail="게임 닉네임은 한글 또는 영어만 사용 가능하며, 공백/특수문자는 사용할 수 없습니다."
        )

    return cleaned


def normalize_game_nickname_for_compare(game_nickname: str) -> str:
    # 영어는 대소문자 구분 없이 중복 처리
    # 한글은 lower() 영향 없음
    return game_nickname.strip().lower()

def is_game_nickname_taken(
    db: Session,
    game_nickname: str,
    exclude_profile_id: Optional[int] = None,
) -> bool:
    normalized = normalize_game_nickname_for_compare(game_nickname)

    query = db.query(UserGameProfile).filter(
        func.lower(func.trim(UserGameProfile.game_nickname)) == normalized
    )

    if exclude_profile_id is not None:
        query = query.filter(UserGameProfile.id != exclude_profile_id)

    return db.query(query.exists()).scalar()

# -----------------------------
# level-up helpers
# -----------------------------
MAX_LEVEL = 10


def get_required_exp_for_level(level: int) -> int:
    """
    현재 레벨에서 다음 레벨로 올라가기 위해 필요한 EXP
    Lv1 -> 100
    Lv2 -> 150
    Lv3 -> 200
    ...
    """
    if level < 1:
        level = 1
    return 100 + (level - 1) * 50


def get_character_stage(level: int) -> str:
    """
    캐릭터 성장 단계 표시용
    프론트에서 필요하면 stage별 이미지/연출 연결 가능
    """
    if level >= 10:
        return "final"
    if level >= 7:
        return "advanced"
    if level >= 4:
        return "middle"
    return "basic"


def build_level_meta(profile: UserGameProfile) -> dict:
    """
    프론트에서 바로 쓸 수 있는 레벨업 메타 정보
    """
    level = profile.level or 1
    current_exp = profile.current_exp or 0

    if level >= MAX_LEVEL:
        return {
            "next_level_required_exp": 0,
            "can_level_up": False,
            "character_stage": get_character_stage(level),
            "max_level": MAX_LEVEL,
        }

    required_exp = get_required_exp_for_level(level)

    return {
        "next_level_required_exp": required_exp,
        "can_level_up": current_exp >= required_exp,
        "character_stage": get_character_stage(level),
        "max_level": MAX_LEVEL,
    }


def is_character_owned(db: Session, profile_id: int, character_id: str) -> bool:
    return (
        db.query(UserOwnedCharacter)
        .filter(UserOwnedCharacter.user_game_profile_id == profile_id)
        .filter(UserOwnedCharacter.character_id == character_id)
        .first()
        is not None
    )


def is_background_owned(db: Session, profile_id: int, background_id: str) -> bool:
    return (
        db.query(UserOwnedBackground)
        .filter(UserOwnedBackground.user_game_profile_id == profile_id)
        .filter(UserOwnedBackground.background_id == background_id)
        .first()
        is not None
    )


def equip_character_internal(db: Session, profile: UserGameProfile, character_id: str):
    validate_character_id(character_id)

    owned = (
        db.query(UserOwnedCharacter)
        .filter(UserOwnedCharacter.user_game_profile_id == profile.id)
        .filter(UserOwnedCharacter.character_id == character_id)
        .first()
    )
    if not owned:
        raise HTTPException(status_code=400, detail="보유하지 않은 캐릭터입니다.")

    (
        db.query(UserOwnedCharacter)
        .filter(UserOwnedCharacter.user_game_profile_id == profile.id)
        .update({"is_equipped": False}, synchronize_session=False)
    )

    owned.is_equipped = True
    profile.selected_character_id = character_id

    profile.level = owned.level or 1
    profile.current_exp = owned.current_exp or 0

def equip_background_internal(db: Session, profile: UserGameProfile, background_id: str):
    validate_background_id(background_id)

    owned = (
        db.query(UserOwnedBackground)
        .filter(UserOwnedBackground.user_game_profile_id == profile.id)
        .filter(UserOwnedBackground.background_id == background_id)
        .first()
    )
    if not owned:
        raise HTTPException(status_code=400, detail="보유하지 않은 배경입니다.")

    (
        db.query(UserOwnedBackground)
        .filter(UserOwnedBackground.user_game_profile_id == profile.id)
        .update({"is_equipped": False}, synchronize_session=False)
    )

    owned.is_equipped = True
    profile.selected_background_id = background_id


def build_profile_adaptation_summary(db: Session, user_id: int) -> Dict[str, Any]:
    return get_public_behavior_summary(
        db,
        user_id,
        lazy_refresh=True,
    )


def build_profile_response(profile: UserGameProfile, db: Session, user_id: int) -> dict:
    """
    프론트에서 쓰기 쉬운 형태로 profile 응답 구성
    """
    active_missions_count = (
        db.query(UserMission)
        .filter(UserMission.user_id == user_id)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .count()
    )

    user = db.query(User).filter(User.id == user_id).first()

    #0409_2수정
    owned_characters = [
    {
        "id": row.character_id,
        "level": row.level or 1,
        "exp": row.current_exp or 0
    }
    for row in db.query(UserOwnedCharacter)
    .filter(UserOwnedCharacter.user_game_profile_id == profile.id)
    .all()
    ]
    ##까지 수정

    owned_background_ids = [
        row.background_id
        for row in db.query(UserOwnedBackground)
        .filter(UserOwnedBackground.user_game_profile_id == profile.id)
        .all()
    ]

    achievement_rows = get_user_achievements(db, profile.id)
    completed_achievement_codes = get_completed_achievement_codes(db, profile.id)
    equipped_achievement_codes = get_equipped_achievement_codes(db, profile.id)

    equipped_achievement = None
    if achievement_rows:
        first_equipped = next((row for row in achievement_rows if row.is_equipped), None)
        if first_equipped:
            equipped_achievement = {
                "achievement_code": first_equipped.achievement_code,
                "title": first_equipped.title,
                "description": first_equipped.description,
            }

    level_meta = build_level_meta(profile)

    return {
        "user_id": profile.user_id,
        "nickname": user.nickname if user else None,
        "game_nickname": profile.game_nickname,
        "level": profile.level,
        "current_exp": profile.current_exp,
        "total_exp": profile.total_exp,
        "coins": profile.coins,
        "mission_coins": profile.mission_coins,
        "has_created_character": profile.has_created_character,
        "selected_character_id": profile.selected_character_id,
        "selected_background_id": profile.selected_background_id,
        "equipped_badge_id": profile.equipped_badge_id,
        "daily_free_regen_remaining": min(profile.daily_free_regen_remaining or 0, 3),
        "daily_regen_date": profile.daily_regen_date,
        "active_missions_count": active_missions_count,
        #0409_2수정
        "owned_characters": owned_characters,
        #까지 수정
        "owned_background_ids": owned_background_ids,
        "equipped_achievement": equipped_achievement,
        "next_level_required_exp": level_meta["next_level_required_exp"],
        "can_level_up": level_meta["can_level_up"],
        "character_stage": level_meta["character_stage"],
        "max_level": level_meta["max_level"],
        "completed_achievement_codes": completed_achievement_codes,
        "equipped_achievement_codes": equipped_achievement_codes,
        "achievements": [serialize_achievement(row) for row in achievement_rows],
        "total_missions_completed": profile.total_missions_completed or 0,
        "total_coins_earned": profile.total_coins_earned or 0,
        "total_purchases": profile.total_purchases or 0,
        "adaptation_summary": build_profile_adaptation_summary(db, user_id),
    }



# -----------------------------
# endpoints
# -----------------------------
@router.get("/profile")
def get_game_profile(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = (
        db.query(UserGameProfile)
        .filter(UserGameProfile.user_id == user.id)
        .first()
    )

    if not profile:
        return {
            "ok": True,
            "game_initialized": False,
            "profile": None,
        }

    changed = reset_daily_regen_if_needed_internal(profile)
    if changed:
        db.add(profile)
        db.commit()
        db.refresh(profile)

    behavior_profile = ensure_user_behavior_profile(db, user.id, lazy_refresh=True)

    has_pending_behavior_changes = (
        behavior_profile.id is None
        or behavior_profile in db.new
        or db.is_modified(behavior_profile, include_collections=False)
    )

    if has_pending_behavior_changes:
        db.add(behavior_profile)
        db.commit()
        db.refresh(profile)

    return {
        "ok": True,
        "game_initialized": True,
        "profile": build_profile_response(profile, db, user.id),
    }


@router.post("/initialize-character")
def initialize_character(
    req: InitializeCharacterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    최초 캐릭터/배경 선택
    - 한 번 선택하면 되돌릴 수 없음
    - 이미 생성된 경우 재선택 불가
    - starter(무료 시작 아이템)만 최초 선택 가능
    """
    validate_character_id(req.character_id)
    validate_background_id(req.background_id)

    if not is_starter_character(req.character_id):
        raise HTTPException(
            status_code=400,
            detail="최초 생성 시에는 시작 캐릭터만 선택할 수 있습니다."
        )

    if not is_starter_background(req.background_id):
        raise HTTPException(
            status_code=400,
            detail="최초 생성 시에는 시작 배경만 선택할 수 있습니다."
        )

    profile = get_existing_game_profile(db, user.id)

    if profile.has_created_character:
        raise HTTPException(
            status_code=400,
            detail="이미 캐릭터가 생성되었습니다. 최초 선택은 다시 할 수 없습니다."
        )

    profile.has_created_character = True
    profile.selected_character_id = req.character_id
    profile.selected_background_id = req.background_id

    db.add(profile)
    db.flush()

    existing_character = (
        db.query(UserOwnedCharacter)
        .filter(UserOwnedCharacter.user_game_profile_id == profile.id)
        .filter(UserOwnedCharacter.character_id == req.character_id)
        .first()
    )
    if not existing_character:
        db.add(
            UserOwnedCharacter(
                user_game_profile_id=profile.id,
                character_id=req.character_id,
                is_equipped=True,
            )
        )
    else:
        existing_character.is_equipped = True

    existing_background = (
        db.query(UserOwnedBackground)
        .filter(UserOwnedBackground.user_game_profile_id == profile.id)
        .filter(UserOwnedBackground.background_id == req.background_id)
        .first()
    )
    if not existing_background:
        db.add(
            UserOwnedBackground(
                user_game_profile_id=profile.id,
                background_id=req.background_id,
                is_equipped=True,
            )
        )
    else:
        existing_background.is_equipped = True

    # 다른 장착 데이터 정리
    (
        db.query(UserOwnedCharacter)
        .filter(UserOwnedCharacter.user_game_profile_id == profile.id)
        .filter(UserOwnedCharacter.character_id != req.character_id)
        .update({"is_equipped": False}, synchronize_session=False)
    )
    (
        db.query(UserOwnedBackground)
        .filter(UserOwnedBackground.user_game_profile_id == profile.id)
        .filter(UserOwnedBackground.background_id != req.background_id)
        .update({"is_equipped": False}, synchronize_session=False)
    )

    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": "캐릭터와 배경이 최초 생성되었습니다.",
        "profile": build_profile_response(profile, db, user.id),
    }

@router.patch("/update-game-nickname")
def update_game_nickname(
    req: UpdateGameNicknameRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = get_existing_game_profile(db, user.id)
    require_character_created(profile)

    normalized = normalize_game_nickname(req.game_nickname)
    if normalized is None:
        raise HTTPException(status_code=400, detail="게임 닉네임을 입력해주세요.")

    if is_game_nickname_taken(db, normalized, exclude_profile_id=profile.id):
        raise HTTPException(status_code=409, detail="중복된 닉네임입니다.")

    current_nickname = (profile.game_nickname or "").strip()
    same_nickname = (
        current_nickname
        and normalize_game_nickname_for_compare(current_nickname)
        == normalize_game_nickname_for_compare(normalized)
    )

    charged_coins = 0
    new_achievements = []

    if req.consume_coins and current_nickname and not same_nickname:
        price = get_game_nickname_change_price()

        if profile.coins < price:
            raise HTTPException(status_code=400, detail="코인이 부족합니다. (500코인 필요)")

        profile.coins -= price
        if profile.coins < 0:
            profile.coins = 0

        if profile.total_purchases is None:
            profile.total_purchases = 0
        profile.total_purchases += 1

        charged_coins = price
        new_achievements = evaluate_and_grant_achievements(db, profile)

    profile.game_nickname = normalized

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": "게임 닉네임이 변경되었습니다." if current_nickname else "게임 닉네임이 설정되었습니다.",
        "charged_coins": charged_coins,
        "remaining_coins": profile.coins,
        "profile": build_profile_response(profile, db, user.id),
        "new_achievements": new_achievements,
    }

@router.post("/check-game-nickname")
def check_game_nickname(
    req: CheckGameNicknameRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = get_existing_game_profile(db, user.id)

    normalized = normalize_game_nickname(req.game_nickname)
    if normalized is None:
        raise HTTPException(status_code=400, detail="게임 닉네임을 입력해주세요.")

    current_nickname = (profile.game_nickname or "").strip()
    same_as_mine = (
        current_nickname
        and normalize_game_nickname_for_compare(current_nickname)
        == normalize_game_nickname_for_compare(normalized)
    )

    if same_as_mine:
        return {
            "available": True,
            "message": "현재 사용 중인 닉네임입니다.",
        }

    if is_game_nickname_taken(db, normalized, exclude_profile_id=profile.id):
        return {
            "available": False,
            "message": "중복된 닉네임입니다.",
        }

    return {
        "available": True,
        "message": "사용 가능한 닉네임입니다.",
    }

@router.post("/purchase-character")
def purchase_character(
    req: PurchaseCharacterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    캐릭터 구매
    - 이미 보유한 캐릭터는 재구매 불가
    - 코인 부족 시 구매 불가
    - 구매 후 자동 장착
    """
    validate_character_id(req.character_id)

    profile = get_existing_game_profile(db, user.id)
    require_character_created(profile)

    price = get_character_price(req.character_id)

    if is_character_owned(db, profile.id, req.character_id):
        raise HTTPException(status_code=400, detail="이미 보유한 캐릭터입니다.")

    if profile.coins < price:
        raise HTTPException(status_code=400, detail="코인이 부족합니다.")

    profile.coins -= price
    if profile.total_purchases is None:
        profile.total_purchases = 0
    profile.total_purchases += 1

    new_achievements = evaluate_and_grant_achievements(db, profile)

    if profile.coins < 0:
        profile.coins = 0

    owned_row = UserOwnedCharacter(
        user_game_profile_id=profile.id,
        character_id=req.character_id,
        is_equipped=False,
        #0409_2수정
        level=1,          # 신규 캐릭터 레벨 1 설정
        current_exp=0
    )
    db.add(owned_row)
    db.flush()

    equip_character_internal(db, profile, req.character_id)

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": "캐릭터를 구매하고 바로 장착했습니다.",
        "purchased_character_id": req.character_id,
        "selected_character_id": profile.selected_character_id,
        "remaining_coins": profile.coins,
        "profile": build_profile_response(profile, db, user.id),
        "new_achievements": new_achievements,
    }


@router.post("/purchase-background")
def purchase_background(
    req: PurchaseBackgroundRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    배경 구매
    - 이미 보유한 배경은 재구매 불가
    - 코인 부족 시 구매 불가
    - 구매 후 자동 적용
    """
    validate_background_id(req.background_id)

    profile = get_existing_game_profile(db, user.id)
    require_character_created(profile)

    price = get_background_price(req.background_id)

    if is_background_owned(db, profile.id, req.background_id):
        raise HTTPException(status_code=400, detail="이미 보유한 배경입니다.")

    if profile.coins < price:
        raise HTTPException(status_code=400, detail="코인이 부족합니다.")

    profile.coins -= price
    if profile.total_purchases is None:
        profile.total_purchases = 0
    profile.total_purchases += 1

    new_achievements = evaluate_and_grant_achievements(db, profile)

    if profile.coins < 0:
        profile.coins = 0

    owned_row = UserOwnedBackground(
        user_game_profile_id=profile.id,
        background_id=req.background_id,
        is_equipped=False,
    )
    db.add(owned_row)
    db.flush()

    equip_background_internal(db, profile, req.background_id)

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": "배경을 구매하고 바로 적용했습니다.",
        "purchased_background_id": req.background_id,
        "selected_background_id": profile.selected_background_id,
        "remaining_coins": profile.coins,
        "profile": build_profile_response(profile, db, user.id),
        "new_achievements": new_achievements,
    }


@router.post("/equip-character")
def equip_character(
    req: EquipCharacterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    보유한 캐릭터 장착
    """
    validate_character_id(req.character_id)

    profile = get_existing_game_profile(db, user.id)
    require_character_created(profile)

    # 1. 사용자가 해당 캐릭터를 실제로 소유하고 있는지 확인
    owned_char = db.query(UserOwnedCharacter).filter(
        UserOwnedCharacter.user_game_profile_id == profile.id,
        UserOwnedCharacter.character_id == req.character_id
    ).first()
    
    if not owned_char:
        raise HTTPException(status_code=400, detail="소유하지 않은 캐릭터입니다.")

    # 2. 기존에 장착된 캐릭터들의 장착 해제 (is_equipped = False)
    db.query(UserOwnedCharacter).filter(
        UserOwnedCharacter.user_game_profile_id == profile.id
    ).update({"is_equipped": False}, synchronize_session=False)

    # 3. 선택한 캐릭터 장착 및 프로필 수치 동기화
    owned_char.is_equipped = True
    profile.selected_character_id = req.character_id
    
    # ✅ 핵심: 프로필 레벨/경험치를 장착한 캐릭터의 독립 수치로 변경
    profile.level = owned_char.level
    profile.current_exp = owned_char.current_exp

    db.add(profile)
    db.add(owned_char)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": "캐릭터를 장착했습니다.",
        "selected_character_id": profile.selected_character_id,
        "profile": build_profile_response(profile, db, user.id),
    }


@router.post("/equip-background")
def equip_background(
    req: EquipBackgroundRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    보유한 배경 장착
    """
    validate_background_id(req.background_id)

    profile = get_existing_game_profile(db, user.id)
    require_character_created(profile)

    equip_background_internal(db, profile, req.background_id)

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": "배경을 적용했습니다.",
        "selected_background_id": profile.selected_background_id,
        "profile": build_profile_response(profile, db, user.id),
    }

@router.post("/equip-achievements")
def equip_achievements(
    req: EquipAchievementsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = get_existing_game_profile(db, user.id)
    require_character_created(profile)

    unique_codes: list[str] = []
    seen = set()
    for code in req.achievement_codes:
        cleaned = (code or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unique_codes.append(cleaned)

    if len(unique_codes) > 3:
        raise HTTPException(status_code=400, detail="업적은 최대 3개까지만 장착할 수 있습니다.")

    owned_rows = get_user_achievements(db, profile.id)
    owned_codes = {row.achievement_code for row in owned_rows}

    for code in unique_codes:
        if code not in owned_codes:
            raise HTTPException(status_code=400, detail=f"보유하지 않은 업적입니다: {code}")

    (
        db.query(UserAchievement)
        .filter(UserAchievement.user_game_profile_id == profile.id)
        .update({"is_equipped": False}, synchronize_session=False)
    )

    if unique_codes:
        (
            db.query(UserAchievement)
            .filter(UserAchievement.user_game_profile_id == profile.id)
            .filter(UserAchievement.achievement_code.in_(unique_codes))
            .update({"is_equipped": True}, synchronize_session=False)
        )
        profile.equipped_badge_id = unique_codes[0]
    else:
        profile.equipped_badge_id = None

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": "장착 업적이 업데이트되었습니다.",
        "equipped_achievement_codes": unique_codes,
        "profile": build_profile_response(profile, db, user.id),
    }



@router.post("/level-up")
def level_up(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    수동 레벨업 처리
    - 미션 보상으로 쌓인 current_exp를 사용
    - 자동 레벨업 없음
    - 버튼을 눌렀을 때만 레벨업
    - 남는 EXP는 다음 레벨로 이월
    """
    profile = get_existing_game_profile(db, user.id)
    require_character_created(profile)

    if profile.level is None or profile.level < 1:
        profile.level = 1

    if profile.current_exp is None:
        profile.current_exp = 0

    if profile.total_exp is None:
        profile.total_exp = 0

    if profile.level >= MAX_LEVEL:
        raise HTTPException(
            status_code=400,
            detail="이미 최대 레벨입니다."
        )

    required_exp = get_required_exp_for_level(profile.level)

    if profile.current_exp < required_exp:
        raise HTTPException(
            status_code=400,
            detail="레벨업에 필요한 EXP가 부족합니다."
        )

    before_level = profile.level
    before_exp = profile.current_exp

    #0409_2수정
    owned_char = db.query(UserOwnedCharacter).filter(
        UserOwnedCharacter.user_game_profile_id == profile.id,
        UserOwnedCharacter.character_id == profile.selected_character_id
    ).first()

    if owned_char:
        # 캐릭터 독립 레벨 및 경험치 수정
        owned_char.level += 1
        owned_char.current_exp -= required_exp
        
        # 최대 레벨 도달 시 경험치 음수 방어 로직
        if owned_char.current_exp < 0:
            owned_char.current_exp = 0

        # 전역 프로필 수치 동기화 (UI 표시용)
        profile.level = owned_char.level
        profile.current_exp = owned_char.current_exp

        # 업적 평가 (선택 사항: 필요 시 유지)
        new_achievements = evaluate_and_grant_achievements(db, profile)

        # ✅ DB 반영 및 세션 갱신
        db.add(owned_char)
        db.add(profile)
        db.commit() # 👈 실제 DB에 레벨 2로 저장되는 지점
        
        db.refresh(owned_char)
        db.refresh(profile)

    return {
        "ok": True,
        "message": f"레벨업 완료! Lv.{before_level} → Lv.{profile.level}",
        "before_level": before_level,
        "after_level": profile.level,
        "before_exp": before_exp,
        "remaining_exp": profile.current_exp,
        "used_exp": required_exp,
        "profile": build_profile_response(profile, db, user.id),
        "new_achievements": new_achievements,
    }

@router.post("/use-mission-coin")
def use_mission_coin(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    미션 코인 1개 사용
    - 실제 미션 재생성은 다음 단계 API와 연결
    - 지금은 코인 차감만 안전하게 처리
    """
    profile = get_existing_game_profile(db, user.id)

    if profile.mission_coins is None:
        profile.mission_coins = 0

    if profile.mission_coins < 1:
        raise HTTPException(
            status_code=400,
            detail="미션 쿠폰이 부족합니다."
        )

    profile.mission_coins -= 1
    if profile.mission_coins < 0:
        profile.mission_coins = 0

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": "미션 쿠폰 1개를 사용했습니다.",
        "mission_coins": profile.mission_coins,
        "profile": build_profile_response(profile, db, user.id),
    }

@router.post("/purchase-mission-coins")
def purchase_mission_coins(
    req: PurchaseMissionCoinsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    미션 쿠폰 구매 (현재는 결제 목업 성공 처리)
    - package_id 기준으로 지급 수량 결정
    - DB의 user_game_profiles.mission_coins 에 실제 반영
    - 첫 구매 업적 판정 연결
    """

    # 운영/토스 결제 연동 후에는 목업 결제 API 차단
    if not settings.ALLOW_MOCK_PAYMENTS:
        raise HTTPException(
            status_code=410,
            detail="목업 결제 API는 비활성화되었습니다. 토스 결제를 사용하세요.",
        )

    profile = get_existing_game_profile(db, user.id)

    if profile.mission_coins is None:
        profile.mission_coins = 0

    if profile.total_purchases is None:
        profile.total_purchases = 0

    package_map = {
        "pack-1": {"amount": 1, "label": "미션 쿠폰 1개"},
        "pack-5": {"amount": 5, "label": "미션 쿠폰 5개"},
        "pack-10": {"amount": 10, "label": "미션 쿠폰 10개"},
        "pack-20": {"amount": 20, "label": "미션 쿠폰 20개"},
        "pack-30": {"amount": 30, "label": "미션 쿠폰 30개"},
        "pack-50": {"amount": 50, "label": "미션 쿠폰 50개"},
        "pack-100": {"amount": 100, "label": "미션 쿠폰 100개"},
    }

    package = package_map.get(req.package_id)
    if not package:
        raise HTTPException(
            status_code=400,
            detail="유효하지 않은 미션 쿠폰 상품입니다."
        )

    profile.mission_coins += package["amount"]

    profile.total_purchases += 1

    if profile.mission_coins < 0:
        profile.mission_coins = 0

    new_achievements = evaluate_and_grant_achievements(db, profile)

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": f"{package['label']} 구매가 완료되었습니다.",
        "package_id": req.package_id,
        "purchased_amount": package["amount"],
        "mission_coins": profile.mission_coins,
        "profile": build_profile_response(profile, db, user.id),
        "new_achievements": new_achievements,
    }


@router.post("/reset-daily-regen-if-needed")
def reset_daily_regen_if_needed(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    하루가 바뀌었는지 확인 후 무료 재생성 횟수 리셋
    - 3 초과 불가
    """
    profile = get_existing_game_profile(db, user.id)

    changed = reset_daily_regen_if_needed_internal(profile)

    if changed:
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return {
        "ok": True,
        "reset_applied": changed,
        "daily_free_regen_remaining": min(profile.daily_free_regen_remaining or 0, 3),
        "daily_regen_date": profile.daily_regen_date,
        "profile": build_profile_response(profile, db, user.id),
    }


@router.get("/achievements")
def get_achievements(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = get_existing_game_profile(db, user.id)
    require_character_created(profile)

    rows = get_user_achievements(db, profile.id)

    return {
        "ok": True,
        "achievements": [serialize_achievement(row) for row in rows],
        "completed_achievement_codes": get_completed_achievement_codes(db, profile.id),
        "equipped_achievement_codes": get_equipped_achievement_codes(db, profile.id),
    }

