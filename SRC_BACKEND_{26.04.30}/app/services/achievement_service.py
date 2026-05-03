from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.game import UserAchievement, UserGameProfile

# 프론트 src/components/game/gameData.ts 의 id / title / description 과 맞춤
ACHIEVEMENT_CATALOG: Dict[str, Dict[str, str | int]] = {
    "achv-level-2": {
        "title": "입문의 시작",
        "description": "2레벨 달성",
    },
    "achv-level-max": {
        "title": "성장의 증거",
        "description": "만렙 달성",
    },
    "achv-first-mission": {
        "title": "첫 발걸음",
        "description": "첫 미션 달성",
    },
    "achv-mission-10": {
        "title": "미션 헌터",
        "description": "미션 누적 10회 완료",
    },
    "achv-mission-50": {
        "title": "미션 전문가",
        "description": "미션 누적 50회 완료",
    },
    "achv-mission-100": {
        "title": "미션 마스터",
        "description": "미션 누적 100회 완료",
    },
    "achv-coin-10": {
        "title": "용돈 모으기",
        "description": "코인 누적 10개 얻기",
    },
    "achv-coin-50": {
        "title": "저금통",
        "description": "코인 누적 50개 얻기",
    },
    "achv-coin-100": {
        "title": "금고 관리자",
        "description": "코인 누적 100개 얻기",
    },
    "achv-coin-200": {
        "title": "재벌의 길",
        "description": "코인 누적 200개 얻기",
    },
    "achv-first-purchase": {
        "title": "첫 결제!",
        "description": "첫 상점 구매 달성",
    },
    # competition / rank 업적은 Week Walk 단계에서 연결
    "achv-week-walk-clear": {
        "title": "First Stride",
        "description": "첫 경쟁전 시즌 클리어",
    },
    "achv-rank-1": {
        "title": "전설의 챔피언",
        "description": "경쟁전 1위 달성",
    },
    "achv-rank-2": {
        "title": "빛나는 준우승",
        "description": "경쟁전 2위 달성",
    },
    "achv-rank-3": {
        "title": "동메달리스트",
        "description": "경쟁전 3위 달성",
    },
    "achv-rank-top50": {
        "title": "탑 50 워커",
        "description": "경쟁전 4~50위 달성",
    },
    "achv-rank-top101": {
        "title": "건강한 도전자",
        "description": "경쟁전 51~100위 달성",
    },
}


def serialize_achievement(row: UserAchievement) -> dict:
    return {
        "achievement_code": row.achievement_code,
        "title": row.title,
        "description": row.description,
        "is_equipped": bool(row.is_equipped),
        "acquired_at": row.acquired_at.isoformat() if row.acquired_at else None,
    }


def get_user_achievements(db: Session, profile_id: int) -> List[UserAchievement]:
    return (
        db.query(UserAchievement)
        .filter(UserAchievement.user_game_profile_id == profile_id)
        .order_by(UserAchievement.acquired_at.asc(), UserAchievement.id.asc())
        .all()
    )


def get_completed_achievement_codes(db: Session, profile_id: int) -> List[str]:
    return [
        row.achievement_code
        for row in get_user_achievements(db, profile_id)
    ]


def get_equipped_achievement_codes(db: Session, profile_id: int) -> List[str]:
    return [
        row.achievement_code
        for row in get_user_achievements(db, profile_id)
        if row.is_equipped
    ]


def _grant_achievement(
    db: Session,
    profile: UserGameProfile,
    code: str,
) -> UserAchievement | None:
    existing = (
        db.query(UserAchievement)
        .filter(UserAchievement.user_game_profile_id == profile.id)
        .filter(UserAchievement.achievement_code == code)
        .first()
    )
    if existing:
        return None

    catalog = ACHIEVEMENT_CATALOG.get(code)
    if not catalog:
        return None

    row = UserAchievement(
        user_game_profile_id=profile.id,
        achievement_code=code,
        title=str(catalog["title"]),
        description=str(catalog["description"]),
        is_equipped=False,
    )
    db.add(row)
    db.flush()
    return row


def evaluate_and_grant_achievements(
    db: Session,
    profile: UserGameProfile,
) -> List[dict]:
    granted_rows: List[UserAchievement] = []

    level = profile.level or 1
    total_missions_completed = profile.total_missions_completed or 0
    total_coins_earned = profile.total_coins_earned or 0
    total_purchases = profile.total_purchases or 0

    if level >= 2:
        row = _grant_achievement(db, profile, "achv-level-2")
        if row:
            granted_rows.append(row)

    if level >= 10:
        row = _grant_achievement(db, profile, "achv-level-max")
        if row:
            granted_rows.append(row)

    if total_missions_completed >= 1:
        row = _grant_achievement(db, profile, "achv-first-mission")
        if row:
            granted_rows.append(row)

    if total_missions_completed >= 10:
        row = _grant_achievement(db, profile, "achv-mission-10")
        if row:
            granted_rows.append(row)

    if total_missions_completed >= 50:
        row = _grant_achievement(db, profile, "achv-mission-50")
        if row:
            granted_rows.append(row)

    if total_missions_completed >= 100:
        row = _grant_achievement(db, profile, "achv-mission-100")
        if row:
            granted_rows.append(row)

    if total_coins_earned >= 10:
        row = _grant_achievement(db, profile, "achv-coin-10")
        if row:
            granted_rows.append(row)

    if total_coins_earned >= 50:
        row = _grant_achievement(db, profile, "achv-coin-50")
        if row:
            granted_rows.append(row)

    if total_coins_earned >= 100:
        row = _grant_achievement(db, profile, "achv-coin-100")
        if row:
            granted_rows.append(row)

    if total_coins_earned >= 200:
        row = _grant_achievement(db, profile, "achv-coin-200")
        if row:
            granted_rows.append(row)

    if total_purchases >= 1:
        row = _grant_achievement(db, profile, "achv-first-purchase")
        if row:
            granted_rows.append(row)

    return [serialize_achievement(row) for row in granted_rows]


def grant_specific_achievements(
    db: Session,
    profile: UserGameProfile,
    codes: List[str],
) -> List[dict]:
    granted_rows: List[UserAchievement] = []

    for code in codes:
        row = _grant_achievement(db, profile, code)
        if row:
            granted_rows.append(row)

    return [serialize_achievement(row) for row in granted_rows]