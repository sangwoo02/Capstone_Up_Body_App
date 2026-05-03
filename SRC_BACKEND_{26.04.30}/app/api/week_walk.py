from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.game import UserGameProfile, WeekWalkWeeklyParticipant
from app.models.user import User
from app.services.week_walk_service import (
    ensure_week_walk_ready,
    build_weekly_leaderboard,
    build_score_leaderboard,
    get_my_weekly_status,
    get_my_score_status,
)

router = APIRouter(prefix="/week-walk", tags=["week-walk"])


def get_existing_game_profile(db: Session, user_id: int) -> UserGameProfile:
    profile = db.query(UserGameProfile).filter(UserGameProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="게임 프로필이 없습니다.")
    return profile


@router.get("/overview")
def get_week_walk_overview(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = get_existing_game_profile(db, user.id)

    ready = ensure_week_walk_ready(db, profile)
    weekly_season = ready["weekly_season"]
    score_season = ready["score_season"]
    new_achievement_codes = ready["new_achievement_codes"]

    # TOP 50까지 반환해서 프론트에서 고정 높이 + 내부 스크롤 UI로 보여준다.
    weekly_ranking = build_weekly_leaderboard(db, weekly_season, limit=50)
    score_ranking = build_score_leaderboard(db, score_season, limit=50)

    my_weekly = get_my_weekly_status(db, weekly_season, profile)
    my_score = get_my_score_status(db, score_season, profile)

    return {
        "ok": True,
        "weekly_season": {
            "season_id": weekly_season.id,
            "start_at": weekly_season.start_at.isoformat(),
            "end_at": weekly_season.end_at.isoformat(),
        },
        "score_season": {
            "season_id": score_season.id,
            "start_at": score_season.start_at.isoformat(),
            "end_at": score_season.end_at.isoformat(),
        },
        "weekly_ranking": weekly_ranking,
        "score_ranking": score_ranking,
        "my_weekly": my_weekly,
        "my_score": my_score,
        "my_game_nickname": profile.game_nickname,
        "total_game_profile_users": db.query(UserGameProfile)
            .filter(UserGameProfile.has_created_character == True)
            .count(),
        "new_achievement_codes": new_achievement_codes,
    }


@router.post("/join")
def join_week_walk(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = get_existing_game_profile(db, user.id)

    if not profile.has_created_character:
        raise HTTPException(status_code=400, detail="캐릭터 생성 후 참여할 수 있습니다.")

    ready = ensure_week_walk_ready(db, profile)
    weekly_season = ready["weekly_season"]
    score_season = ready["score_season"]
    new_achievement_codes = ready["new_achievement_codes"]

    existing = (
        db.query(WeekWalkWeeklyParticipant)
        .filter(WeekWalkWeeklyParticipant.season_id == weekly_season.id)
        .filter(WeekWalkWeeklyParticipant.user_game_profile_id == profile.id)
        .first()
    )

    if existing:
        return {
            "ok": True,
            "message": "이미 이번 주 경쟁전에 참여 중입니다.",
            "joined": True,
            "new_achievement_codes": new_achievement_codes,
        }

    row = WeekWalkWeeklyParticipant(
        season_id=weekly_season.id,
        user_game_profile_id=profile.id,
    )
    db.add(row)
    db.commit()

    return {
        "ok": True,
        "message": "Week Walk 경쟁전에 참여했습니다.",
        "joined": True,
        "weekly_season_id": weekly_season.id,
        "score_season_id": score_season.id,
        "new_achievement_codes": new_achievement_codes,
    }