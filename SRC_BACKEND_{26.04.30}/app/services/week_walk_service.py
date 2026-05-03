from datetime import datetime, timedelta, timezone, date, time
from zoneinfo import ZoneInfo
from typing import List, Dict, Any, Tuple

from sqlalchemy.orm import Session

from app.models.game import (
    UserGameProfile,
    WeekWalkSeason,
    WeekWalkWeeklyParticipant,
)
from app.models.user import UserActivity, User
from app.services.achievement_service import grant_specific_achievements

WEEKLY_REWARDS = [
    {"min_rank": 1, "max_rank": 1, "exp": 500, "coins": 300, "coupons": 5, "score": 200},
    {"min_rank": 2, "max_rank": 2, "exp": 350, "coins": 200, "coupons": 3, "score": 150},
    {"min_rank": 3, "max_rank": 3, "exp": 250, "coins": 150, "coupons": 2, "score": 120},
    {"min_rank": 4, "max_rank": 50, "exp": 100, "coins": 50, "coupons": 0, "score": 80},
    {"min_rank": 51, "max_rank": 100, "exp": 50, "coins": 30, "coupons": 0, "score": 50},
    {"min_rank": 101, "max_rank": 500, "exp": 30, "coins": 0, "coupons": 0, "score": 30},
    {"min_rank": 501, "max_rank": 1000, "exp": 15, "coins": 0, "coupons": 0, "score": 15},
    {"min_rank": 1001, "max_rank": 9999999, "exp": 5, "coins": 0, "coupons": 0, "score": 5},
]

SEASON_REWARDS = [
    {"min_rank": 1, "max_rank": 1, "coins": 1000, "coupons": 20, "achievement_codes": ["achv-rank-1"]},
    {"min_rank": 2, "max_rank": 2, "coins": 700, "coupons": 15, "achievement_codes": ["achv-rank-2"]},
    {"min_rank": 3, "max_rank": 3, "coins": 500, "coupons": 10, "achievement_codes": ["achv-rank-3"]},
    {"min_rank": 4, "max_rank": 50, "coins": 200, "coupons": 0, "achievement_codes": ["achv-rank-top50"]},
    {"min_rank": 51, "max_rank": 100, "coins": 100, "coupons": 0, "achievement_codes": ["achv-rank-top101"]},
]

TIERS = [
    ("브론즈", 0),
    ("실버", 500),
    ("골드", 1500),
    ("플래티넘", 3500),
    ("다이아", 7000),
    ("마스터", 15000),
]

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc


def extract_achievement_codes(rows) -> list[str]:
    codes: list[str] = []

    for row in rows or []:
        code = None

        if isinstance(row, dict):
            code = row.get("achievement_code")
        else:
            code = getattr(row, "achievement_code", None)

        if code:
            codes.append(str(code))

    return codes


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_kst(dt: datetime) -> datetime:
    return to_utc(dt).astimezone(KST)


def get_kst_today(now: datetime | None = None) -> date:
    base = now or datetime.now(UTC)
    return to_kst(base).date()


def get_kst_week_range(target_day: date) -> Tuple[date, date]:
    """
    HistoryPage의 월~일 주간 범위와 동일한 기준
    """
    start_date = target_day - timedelta(days=target_day.weekday())  # 월요일
    end_date = start_date + timedelta(days=6)  # 일요일
    return start_date, end_date


def kst_date_range_to_utc_bounds(start_date: date, end_date: date) -> Tuple[datetime, datetime]:
    """
    KST 날짜 범위를 DB 조회용 UTC datetime 범위로 변환
    """
    start_local = datetime.combine(start_date, time.min, tzinfo=KST)
    end_local = datetime.combine(end_date, time.max, tzinfo=KST)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def get_week_walk_tier(score: int) -> str:
    tier_name = "브론즈"
    for name, min_score in TIERS:
        if score >= min_score:
            tier_name = name
    return tier_name


def get_weekly_reward(rank: int) -> Dict[str, int]:
    for reward in WEEKLY_REWARDS:
        if reward["min_rank"] <= rank <= reward["max_rank"]:
            return reward
    return WEEKLY_REWARDS[-1]


def get_season_reward(rank: int) -> Dict[str, Any] | None:
    for reward in SEASON_REWARDS:
        if reward["min_rank"] <= rank <= reward["max_rank"]:
            return reward
    return None


def get_week_start(now: datetime) -> datetime:
    """
    KST 월요일 00:00:00 시작을 UTC instant로 저장
    예) KST 월요일 00:00 == UTC 일요일 15:00
    """
    now_kst = to_kst(now)
    week_start_date = now_kst.date() - timedelta(days=now_kst.weekday())
    start_local = datetime.combine(week_start_date, time.min, tzinfo=KST)
    return start_local.astimezone(UTC)


def get_week_end(start_at: datetime) -> datetime:
    """
    KST 일요일 23:59:59.999999 끝을 UTC instant로 저장
    """
    start_kst = to_kst(start_at)
    end_local = datetime.combine(start_kst.date() + timedelta(days=6), time.max, tzinfo=KST)
    return end_local.astimezone(UTC)


def get_score_season_start(now: datetime) -> datetime:
    """
    2달 시즌도 KST 기준 시작
    """
    now_kst = to_kst(now)
    month = now_kst.month
    year = now_kst.year

    if month in [1, 2]:
        start_month = 1
    elif month in [3, 4]:
        start_month = 3
    elif month in [5, 6]:
        start_month = 5
    elif month in [7, 8]:
        start_month = 7
    elif month in [9, 10]:
        start_month = 9
    else:
        start_month = 11

    start_local = datetime(year, start_month, 1, 0, 0, 0, tzinfo=KST)
    return start_local.astimezone(UTC)


def get_score_season_end(start_at: datetime) -> datetime:
    start_kst = to_kst(start_at)

    if start_kst.month == 11:
        next_start_local = datetime(start_kst.year + 1, 1, 1, 0, 0, 0, tzinfo=KST)
    else:
        next_start_local = datetime(start_kst.year, start_kst.month + 2, 1, 0, 0, 0, tzinfo=KST)

    return (next_start_local - timedelta(microseconds=1)).astimezone(UTC)


def ensure_current_season(db: Session, season_type: str) -> WeekWalkSeason:
    now = datetime.now(UTC)

    if season_type == "weekly":
        start_at = get_week_start(now)
        end_at = get_week_end(start_at)
    else:
        start_at = get_score_season_start(now)
        end_at = get_score_season_end(start_at)

    season = (
        db.query(WeekWalkSeason)
        .filter(WeekWalkSeason.season_type == season_type)
        .filter(WeekWalkSeason.start_at == start_at)
        .first()
    )

    if season:
        return season

    season = WeekWalkSeason(
        season_type=season_type,
        start_at=start_at,
        end_at=end_at,
        is_settled=False,
    )
    db.add(season)
    db.commit()
    db.refresh(season)
    return season


def sum_steps_for_user_between(
    db: Session,
    user_id: int,
    start_at: datetime,
    end_at: datetime,
) -> int:
    """
    Week Walk 집계도 HistoryPage와 동일하게 KST 날짜 범위 기준으로 합산
    """
    start_kst_date = to_kst(start_at).date()
    end_kst_date = to_kst(end_at).date()

    query_start_utc, query_end_utc = kst_date_range_to_utc_bounds(start_kst_date, end_kst_date)

    rows = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user_id)
        .filter(UserActivity.recorded_at >= query_start_utc)
        .filter(UserActivity.recorded_at <= query_end_utc)
        .all()
    )

    total_steps = 0
    for row in rows:
        if not row.recorded_at:
            continue

        row_kst_date = to_kst(row.recorded_at).date()
        if start_kst_date <= row_kst_date <= end_kst_date:
            total_steps += int(row.steps or 0)

    return total_steps


def build_weekly_leaderboard(
    db: Session,
    season: WeekWalkSeason,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    participants = (
        db.query(WeekWalkWeeklyParticipant, UserGameProfile, User)
        .join(UserGameProfile, UserGameProfile.id == WeekWalkWeeklyParticipant.user_game_profile_id)
        .join(User, User.id == UserGameProfile.user_id)
        .filter(WeekWalkWeeklyParticipant.season_id == season.id)
        .all()
    )

    ranking: List[Dict[str, Any]] = []
    for participant, profile, user in participants:
        steps = sum_steps_for_user_between(db, user.id, season.start_at, season.end_at)
        ranking.append({
            "profile_id": profile.id,
            "user_id": user.id,
            "nickname": profile.game_nickname or f"USER-{user.id}",
            "steps": steps,
        })

    ranking.sort(key=lambda x: (-x["steps"], x["user_id"]))

    result = []
    for idx, item in enumerate(ranking[:limit], start=1):
        result.append({
            "rank": idx,
            "nickname": item["nickname"],
            "steps": item["steps"],
            "change": 0,
        })
    return result


def build_full_weekly_ranking(
    db: Session,
    season: WeekWalkSeason,
) -> List[Dict[str, Any]]:
    participants = (
        db.query(WeekWalkWeeklyParticipant, UserGameProfile, User)
        .join(UserGameProfile, UserGameProfile.id == WeekWalkWeeklyParticipant.user_game_profile_id)
        .join(User, User.id == UserGameProfile.user_id)
        .filter(WeekWalkWeeklyParticipant.season_id == season.id)
        .all()
    )

    ranking: List[Dict[str, Any]] = []
    for participant, profile, user in participants:
        steps = sum_steps_for_user_between(db, user.id, season.start_at, season.end_at)
        ranking.append({
            "profile": profile,
            "user": user,
            "steps": steps,
        })

    ranking.sort(key=lambda x: (-x["steps"], x["user"].id))
    return ranking


def get_score_season_participant_profile_ids(
    db: Session,
    score_season: WeekWalkSeason,
) -> list[int]:
    """
    score 시즌 기간 안에 실제로 "시작하기"를 눌러 주간 경쟁전에 참가한 유저만
    시즌 보상 대상으로 인정한다.
    """
    rows = (
        db.query(WeekWalkWeeklyParticipant.user_game_profile_id)
        .filter(WeekWalkWeeklyParticipant.joined_at >= score_season.start_at)
        .filter(WeekWalkWeeklyParticipant.joined_at <= score_season.end_at)
        .distinct()
        .all()
    )
    return [profile_id for (profile_id,) in rows]


def build_score_leaderboard(
    db: Session,
    score_season: WeekWalkSeason,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    점수 시즌 랭킹 표시는 현재 시즌 참가 여부로 필터링하지 않는다.
    캐릭터를 만든 모든 유저를 누적 점수 기준으로 계속 노출한다.
    """
    profiles = (
        db.query(UserGameProfile, User)
        .join(User, User.id == UserGameProfile.user_id)
        .filter(UserGameProfile.has_created_character == True)
        .order_by(UserGameProfile.week_walk_score.desc(), User.id.asc())
        .limit(limit)
        .all()
    )

    result = []
    for idx, (profile, user) in enumerate(profiles, start=1):
        result.append({
            "rank": idx,
            "nickname": profile.game_nickname or f"USER-{user.id}",
            "score": int(profile.week_walk_score or 0),
            "tier": profile.week_walk_tier or "브론즈",
        })
    return result


def build_full_score_ranking(
    db: Session,
    score_season: WeekWalkSeason,
) -> List[Dict[str, Any]]:
    """
    점수 시즌 전체 랭킹 표시용.
    현재 시즌 참가 여부와 무관하게 캐릭터를 만든 모든 유저를 누적 점수 기준으로 정렬한다.
    """
    profiles = (
        db.query(UserGameProfile, User)
        .join(User, User.id == UserGameProfile.user_id)
        .filter(UserGameProfile.has_created_character == True)
        .order_by(UserGameProfile.week_walk_score.desc(), User.id.asc())
        .all()
    )
    return [{"profile": profile, "user": user} for profile, user in profiles]


def build_full_score_reward_ranking(
    db: Session,
    score_season: WeekWalkSeason,
) -> List[Dict[str, Any]]:
    """
    점수 시즌 정산/보상 지급용 랭킹.
    현재 score 시즌 기간 안에 실제로 주간 경쟁전에 참가한 유저만 보상 대상으로 인정한다.
    """
    participant_profile_ids = get_score_season_participant_profile_ids(db, score_season)
    if not participant_profile_ids:
        return []

    profiles = (
        db.query(UserGameProfile, User)
        .join(User, User.id == UserGameProfile.user_id)
        .filter(UserGameProfile.has_created_character == True)
        .filter(UserGameProfile.id.in_(participant_profile_ids))
        .order_by(UserGameProfile.week_walk_score.desc(), User.id.asc())
        .all()
    )
    return [{"profile": profile, "user": user} for profile, user in profiles]


def get_my_weekly_status(
    db: Session,
    season: WeekWalkSeason,
    profile: UserGameProfile,
) -> Dict[str, Any]:
    joined = (
        db.query(WeekWalkWeeklyParticipant)
        .filter(WeekWalkWeeklyParticipant.season_id == season.id)
        .filter(WeekWalkWeeklyParticipant.user_game_profile_id == profile.id)
        .first()
    ) is not None

    my_steps = sum_steps_for_user_between(
        db=db,
        user_id=profile.user_id,
        start_at=season.start_at,
        end_at=season.end_at,
    )

    all_ranking = build_full_weekly_ranking(db, season)

    my_rank = None
    for idx, item in enumerate(all_ranking, start=1):
        if item["profile"].id == profile.id:
            my_rank = idx
            break

    return {
        "joined": joined,
        "rank": my_rank,
        "steps": my_steps,
    }


def get_my_score_status(
    db: Session,
    score_season: WeekWalkSeason,
    profile: UserGameProfile,
) -> Dict[str, Any]:
    ranking = build_full_score_ranking(db, score_season)

    my_rank = None
    for idx, item in enumerate(ranking, start=1):
        if item["profile"].id == profile.id:
            my_rank = idx
            break

    return {
        "joined": bool(profile.has_created_character),
        "rank": my_rank,
        "score": int(profile.week_walk_score or 0),
        "tier": profile.week_walk_tier or "브론즈",
    }


def _append_granted_codes(
    result: dict[int, list[str]],
    profile_id: int,
    rows,
) -> None:
    codes = extract_achievement_codes(rows)
    if not codes:
        return

    if profile_id not in result:
        result[profile_id] = []

    result[profile_id].extend(codes)


def settle_expired_weekly_seasons(db: Session) -> dict[int, list[str]]:
    now = datetime.now(timezone.utc)
    granted_codes_by_profile: dict[int, list[str]] = {}

    expired = (
        db.query(WeekWalkSeason)
        .filter(WeekWalkSeason.season_type == "weekly")
        .filter(WeekWalkSeason.is_settled == False)
        .filter(WeekWalkSeason.end_at < now)
        .all()
    )

    for season in expired:
        ranking = build_full_weekly_ranking(db, season)

        for idx, item in enumerate(ranking, start=1):
            profile: UserGameProfile = item["profile"]
            reward = get_weekly_reward(idx)

            profile.current_exp = int(profile.current_exp or 0) + int(reward["exp"])
            profile.total_exp = int(profile.total_exp or 0) + int(reward["exp"])
            profile.coins = int(profile.coins or 0) + int(reward["coins"])
            profile.mission_coins = int(profile.mission_coins or 0) + int(reward["coupons"])
            profile.total_coins_earned = int(profile.total_coins_earned or 0) + int(reward["coins"])
            profile.week_walk_score = int(profile.week_walk_score or 0) + int(reward["score"])
            profile.week_walk_tier = get_week_walk_tier(int(profile.week_walk_score or 0))

            new_rows = grant_specific_achievements(
                db,
                profile,
                ["achv-week-walk-clear"],
            )
            _append_granted_codes(granted_codes_by_profile, profile.id, new_rows)

            db.add(profile)

        season.is_settled = True
        season.settled_at = now
        db.add(season)

    db.commit()
    return granted_codes_by_profile


def settle_expired_score_seasons(db: Session) -> dict[int, list[str]]:
    now = datetime.now(timezone.utc)
    granted_codes_by_profile: dict[int, list[str]] = {}

    expired = (
        db.query(WeekWalkSeason)
        .filter(WeekWalkSeason.season_type == "score")
        .filter(WeekWalkSeason.is_settled == False)
        .filter(WeekWalkSeason.end_at < now)
        .all()
    )

    for season in expired:
        ranking = build_full_score_reward_ranking(db, season)

        for idx, item in enumerate(ranking, start=1):
            profile: UserGameProfile = item["profile"]

            reward = get_season_reward(idx)
            if not reward:
                continue

            profile.coins = int(profile.coins or 0) + int(reward["coins"])
            profile.mission_coins = int(profile.mission_coins or 0) + int(reward["coupons"])
            profile.total_coins_earned = int(profile.total_coins_earned or 0) + int(reward["coins"])

            new_rows = grant_specific_achievements(
                db,
                profile,
                reward["achievement_codes"],
            )
            _append_granted_codes(granted_codes_by_profile, profile.id, new_rows)

            db.add(profile)

        season.is_settled = True
        season.settled_at = now
        db.add(season)

    db.commit()
    return granted_codes_by_profile


def ensure_week_walk_ready(
    db: Session,
    profile: UserGameProfile | None = None,
) -> dict:
    weekly_new_by_profile = settle_expired_weekly_seasons(db)
    score_new_by_profile = settle_expired_score_seasons(db)

    weekly = ensure_current_season(db, "weekly")
    score = ensure_current_season(db, "score")

    new_achievement_codes: list[str] = []

    if profile:
        new_achievement_codes.extend(weekly_new_by_profile.get(profile.id, []))
        new_achievement_codes.extend(score_new_by_profile.get(profile.id, []))

    deduped_codes = list(dict.fromkeys(new_achievement_codes))

    return {
        "weekly_season": weekly,
        "score_season": score,
        "new_achievement_codes": deduped_codes,
    }