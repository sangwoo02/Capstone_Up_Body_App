# app/api/missions.py

import re
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, status, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, date

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User, UserInbody, UserMission, UserActivity, MissionGenerationLog
from app.schemas.user_schema import HealthcareSyncRequest, HealthcareResponse, UserCheckResponse
from app.services.health_logic import HealthAnalyzer
from app.services.gpt_service import (
    GPTService,
    GPTMissionFormatError,
    ALLOWED_TYPES_BY_SLOT,
    BEHAVIOR_HISTORY_WINDOW,
    shift_numeric_candidates_by_bias,
    adjust_routine_candidates_by_bias,
    STEP_TARGET_MASTER,
    KCAL_TARGET_MASTER,
    STRETCH_DURATION_MASTER,
    SLEEP_PREP_DURATION_MASTER,
    CHECKIN_MIN_LENGTH_MASTER,
)
from app.services.mission_behavior_service import (
    get_effective_behavior_summary,
    upsert_user_behavior_profile,
)
from app.services.data_seeder import DataSeeder
from app.models.standard import HealthStandard
from app.services.kosis_api import KosisHealthStatsService
from app.api.game import ensure_game_profile
from app.api.auth import get_current_user_id
from app.models.game import UserGameProfile
from pydantic import BaseModel, Field
from app.services.achievement_service import evaluate_and_grant_achievements
from app.models.game import UserOwnedCharacter

router = APIRouter(prefix="/missions", tags=["Missions"])

# 한국 성인 BMI 분류 기준: 정상 18.5~22.9, 비만전단계 23.0~24.9, 비만 25.0 이상.
# 공공데이터 평균은 정상/위험 판정 기준이 아니라 참고 평균값으로만 사용한다.
BMI_NORMAL_MIN = 18.5
BMI_NORMAL_MAX = 22.9
BMI_PRE_OBESITY_MAX = 24.9
BMI_NORMAL_MID = 20.7


def get_bmi_status_for_mission(bmi_value: Optional[float]) -> str:
    try:
        value = float(bmi_value)
    except (TypeError, ValueError):
        return "unknown"

    if value < BMI_NORMAL_MIN:
        return "underweight"
    if value <= BMI_NORMAL_MAX:
        return "normal"
    if value <= BMI_PRE_OBESITY_MAX:
        return "pre_obesity"
    return "obesity"


def get_weight_status_by_bmi(bmi_value: Optional[float]) -> str:
    bmi_status = get_bmi_status_for_mission(bmi_value)

    if bmi_status == "underweight":
        return "low"
    if bmi_status in {"pre_obesity", "obesity"}:
        return "slightly_high"
    if bmi_status == "normal":
        return "normal"
    return "unknown"


def get_bmi_weight_range_for_mission(height_cm: Optional[float]) -> Optional[Dict[str, float]]:
    try:
        height = float(height_cm or 0)
    except (TypeError, ValueError):
        return None

    if height <= 0:
        return None

    height_m = height / 100.0

    return {
        "min": round(BMI_NORMAL_MIN * height_m * height_m, 1),
        "max": round(BMI_NORMAL_MAX * height_m * height_m, 1),
        "avg": round(BMI_NORMAL_MID * height_m * height_m, 1),
    }


# ============================
# 요청 모델
# ============================

class GenerateInitialMissionsRequest(BaseModel):
    force_regenerate: bool = False

class RefreshSlotRequest(BaseModel):
    slot_code: str
    use_mission_coin_if_needed: bool = True

class CurrentMissionResponse(BaseModel):
    id: int
    slot_code: str
    mission_type: str
    title: str
    description: str
    status: str
    params: Dict[str, Any]
    progress: Dict[str, Any]
    reward_exp: int
    reward_coins: int
    reason: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    is_completed: bool
    is_refreshed: bool
    generation_source: Optional[str] = None
    validation_status: Optional[str] = None
    validation_reason: Optional[str] = None
    generation_provider: Optional[str] = None
    generation_attempt_count: Optional[int] = 0
    fallback_reason: Optional[str] = None
    generation_meta: Optional[Dict[str, Any]] = None

class CompleteSlotRequest(BaseModel):
    slot_code: str
    client_payload: Dict[str, Any] = Field(default_factory=dict)
    # true: 완료 후 다음 미션 자동 생성, false: 완료/보상만 처리
    regenerate_after_complete: bool = True

class StartSlotRequest(BaseModel):
    slot_code: str

class RetrySlotRequest(BaseModel):
    slot_code: str
    use_mission_coin_if_needed: bool = False

# ============================
# 신버전 미션 검수/요약 헬퍼
# ============================

FORBIDDEN_PHRASES = [
    "오늘까지",
    "오늘 안에",
    "내일까지",
    "못하면 실패",
    "제한 시간 내",
    "마감",
    "기간 내 완료",
    "24시간 안에",
    "하루 안에",
]

FORBIDDEN_REASON_PHRASES = FORBIDDEN_PHRASES + [
    "반드시 해야 합니다",
    "위험합니다",
    "진단",
    "질병",
    "치료",
    "의심",
    "정확히",
]

GENERIC_REASON_PATTERNS = [
    "ai가 사용자 건강 데이터를 바탕으로 생성한 미션입니다",
    "ai가 생성한 미션입니다",
    "사용자 데이터를 바탕으로 추천했어요",
    "건강 데이터를 바탕으로 추천했어요",
]

REASON_MAX_LENGTH = 120
REASON_MIN_LENGTH = 18


def get_slot_behavior_summary(
    behavior_summary: Optional[Dict[str, Any]],
    slot_code: str,
) -> Dict[str, Any]:
    if not behavior_summary:
        return {}
    return (behavior_summary.get("slots") or {}).get(slot_code, {}) or {}


def get_recent_resolved_mission_history(
    db: Session,
    user_id: int,
    limit: int = BEHAVIOR_HISTORY_WINDOW,
) -> List[Dict[str, Any]]:
    resolved_missions = (
        db.query(UserMission)
        .filter(UserMission.user_id == user_id)
        .filter(UserMission.status.in_(["completed", "refreshed"]))
        .order_by(UserMission.updated_at.desc(), UserMission.id.desc())
        .limit(max(limit, 1))
        .all()
    )

    return [
        {
            "slot_code": mission.slot_code,
            "mission_type": mission.mission_type,
            "status": mission.status,
            "started_at": mission.started_at.isoformat() if mission.started_at else None,
            "generation_source": mission.generation_source,
        }
        for mission in resolved_missions
    ]


def build_behavior_adaptation_summary(
    db: Session,
    user_id: int,
    limit: int = BEHAVIOR_HISTORY_WINDOW,
) -> Dict[str, Any]:
    return get_effective_behavior_summary(
        db,
        user_id,
        lazy_refresh=True,
    )


def refresh_behavior_profile_snapshot(
    db: Session,
    user_id: int,
) -> None:
    upsert_user_behavior_profile(
        db,
        user_id,
        recent_window_size=BEHAVIOR_HISTORY_WINDOW,
    )


def get_behavior_preferred_type(
    slot_code: str,
    behavior_summary: Optional[Dict[str, Any]],
    *,
    exclude_types: Optional[List[str]] = None,
) -> Optional[str]:
    slot_behavior = get_slot_behavior_summary(behavior_summary, slot_code)
    exclude = {mission_type for mission_type in (exclude_types or []) if mission_type}

    for mission_type in slot_behavior.get("preferred_types") or []:
        if mission_type not in exclude:
            return mission_type
    return None


def choose_candidate(candidates: List[int], previous_value: Optional[int] = None) -> int:
    if not candidates:
        raise ValueError("후보값이 비어 있습니다.")

    for candidate in candidates:
        if previous_value is None or candidate != previous_value:
            return candidate
    return candidates[0]


def build_step_target_mission_data(target_steps: int) -> Dict[str, Any]:
    return {
        "slot_code": "A",
        "title": f"{target_steps}보 걷기에 도전해보세요",
        "description": f"지금부터 {target_steps}보를 더 걸어보세요.",
        "suggested_type": "A1_STEP_TARGET",
        "params": {
            "target_steps": target_steps,
        },
    }


def build_active_kcal_mission_data(target_kcal: int) -> Dict[str, Any]:
    return {
        "slot_code": "A",
        "title": f"활동칼로리 {target_kcal}kcal 달성에 도전해보세요",
        "description": f"지금부터 {target_kcal}kcal를 더 쌓아보세요.",
        "suggested_type": "A2_ACTIVE_KCAL_TARGET",
        "params": {
            "target_kcal": target_kcal,
        },
    }


def build_stretch_mission_data(duration_min: int) -> Dict[str, Any]:
    return {
        "slot_code": "B",
        "title": f"스트레칭 {duration_min}분을 완료해보세요",
        "description": f"가볍게 {duration_min}분 동안 몸을 풀어보세요.",
        "suggested_type": "B1_TIMER_STRETCH",
        "params": {
            "duration_min": duration_min,
        },
    }


def build_sleep_prep_mission_data(duration_min: int) -> Dict[str, Any]:
    return {
        "slot_code": "B",
        "title": f"편안한 휴식을 위한 {duration_min}분 루틴을 진행해보세요",
        "description": f"부담 없는 {duration_min}분 휴식 루틴으로 몸과 마음을 정리해보세요.",
        "suggested_type": "B2_SLEEP_PREP",
        "params": {
            "duration_min": duration_min,
        },
    }


def build_routine_check_mission_data(
    routine_name: str,
    repeat_count: int,
    interval_min: int,
) -> Dict[str, Any]:
    return {
        "slot_code": "B",
        "title": f"{routine_name} 루틴 {repeat_count}회 체크해보세요",
        "description": f"{interval_min}분마다 {routine_name} 루틴을 체크해보세요.",
        "suggested_type": "B3_ROUTINE_CHECK",
        "params": {
            "routine_name": routine_name,
            "repeat_count": repeat_count,
            "interval_min": interval_min,
        },
    }


def build_checkin_mission_data(
    title: str,
    description_template: str,
    min_length: int,
) -> Dict[str, Any]:
    return {
        "slot_code": "C",
        "title": title,
        "description": description_template.format(min_length=min_length),
        "suggested_type": "C1_HEALTH_CHECKIN",
        "params": {
            "min_length": min_length,
        },
    }


def contains_forbidden_phrase(text: Optional[str]) -> bool:
    if not text:
        return False
    normalized = text.strip()
    return any(phrase in normalized for phrase in FORBIDDEN_PHRASES)


def normalize_reason_text(reason: Optional[str]) -> str:
    if not reason:
        return ""
    return re.sub(r"\s+", " ", str(reason).strip())


def contains_forbidden_reason_phrase(reason: Optional[str]) -> bool:
    normalized = normalize_reason_text(reason)
    if not normalized:
        return False
    return any(phrase in normalized for phrase in FORBIDDEN_REASON_PHRASES)


def is_generic_reason(reason: Optional[str]) -> bool:
    normalized = normalize_reason_text(reason).lower()
    if not normalized:
        return True

    if normalized in GENERIC_REASON_PATTERNS:
        return True

    return (
        "추천" not in normalized
        and "구성" not in normalized
        and "조정" not in normalized
        and "기록" not in normalized
        and "루틴" not in normalized
        and "걸음" not in normalized
        and "칼로리" not in normalized
        and "스트레칭" not in normalized
        and "휴식" not in normalized
        and "컨디션" not in normalized
    )


def reason_matches_type(mission_type: str, reason: Optional[str]) -> bool:
    normalized = normalize_reason_text(reason)
    if not normalized:
        return False

    keyword_groups = {
        "A1_STEP_TARGET": ["걸음", "보", "걷", "활동 패턴"],
        "A2_ACTIVE_KCAL_TARGET": ["활동량", "활동", "움직", "칼로리"],
        "B1_TIMER_STRETCH": ["스트레칭", "루틴", "몸을 풀", "실천"],
        "B2_SLEEP_PREP": ["휴식", "회복", "생활 패턴", "루틴"],
        "B3_ROUTINE_CHECK": ["반복", "습관", "루틴", "체크"],
        "C1_HEALTH_CHECKIN": ["기록", "컨디션", "상태", "패턴"],
    }

    keywords = keyword_groups.get(mission_type, [])
    return any(keyword in normalized for keyword in keywords)


def build_reason_prefix(
    *,
    comparison: Optional[Dict[str, Any]] = None,
    activity_summary: Optional[Dict[str, Any]] = None,
    public_average: Optional[Dict[str, Any]] = None,
    mission_type: Optional[str] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> str:
    comparison = comparison or {}
    activity_summary = activity_summary or {}
    public_average = public_average or {}

    slot_code = str(mission_type or "").strip()[:1]
    slot_behavior = get_slot_behavior_summary(behavior_summary, slot_code)
    preferred_types = list(slot_behavior.get("preferred_types") or [])
    discouraged_types = list(slot_behavior.get("discouraged_types") or [])
    difficulty_bias = str(slot_behavior.get("difficulty_bias") or "neutral")

    confidence = str(slot_behavior.get("confidence") or behavior_summary.get("confidence") or "low") if behavior_summary else "low"

    if mission_type and mission_type in preferred_types:
        preferred_prefix = {
            "A": "최근 자주 이어온 활동형 흐름을 반영해",
            "B": "최근 자주 이어온 루틴형 흐름을 반영해",
            "C": "최근 자연스럽게 이어온 기록형 흐름을 반영해",
        }
        return preferred_prefix.get(slot_code, "최근 잘 맞았던 실천 흐름을 반영해")

    if mission_type and mission_type in discouraged_types and confidence in {"medium", "high"}:
        return "최근 새로고침이 잦았던 유형은 비중을 낮추고"

    if difficulty_bias == "up":
        return "최근 달성 흐름을 반영해 난이도를 조금 높여"

    if difficulty_bias == "down":
        return "부담 없이 이어가기 좋도록 익숙한 방식으로"

    step_status = str(comparison.get("step_status") or "")
    activity_status = str(comparison.get("activity_status") or "")
    weight_status = str(comparison.get("weight_status") or "")
    avg_steps_7d = int(activity_summary.get("avg_steps_7d", 0) or 0)
    avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)

    if step_status == "below_average" or avg_steps_7d < 4000:
        return "최근 걸음 수와 활동 패턴을 바탕으로"
    if activity_status == "low" or avg_active_kcal_7d < 150:
        return "최근 활동량과 실천 흐름을 바탕으로"
    if weight_status in ["slightly_high", "low"]:
        return "BMI 기준 체중 흐름과 최근 활동 기록을 바탕으로"
    if public_average.get("source") != "unavailable":
        return "최근 활동 기록과 공공데이터 평균 참고값을 바탕으로"
    return "최근 활동 기록을 바탕으로"


def generate_reason_fallback(
    *,
    mission_type: str,
    params: Optional[Dict[str, Any]] = None,
    comparison: Optional[Dict[str, Any]] = None,
    activity_summary: Optional[Dict[str, Any]] = None,
    public_average: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> str:
    prefix = build_reason_prefix(
        comparison=comparison,
        activity_summary=activity_summary,
        public_average=public_average,
        mission_type=mission_type,
        behavior_summary=behavior_summary,
    )

    templates = {
        "A1_STEP_TARGET": f"{prefix} 부담 없이 시작할 수 있는 걸음 미션으로 추천했어요.",
        "A2_ACTIVE_KCAL_TARGET": f"{prefix} 가볍게 움직이며 실천할 수 있는 활동 미션으로 구성했어요.",
        "B1_TIMER_STRETCH": f"{prefix} 가볍게 실천할 수 있는 스트레칭 루틴으로 추천했어요.",
        "B2_SLEEP_PREP": f"{prefix} 꾸준히 이어가기 쉬운 휴식 루틴으로 조정했어요.",
        "B3_ROUTINE_CHECK": f"{prefix} 작은 행동을 반복하며 습관을 만들 수 있는 체크형 루틴으로 구성했어요.",
        "C1_HEALTH_CHECKIN": f"{prefix} 현재 상태를 직접 기록하며 건강 패턴을 돌아볼 수 있도록 기록형 미션을 추천했어요.",
    }

    return templates.get(
        mission_type,
        f"{prefix} 현재 상태에 맞게 부담 없이 실천할 수 있는 미션으로 추천했어요.",
    )


def sanitize_mission_reason(
    *,
    raw_reason: Optional[str],
    mission_type: str,
    params: Optional[Dict[str, Any]] = None,
    comparison: Optional[Dict[str, Any]] = None,
    activity_summary: Optional[Dict[str, Any]] = None,
    public_average: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> str:
    reason = normalize_reason_text(raw_reason)

    should_fallback = (
        not reason
        or len(reason) < REASON_MIN_LENGTH
        or len(reason) > REASON_MAX_LENGTH
        or contains_forbidden_reason_phrase(reason)
        or not reason_matches_type(mission_type, reason)
        or is_generic_reason(reason)
    )

    if should_fallback:
        return generate_reason_fallback(
            mission_type=mission_type,
            params=params,
            comparison=comparison,
            activity_summary=activity_summary,
            public_average=public_average,
            behavior_summary=behavior_summary,
        )

    return reason


def normalize_user_goal_for_mission(goal: Optional[str]) -> str:
    """
    AI 미션 생성에 사용할 사용자 목표값을 서비스 정책에 맞게 정규화한다.

    현재 프론트 목표 선택지는:
    - 건강 유지
    - 체중 감량

    예전에 DB에 저장된 "근육 증가"나 알 수 없는 값은
    미션 생성 안정성을 위해 "건강 유지"로 처리한다.
    """
    normalized_goal = str(goal or "").strip()

    if normalized_goal == "체중 감량":
        return "체중 감량"

    return "건강 유지"

def calc_age_from_birth_date(birth_date: Optional[date]) -> Optional[int]:
    if not birth_date:
        return None

    today = date.today()
    age = today.year - birth_date.year

    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1

    return max(age, 0)


def resolve_effective_age(user: Optional[User], inbody: UserInbody) -> Optional[int]:
    birth_age = calc_age_from_birth_date(getattr(user, "birth_date", None)) if user else None

    if birth_age is not None:
        return birth_age

    return inbody.age

def build_user_profile_summary(
    inbody: UserInbody,
    user: Optional[User] = None,
) -> Dict[str, Any]:
    effective_age = resolve_effective_age(user, inbody)

    return {
        "age": effective_age,
        "gender": inbody.gender,
        "height_cm": inbody.height,
        "weight_kg": inbody.weight,
        "bmi": inbody.bmi,
        "target_weight": inbody.target_weight,
        "goal": normalize_user_goal_for_mission(inbody.goal),
        "body_fat": inbody.body_fat,
    }

def get_recent_activity_records(
    db: Session,
    user_id: int,
    days: int = 7,
) -> List[UserActivity]:
    since = datetime.utcnow() - timedelta(days=max(days, 1))

    return (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user_id)
        .filter(UserActivity.recorded_at >= since)
        .order_by(UserActivity.recorded_at.desc(), UserActivity.id.desc())
        .all()
    )



def build_activity_summary(
    activity: Optional[UserActivity],
    recent_activities: Optional[List[UserActivity]] = None,
) -> Dict[str, Any]:
    recent_activities = recent_activities or ([] if activity is None else [activity])
    latest_activity = activity or (recent_activities[0] if recent_activities else None)

    if not latest_activity and not recent_activities:
        return {
            "avg_steps_7d": 0,
            "avg_active_kcal_7d": 0,
            "today_steps": 0,
            "today_active_kcal": 0,
            "sleep_minutes_latest": 0,
            "avg_sleep_minutes_7d": 0,
        }

    steps_samples = [int(a.steps or 0) for a in recent_activities]
    kcal_samples = [int(a.calories or 0) for a in recent_activities]
    sleep_samples = [
        int(a.sleep_minutes or 0)
        for a in recent_activities
        if a.sleep_minutes is not None
    ]

    avg_steps_7d = round(sum(steps_samples) / len(steps_samples)) if steps_samples else 0
    avg_active_kcal_7d = round(sum(kcal_samples) / len(kcal_samples)) if kcal_samples else 0
    avg_sleep_minutes_7d = round(sum(sleep_samples) / len(sleep_samples)) if sleep_samples else 0

    return {
        "avg_steps_7d": avg_steps_7d,
        "avg_active_kcal_7d": avg_active_kcal_7d,
        "today_steps": int(latest_activity.steps or 0),
        "today_active_kcal": int(latest_activity.calories or 0),
        "sleep_minutes_latest": int(latest_activity.sleep_minutes or 0),
        "avg_sleep_minutes_7d": avg_sleep_minutes_7d,
    }


def normalize_age_group(age: Optional[int]) -> Optional[int]:
    """
    표준 데이터 테이블은 10,20,30,40,50,60 단위로 저장되어 있으므로
    사용자 나이를 가장 가까운 '연령대' 기준으로 정규화한다.
    """
    if age is None:
        return None

    try:
        age = int(age)
    except (TypeError, ValueError):
        return None

    age_group = (age // 10) * 10

    # 현재 seed 구조가 10~60대 중심이라 안전하게 범위를 고정
    if age_group < 10:
        age_group = 10
    if age_group > 60:
        age_group = 60

    return age_group


async def get_public_average_summary(
    db: Session,
    inbody: UserInbody,
    user: Optional[User] = None,
) -> Dict[str, Any]:
    """
    1순위: KOSIS 국민건강보험공단 건강검진통계 평균 신장/체중
    2순위: DB health_standards 테이블 조회
    3순위: 그래도 없으면 None 기반 안전 반환
    """

    effective_age = resolve_effective_age(user, inbody)
    age_group = normalize_age_group(effective_age)
    gender = (inbody.gender or "").strip().lower()
    public_api_age = effective_age or (inbody.age or 20)

    # 1) AI 미션 입력값도 화면 평균과 동일하게 KOSIS 기준을 우선 사용한다.
    kosis_avg = await KosisHealthStatsService.get_average_metrics(
        user_age=public_api_age,
        user_gender=gender or "male",
    )

    if kosis_avg:
        return {
            "age_group": age_group,
            "requested_test_age": public_api_age,
            "gender": gender,
            "avg_height": kosis_avg.get("avg_height"),
            "avg_weight": kosis_avg.get("avg_weight"),
            "avg_body_fat": kosis_avg.get("avg_body_fat"),
            "avg_body_fat_basis": kosis_avg.get("avg_body_fat_basis"),
            "is_body_fat_estimated": kosis_avg.get("is_body_fat_estimated"),
            "avg_bmi": kosis_avg.get("avg_bmi"),
            "sample_count": kosis_avg.get("sample_count"),
            "prescription": kosis_avg.get("prescription"),
            "source": "kosis_health_checkup",
            "source_detail": "KOSIS 국민건강보험공단 건강검진통계 평균 신장/체중",
        }

    standard = None
    if age_group is not None and gender:
        standard = (
            db.query(HealthStandard)
            .filter(HealthStandard.gender == gender)
            .filter(HealthStandard.age_group == age_group)
            .first()
        )

    # 2) KOSIS가 실패하거나 KOSIS 키가 없으면 DB 표준 데이터 사용
    if standard:
        avg_height = float(standard.avg_height) if standard.avg_height is not None else None
        avg_weight = float(standard.avg_weight) if standard.avg_weight is not None else None
        avg_body_fat = float(standard.avg_body_fat) if standard.avg_body_fat is not None else None

        avg_bmi = None
        if avg_height and avg_weight and avg_height > 0:
            avg_bmi = round(avg_weight / ((avg_height / 100) ** 2), 1)

        return {
            "age_group": age_group,
            "gender": gender,
            "avg_height": avg_height,
            "avg_weight": avg_weight,
            "avg_body_fat": avg_body_fat,
            "avg_bmi": avg_bmi,
            "sample_count": None,
            "prescription": None,
            "source": "health_standards",
        }

    # 3) 최종 fallback
    # KOSIS/DB가 없더라도 국민체력100 공공 API는 더 이상 호출하지 않습니다.
    return {
        "age_group": age_group,
        "requested_test_age": effective_age,
        "gender": gender,
        "avg_height": None,
        "avg_weight": None,
        "avg_body_fat": None,
        "avg_bmi": None,
        "sample_count": None,
        "prescription": None,
        "source": "unavailable",
    }


def build_health_gap_summary(
    inbody: UserInbody,
    activity: Optional[UserActivity],
    public_average: Dict[str, Any],
) -> Dict[str, Any]:
    """
    GPT에게 전달할 건강 요약.

    - 체중/BMI 상태는 한국 성인 BMI 기준으로 판단한다.
    - 공공데이터 평균은 정상/위험 판정 기준이 아니라 참고 평균값으로만 제공한다.
    - 체지방률은 현재 별도 의학 기준표가 없으므로 공공 평균과의 차이만 참고값으로 제공한다.
    """

    public_average = public_average or {}
    avg_weight = public_average.get("avg_weight")
    avg_bmi = public_average.get("avg_bmi")
    avg_body_fat = public_average.get("avg_body_fat")

    public_weight_gap_kg = None
    public_bmi_gap = None
    public_body_fat_gap = None

    if inbody.weight is not None and avg_weight is not None:
        public_weight_gap_kg = round(float(inbody.weight) - float(avg_weight), 1)

    if inbody.bmi is not None and avg_bmi is not None:
        public_bmi_gap = round(float(inbody.bmi) - float(avg_bmi), 1)

    if inbody.body_fat is not None and avg_body_fat is not None:
        public_body_fat_gap = round(float(inbody.body_fat) - float(avg_body_fat), 1)

    bmi_status = get_bmi_status_for_mission(inbody.bmi)
    weight_status = get_weight_status_by_bmi(inbody.bmi)
    normal_weight_range = get_bmi_weight_range_for_mission(inbody.height)

    # 기존 로그/프롬프트 호환성을 위해 key 이름은 유지하되, 값의 의미를 명확히 한다.
    weight_gap_kg = None
    if normal_weight_range and inbody.weight is not None:
        weight = float(inbody.weight)
        if weight < normal_weight_range["min"]:
            weight_gap_kg = round(weight - normal_weight_range["min"], 1)
        elif weight > normal_weight_range["max"]:
            weight_gap_kg = round(weight - normal_weight_range["max"], 1)
        else:
            weight_gap_kg = 0.0

    today_steps = activity.steps if activity and activity.steps else 0
    today_kcal = int(activity.calories) if activity and activity.calories else 0

    if today_steps >= 7000:
        step_status = "good"
    elif today_steps >= 4000:
        step_status = "moderate"
    else:
        step_status = "below_average"

    if today_kcal >= 300:
        activity_status = "good"
    elif today_kcal >= 150:
        activity_status = "moderate"
    else:
        activity_status = "low"

    return {
        "weight_gap_kg": weight_gap_kg,
        "bmi_gap": None,
        "body_fat_gap": public_body_fat_gap,
        "weight_status": weight_status,
        "bmi_status": bmi_status,
        "body_fat_status": "reference_only" if public_body_fat_gap is not None else "unknown",
        "normal_weight_range": normal_weight_range,
        "bmi_basis": "korean_adult_bmi_18.5_22.9",
        "public_weight_gap_kg": public_weight_gap_kg,
        "public_bmi_gap": public_bmi_gap,
        "public_body_fat_gap": public_body_fat_gap,
        "public_average_is_reference_only": True,
        "step_status": step_status,
        "activity_status": activity_status,
        "public_data_source": public_average.get("source"),
    }


def build_comparison_summary(
    inbody: UserInbody,
    activity: Optional[UserActivity],
    public_average: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    미션 생성용 간단 비교 요약.

    weight_status는 공공 평균 체중이 아니라 한국 성인 BMI 기준으로만 판단한다.
    public_average는 별도 참고값으로 GPT payload에 전달된다.
    """

    step_status = "below_average"
    activity_status = "low"
    weight_status = get_weight_status_by_bmi(inbody.bmi)

    today_steps = activity.steps if activity and activity.steps else 0
    today_kcal = int(activity.calories) if activity and activity.calories else 0

    if today_steps >= 7000:
        step_status = "good"
    elif today_steps >= 4000:
        step_status = "moderate"

    if today_kcal >= 300:
        activity_status = "good"
    elif today_kcal >= 150:
        activity_status = "moderate"

    return {
        "step_status": step_status,
        "activity_status": activity_status,
        "weight_status": weight_status,
        "weight_status_basis": "korean_adult_bmi_18.5_22.9",
    }

def infer_slot_code_from_type(suggested_type: Optional[str]) -> Optional[str]:
    suggested_type = str(suggested_type or "").strip()
    if not suggested_type:
        return None

    for slot_code, allowed_types in ALLOWED_TYPES_BY_SLOT.items():
        if suggested_type in allowed_types:
            return slot_code

    return None


def normalize_generated_mission(mission: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(mission or {})

    slot_code = normalized.get("slot_code")
    suggested_type = normalized.get("suggested_type")

    if slot_code is None or str(slot_code).strip() == "":
        inferred = infer_slot_code_from_type(suggested_type)
        if inferred:
            normalized["slot_code"] = inferred

    return normalized

def apply_a_type_minimum_label(mission_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    A타입 미션이 서버 기준 최소값이면 title/description에 '최소' 안내를 붙인다.

    목적:
    - 사용자가 2500보, 80kcal보다 더 낮은 미션이 있다고 착각해서
      계속 새로고침하는 상황을 줄이기 위함.
    - A타입에만 적용한다.
    """

    copied = dict(mission_data or {})
    mission_type = str(
        copied.get("suggested_type")
        or copied.get("mission_type")
        or ""
    ).strip()

    params = copied.get("params") or {}

    # A1: 걸음 수 최소값
    if mission_type == "A1_STEP_TARGET":
        target_steps = int(params.get("target_steps", 0) or 0)
        min_steps = min(STEP_TARGET_MASTER)

        if target_steps == min_steps:
            title = str(copied.get("title") or "").strip()
            description = str(copied.get("description") or "").strip()

            if "최소" not in title:
                copied["title"] = f"최소 {target_steps}보 걷기에 도전해보세요"

            if "최소" not in description:
                copied["description"] = (
                    f"현재 기준 가장 낮은 걸음 미션입니다. "
                    f"지금부터 최소 {target_steps}보를 더 걸어보세요."
                )

    # A2: 활동 칼로리 최소값
    elif mission_type == "A2_ACTIVE_KCAL_TARGET":
        target_kcal = int(params.get("target_kcal", 0) or 0)
        min_kcal = min(KCAL_TARGET_MASTER)

        if target_kcal == min_kcal:
            title = str(copied.get("title") or "").strip()
            description = str(copied.get("description") or "").strip()

            if "최소" not in title:
                copied["title"] = f"최소 활동칼로리 {target_kcal}kcal 달성에 도전해보세요"

            if "최소" not in description:
                copied["description"] = (
                    f"현재 기준 가장 낮은 활동칼로리 미션입니다. "
                    f"지금부터 최소 {target_kcal}kcal를 더 쌓아보세요."
                )

    return copied


def validate_mission_shape(mission: Dict[str, Any]) -> None:
    required_keys = ["slot_code", "title", "description", "suggested_type", "params"]

    for key in required_keys:
        if key not in mission:
            raise ValueError(f"GPT 미션 필드 누락: {key}")
        if mission[key] is None:
            raise ValueError(f"GPT 미션 필드 값이 비어 있습니다: {key}")

    if not isinstance(mission["slot_code"], str) or not mission["slot_code"].strip():
        raise ValueError("slot_code는 비어 있지 않은 문자열이어야 합니다.")

    if not isinstance(mission["title"], str) or not mission["title"].strip():
        raise ValueError("title은 비어 있지 않은 문자열이어야 합니다.")

    if not isinstance(mission["description"], str) or not mission["description"].strip():
        raise ValueError("description은 비어 있지 않은 문자열이어야 합니다.")

    if not isinstance(mission["suggested_type"], str) or not mission["suggested_type"].strip():
        raise ValueError("suggested_type은 비어 있지 않은 문자열이어야 합니다.")

    if not isinstance(mission["params"], dict):
        raise ValueError("params는 객체(JSON object)여야 합니다.")

    if "reason" in mission and mission["reason"] is not None and not isinstance(mission["reason"], str):
        raise ValueError("reason은 문자열이어야 합니다.")


def validate_slot_and_type(slot_code: str, suggested_type: str) -> None:
    if slot_code not in ALLOWED_TYPES_BY_SLOT:
        raise ValueError(f"허용되지 않은 slot_code: {slot_code}")

    if suggested_type not in ALLOWED_TYPES_BY_SLOT[slot_code]:
        raise ValueError(
            f"slot_code {slot_code} 에 suggested_type {suggested_type} 는 허용되지 않습니다."
        )


def validate_forbidden_text(title: str, description: str) -> None:
    if contains_forbidden_phrase(title):
        raise ValueError(f"금지 문구가 title에 포함되어 있습니다: {title}")
    if contains_forbidden_phrase(description):
        raise ValueError(f"금지 문구가 description에 포함되어 있습니다: {description}")


def validate_params_by_type(suggested_type: str, params: Dict[str, Any]) -> None:
    if suggested_type == "A1_STEP_TARGET":
        if not isinstance(params.get("target_steps"), int):
            raise ValueError("A1_STEP_TARGET은 params.target_steps(int)가 필요합니다.")

    elif suggested_type == "A2_ACTIVE_KCAL_TARGET":
        if not isinstance(params.get("target_kcal"), int):
            raise ValueError("A2_ACTIVE_KCAL_TARGET은 params.target_kcal(int)가 필요합니다.")

    elif suggested_type == "B1_TIMER_STRETCH":
        if not isinstance(params.get("duration_min"), int):
            raise ValueError("B1_TIMER_STRETCH는 params.duration_min(int)이 필요합니다.")

    elif suggested_type == "B2_SLEEP_PREP":
        if not isinstance(params.get("duration_min"), int):
            raise ValueError("B2_SLEEP_PREP는 params.duration_min(int)이 필요합니다.")

    elif suggested_type == "B3_ROUTINE_CHECK":
        if not isinstance(params.get("routine_name"), str):
            raise ValueError("B3_ROUTINE_CHECK는 params.routine_name(str)이 필요합니다.")
        if not isinstance(params.get("repeat_count"), int):
            raise ValueError("B3_ROUTINE_CHECK는 params.repeat_count(int)가 필요합니다.")
        if not isinstance(params.get("interval_min"), int):
            raise ValueError("B3_ROUTINE_CHECK는 params.interval_min(int)가 필요합니다.")

    elif suggested_type == "C1_HEALTH_CHECKIN":
        if not isinstance(params.get("min_length"), int):
            raise ValueError("C1_HEALTH_CHECKIN은 params.min_length(int)가 필요합니다.")

    else:
        raise ValueError(f"알 수 없는 suggested_type: {suggested_type}")


def validate_initial_missions(missions: List[Dict[str, Any]]) -> None:
    if len(missions) != 3:
        raise ValueError("초기 미션 생성은 정확히 3개여야 합니다.")

    suggested_types: List[str] = []
    slot_codes: List[str] = []

    for mission in missions:
        validate_mission_shape(mission)
        validate_forbidden_text(mission["title"], mission["description"])
        validate_slot_and_type(mission["slot_code"], mission["suggested_type"])
        validate_params_by_type(mission["suggested_type"], mission["params"])

        slot_codes.append(str(mission["slot_code"]).strip())
        suggested_types.append(mission["suggested_type"])

    if sorted(slot_codes) != ["A", "B", "C"]:
        raise ValueError("초기 미션은 A/B/C 슬롯 각각 1개씩 있어야 합니다.")

    if len(set(suggested_types)) != 3:
        raise ValueError("초기 미션 3개는 mission type이 중복되면 안 됩니다.")

def validate_single_slot_mission(
    mission: Dict[str, Any],
    expected_slot_code: str,
) -> None:
    validate_mission_shape(mission)
    validate_forbidden_text(mission["title"], mission["description"])

    actual_slot_code = str(mission.get("slot_code") or "").strip()
    if actual_slot_code != expected_slot_code:
        raise ValueError(
            f"단일 슬롯 미션의 slot_code가 올바르지 않습니다. expected={expected_slot_code}, actual={actual_slot_code}"
        )

    validate_slot_and_type(expected_slot_code, mission["suggested_type"])
    validate_params_by_type(mission["suggested_type"], mission["params"])

def build_initial_slot_fallback_mission(
    slot_code: str,
    activity_summary: Dict[str, Any],
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    avg_steps_7d = int(activity_summary.get("avg_steps_7d", 0) or 0)
    avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
    avg_sleep_minutes_7d = int(activity_summary.get("avg_sleep_minutes_7d", 0) or 0)

    preferred_type = get_behavior_preferred_type(slot_code, behavior_summary)
    slot_behavior = get_slot_behavior_summary(behavior_summary, slot_code)
    difficulty_bias = str(slot_behavior.get("difficulty_bias") or "neutral")

    if slot_code == "A":
        if avg_steps_7d <= 2000:
            step_candidates = [2500, 3000, 3500]
        elif avg_steps_7d <= 4000:
            step_candidates = [3500, 4000, 4500]
        elif avg_steps_7d <= 6000:
            step_candidates = [4500, 5000, 5500]
        elif avg_steps_7d <= 8000:
            step_candidates = [5500, 6000, 7000]
        else:
            step_candidates = [7000, 8000, 9000]

        if avg_active_kcal_7d <= 80:
            kcal_candidates = [80, 100, 120]
        elif avg_active_kcal_7d <= 140:
            kcal_candidates = [100, 120, 150]
        elif avg_active_kcal_7d <= 200:
            kcal_candidates = [150, 180, 220]
        elif avg_active_kcal_7d <= 280:
            kcal_candidates = [180, 220, 250]
        else:
            kcal_candidates = [220, 250, 300]

        step_candidates = shift_numeric_candidates_by_bias(step_candidates, STEP_TARGET_MASTER, difficulty_bias)
        kcal_candidates = shift_numeric_candidates_by_bias(kcal_candidates, KCAL_TARGET_MASTER, difficulty_bias)

        if preferred_type == "A1_STEP_TARGET" and avg_active_kcal_7d > 120:
            return build_step_target_mission_data(choose_candidate(step_candidates))

        return build_active_kcal_mission_data(choose_candidate(kcal_candidates))

    if slot_code == "B":
        stretch_candidates = [5, 10, 15] if avg_active_kcal_7d <= 150 else [10, 15, 20]
        stretch_candidates = shift_numeric_candidates_by_bias(
            stretch_candidates,
            STRETCH_DURATION_MASTER,
            difficulty_bias,
        )

        if avg_sleep_minutes_7d and avg_sleep_minutes_7d < 360:
            sleep_candidates = [10, 15]
        elif avg_sleep_minutes_7d and avg_sleep_minutes_7d < 420:
            sleep_candidates = [15, 20]
        else:
            sleep_candidates = [15, 20, 25]
        sleep_candidates = shift_numeric_candidates_by_bias(
            sleep_candidates,
            SLEEP_PREP_DURATION_MASTER,
            difficulty_bias,
        )

        if avg_sleep_minutes_7d == 0:
            if preferred_type == "B1_TIMER_STRETCH":
                return build_stretch_mission_data(choose_candidate(stretch_candidates))
            return build_b3_routine_fallback_mission(activity_summary, behavior_summary=behavior_summary)

        if preferred_type == "B1_TIMER_STRETCH":
            return build_stretch_mission_data(choose_candidate(stretch_candidates))
        if preferred_type == "B3_ROUTINE_CHECK":
            return build_b3_routine_fallback_mission(activity_summary, behavior_summary=behavior_summary)

        return build_sleep_prep_mission_data(choose_candidate(sleep_candidates))

    return build_c1_fallback_mission(behavior_summary=behavior_summary)


def rebalance_initial_missions(
    missions: List[Dict[str, Any]],
    activity_summary: Dict[str, Any],
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    초기 3개 미션 타입 균형 보정.

    주의:
    - GPT가 만든 미션을 무조건 바꾸지 않는다.
    - 정말 타입 조합이 너무 단조롭거나 데이터와 맞지 않을 때만 보정한다.
    - B3_ROUTINE_CHECK도 초기 B 슬롯의 정상 핵심 후보로 인정한다.
    """

    mission_map = {
        m["slot_code"]: m
        for m in missions
        if m.get("slot_code") in ["A", "B", "C"]
    }

    if sorted(mission_map.keys()) != ["A", "B", "C"]:
        return missions

    avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
    avg_sleep_minutes_7d = int(activity_summary.get("avg_sleep_minutes_7d", 0) or 0)

    a_type = mission_map["A"].get("suggested_type")
    b_type = mission_map["B"].get("suggested_type")

    # 활동량이 정말 낮은 경우에만 A2를 강하게 우선한다.
    # 기존 180 기준은 너무 넓어서 GPT 결과가 자주 server_rebalance로 바뀔 수 있음.
    if avg_active_kcal_7d <= 150 and a_type != "A2_ACTIVE_KCAL_TARGET":
        mission_map["A"] = build_initial_slot_fallback_mission(
            "A",
            activity_summary,
            behavior_summary,
        )
        a_type = mission_map["A"]["suggested_type"]

    # 수면 데이터가 아예 없는데 B2_SLEEP_PREP가 나오면 B3로 보정한다.
    # 수면 데이터가 없는 상태에서 수면 준비 미션은 근거가 약하기 때문.
    if avg_sleep_minutes_7d == 0 and b_type == "B2_SLEEP_PREP":
        mission_map["B"] = build_b3_routine_fallback_mission(
            activity_summary,
            behavior_summary=behavior_summary,
        )
        b_type = mission_map["B"]["suggested_type"]

    # 수면 데이터가 있고, 실제로 수면이 낮으면 B2를 우선한다.
    elif avg_sleep_minutes_7d and avg_sleep_minutes_7d < 360 and b_type != "B2_SLEEP_PREP":
        mission_map["B"] = build_initial_slot_fallback_mission(
            "B",
            activity_summary,
            behavior_summary,
        )
        b_type = mission_map["B"]["suggested_type"]

    # A1 + B1 + C1처럼 너무 기본 조합으로만 나온 경우만 보정한다.
    # 이제 B3는 정상적인 초기 다양성 타입으로 인정한다.
    if (
        a_type != "A2_ACTIVE_KCAL_TARGET"
        and b_type not in {"B2_SLEEP_PREP", "B3_ROUTINE_CHECK"}
    ):
        mission_map["A"] = build_initial_slot_fallback_mission(
            "A",
            activity_summary,
            behavior_summary,
        )

    return [mission_map["A"], mission_map["B"], mission_map["C"]]


def validate_initial_type_balance(
    missions: List[Dict[str, Any]],
    activity_summary: Dict[str, Any],
) -> None:
    """
    초기 3개 미션 타입 균형 검수.

    B3_ROUTINE_CHECK도 초기 B 슬롯의 정상적인 핵심 타입으로 인정한다.
    """

    mission_map = {m["slot_code"]: m for m in missions}

    a_type = mission_map["A"]["suggested_type"]
    b_type = mission_map["B"]["suggested_type"]

    avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
    avg_sleep_minutes_7d = int(activity_summary.get("avg_sleep_minutes_7d", 0) or 0)

    # 기존에는 A2 또는 B2만 인정했는데,
    # 이제 B3도 루틴형 핵심 미션이므로 초기 균형 타입으로 인정한다.
    if (
        a_type != "A2_ACTIVE_KCAL_TARGET"
        and b_type not in {"B2_SLEEP_PREP", "B3_ROUTINE_CHECK"}
    ):
        raise ValueError("초기 생성은 A2, B2, B3 중 최소 1개를 포함해야 합니다.")

    # 활동량이 정말 낮은 사용자는 A2를 우선한다.
    if avg_active_kcal_7d <= 150 and a_type != "A2_ACTIVE_KCAL_TARGET":
        raise ValueError("최근 활동량이 낮은 사용자 초기 A 슬롯은 A2를 우선 포함해야 합니다.")

    # 수면 데이터가 실제로 있고, 수면 시간이 낮은 경우에만 B2를 강제한다.
    if avg_sleep_minutes_7d and avg_sleep_minutes_7d < 360 and b_type != "B2_SLEEP_PREP":
        raise ValueError("최근 수면 시간이 낮은 사용자 초기 B 슬롯은 B2를 우선 포함해야 합니다.")


def build_b3_routine_fallback_mission(
    activity_summary: Dict[str, Any],
    previous_mission_summary: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    avg_steps_7d = int(activity_summary.get("avg_steps_7d", 0) or 0)
    avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)

    prev_params = (previous_mission_summary or {}).get("params") or {}
    prev_routine_name = str(prev_params.get("routine_name", "") or "").strip()
    prev_repeat_count = int(prev_params.get("repeat_count", 0) or 0)
    prev_interval_min = int(prev_params.get("interval_min", 0) or 0)

    options = [
        {"routine_name": "물 마시기", "repeat_count": 3, "interval_min": 10},
        {"routine_name": "물 마시기", "repeat_count": 4, "interval_min": 10},
        {"routine_name": "가볍게 일어나기", "repeat_count": 3, "interval_min": 15},
    ]

    if avg_steps_7d >= 6000 or avg_active_kcal_7d >= 220:
        options = [
            {"routine_name": "물 마시기", "repeat_count": 4, "interval_min": 15},
            {"routine_name": "가볍게 일어나기", "repeat_count": 3, "interval_min": 15},
            {"routine_name": "물 마시기", "repeat_count": 3, "interval_min": 10},
        ]

    difficulty_bias = str(get_slot_behavior_summary(behavior_summary, "B").get("difficulty_bias") or "neutral")
    options = adjust_routine_candidates_by_bias(options, difficulty_bias)

    choice = options[0]
    for option in options:
        if (
            option["routine_name"] != prev_routine_name
            or option["repeat_count"] != prev_repeat_count
            or option["interval_min"] != prev_interval_min
        ):
            choice = option
            break

    return build_routine_check_mission_data(
        choice["routine_name"],
        choice["repeat_count"],
        choice["interval_min"],
    )


def build_c1_fallback_mission(
    previous_mission_summary: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    prev_title = str((previous_mission_summary or {}).get("title") or "").strip()
    prev_params = (previous_mission_summary or {}).get("params") or {}
    prev_min_length = int(prev_params.get("min_length", 0) or 0)

    variants = [
        {
            "title": "컨디션 기록 미션에 도전해보세요",
            "description": "몸 상태와 기분을 최소 {min_length}자 이상 기록해보세요.",
        },
        {
            "title": "몸 상태를 기록해보세요",
            "description": "지금 몸 상태와 컨디션 변화를 최소 {min_length}자 이상 적어보세요.",
        },
        {
            "title": "오늘 컨디션을 남겨보세요",
            "description": "지금 기분과 몸 상태를 최소 {min_length}자 이상 기록해보세요.",
        },
    ]

    difficulty_bias = str(get_slot_behavior_summary(behavior_summary, "C").get("difficulty_bias") or "neutral")
    min_length_candidates = shift_numeric_candidates_by_bias(
        [15, 20, 25],
        CHECKIN_MIN_LENGTH_MASTER,
        difficulty_bias,
    )
    min_length = choose_candidate(min_length_candidates, prev_min_length or None)

    chosen = variants[0]
    for variant in variants:
        if variant["title"] != prev_title:
            chosen = variant
            break

    return build_checkin_mission_data(chosen["title"], chosen["description"], min_length)


def get_existing_active_missions(db: Session, user_id: int) -> List[UserMission]:
    return (
        db.query(UserMission)
        .filter(UserMission.user_id == user_id)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .all()
    )


def build_existing_mission_summary(missions: List[UserMission]) -> List[Dict[str, Any]]:
    return [
        {
            "slot_code": m.slot_code,
            "mission_type": m.mission_type,
            "title": m.title,
            "description": m.content,
            "params": m.params_json or {},
            "reason": m.reason,
        }
        for m in missions
    ]


def build_previous_mission_summary(mission: Optional[UserMission]) -> Optional[Dict[str, Any]]:
    if not mission:
        return None

    return {
        "slot_code": mission.slot_code,
        "mission_type": mission.mission_type,
        "title": mission.title,
        "description": mission.content,
        "params": mission.params_json or {},
        "reason": mission.reason,
    }


def normalize_mission_text(text: Optional[str]) -> str:
    if not text:
        return ""
    normalized = re.sub(r"\s+", "", text.strip().lower())
    normalized = re.sub(r"[^0-9a-z가-힣]", "", normalized)
    return normalized


def canonicalize_mission_params(suggested_type: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    params = params or {}

    if suggested_type == "A1_STEP_TARGET":
        return {
            "target_steps": int(params.get("target_steps", 0) or 0),
        }

    if suggested_type == "A2_ACTIVE_KCAL_TARGET":
        return {
            "target_kcal": int(params.get("target_kcal", 0) or 0),
        }

    if suggested_type in ["B1_TIMER_STRETCH", "B2_SLEEP_PREP"]:
        return {
            "duration_min": int(params.get("duration_min", 0) or 0),
        }

    if suggested_type == "B3_ROUTINE_CHECK":
        return {
            "routine_name": str(params.get("routine_name", "") or "").strip().lower(),
            "repeat_count": int(params.get("repeat_count", 0) or 0),
            "interval_min": int(params.get("interval_min", 0) or 0),
        }

    if suggested_type == "C1_HEALTH_CHECKIN":
        return {
            "min_length": int(params.get("min_length", 0) or 0),
        }

    return params


def is_same_mission_as_previous(
    new_mission_data: Dict[str, Any],
    previous_mission: Optional[Dict[str, Any]],
) -> bool:
    if not previous_mission:
        return False

    new_type = str(new_mission_data.get("suggested_type") or "").strip()
    prev_type = str(
        previous_mission.get("mission_type")
        or previous_mission.get("suggested_type")
        or ""
    ).strip()

    new_title = normalize_mission_text(new_mission_data.get("title"))
    prev_title = normalize_mission_text(previous_mission.get("title"))

    if new_title and prev_title and new_title == prev_title:
        return True

    if new_type != prev_type:
        return False

    new_params = canonicalize_mission_params(new_type, new_mission_data.get("params"))
    prev_params = canonicalize_mission_params(prev_type, previous_mission.get("params"))

    return new_params == prev_params


def validate_not_same_as_previous(
    new_mission_data: Dict[str, Any],
    previous_mission: Optional[Dict[str, Any]],
) -> None:
    if is_same_mission_as_previous(new_mission_data, previous_mission):
        raise ValueError("직전 미션과 동일한 title 또는 동일한 타입/파라미터 조합은 허용되지 않습니다.")

def get_previous_mission_type(previous_mission: Optional[Dict[str, Any]]) -> str:
    if not previous_mission:
        return ""

    return str(
        previous_mission.get("mission_type")
        or previous_mission.get("suggested_type")
        or ""
    ).strip()


def get_preferred_regenerated_types(
    slot_code: str,
    previous_mission: Optional[Dict[str, Any]],
    attempt: int,
    max_attempts: int,
) -> List[str]:
    if not previous_mission:
        return []

    if attempt >= max_attempts:
        return []

    prev_type = get_previous_mission_type(previous_mission)

    if slot_code == "A":
        if prev_type == "A1_STEP_TARGET":
            return ["A2_ACTIVE_KCAL_TARGET"]
        if prev_type == "A2_ACTIVE_KCAL_TARGET":
            return ["A1_STEP_TARGET"]

    if slot_code == "B":
        if prev_type == "B1_TIMER_STRETCH":
            return ["B2_SLEEP_PREP", "B3_ROUTINE_CHECK"]
        if prev_type == "B2_SLEEP_PREP":
            return ["B1_TIMER_STRETCH", "B3_ROUTINE_CHECK"]
        if prev_type == "B3_ROUTINE_CHECK":
            return ["B1_TIMER_STRETCH", "B2_SLEEP_PREP"]

    return []


def validate_regeneration_type_rotation(
    *,
    slot_code: str,
    new_mission_data: Dict[str, Any],
    previous_mission: Optional[Dict[str, Any]],
    attempt: int,
    max_attempts: int,
) -> None:
    preferred_types = get_preferred_regenerated_types(
        slot_code=slot_code,
        previous_mission=previous_mission,
        attempt=attempt,
        max_attempts=max_attempts,
    )

    if not preferred_types:
        return

    new_type = str(new_mission_data.get("suggested_type") or "").strip()
    if new_type not in preferred_types:
        raise ValueError(
            f"{slot_code} 슬롯 재생성은 이번 시도에서 {preferred_types} 타입을 우선 생성해야 합니다."
        )


def build_retry_fallback_mission(
    slot_code: str,
    previous_mission_summary: Optional[Dict[str, Any]] = None,
    activity_summary: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    activity_summary = activity_summary or {}
    prev_type = get_previous_mission_type(previous_mission_summary)
    prev_params = (previous_mission_summary or {}).get("params") or {}
    preferred_type = get_behavior_preferred_type(
        slot_code,
        behavior_summary,
        exclude_types=[prev_type] if prev_type else None,
    )

    if slot_code == "A":
        avg_steps_7d = int(activity_summary.get("avg_steps_7d", 0) or 0)
        avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
        difficulty_bias = str(get_slot_behavior_summary(behavior_summary, "A").get("difficulty_bias") or "neutral")

        if avg_steps_7d <= 2000:
            step_candidates = [2500, 3000, 3500]
        elif avg_steps_7d <= 4000:
            step_candidates = [3500, 4000, 4500]
        elif avg_steps_7d <= 6000:
            step_candidates = [4500, 5000, 5500]
        elif avg_steps_7d <= 8000:
            step_candidates = [5500, 6000, 7000]
        else:
            step_candidates = [7000, 8000, 9000]

        if avg_active_kcal_7d <= 80:
            kcal_candidates = [80, 100, 120]
        elif avg_active_kcal_7d <= 140:
            kcal_candidates = [100, 120, 150]
        elif avg_active_kcal_7d <= 200:
            kcal_candidates = [150, 180, 220]
        elif avg_active_kcal_7d <= 280:
            kcal_candidates = [180, 220, 250]
        else:
            kcal_candidates = [220, 250, 300]

        step_candidates = shift_numeric_candidates_by_bias(step_candidates, STEP_TARGET_MASTER, difficulty_bias)
        kcal_candidates = shift_numeric_candidates_by_bias(kcal_candidates, KCAL_TARGET_MASTER, difficulty_bias)

        if prev_type == "A1_STEP_TARGET":
            prev_kcal = int(prev_params.get("target_kcal", 0) or 0)
            return build_active_kcal_mission_data(choose_candidate(kcal_candidates, prev_kcal or None))

        if prev_type == "A2_ACTIVE_KCAL_TARGET":
            prev_steps = int(prev_params.get("target_steps", 0) or 0)
            return build_step_target_mission_data(choose_candidate(step_candidates, prev_steps or None))

        if preferred_type == "A2_ACTIVE_KCAL_TARGET" or avg_active_kcal_7d <= 180:
            prev_kcal = int(prev_params.get("target_kcal", 0) or 0)
            return build_active_kcal_mission_data(choose_candidate(kcal_candidates, prev_kcal or None))

        prev_steps = int(prev_params.get("target_steps", 0) or 0)
        return build_step_target_mission_data(choose_candidate(step_candidates, prev_steps or None))

    if slot_code == "B":
        avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
        avg_sleep_minutes_7d = int(activity_summary.get("avg_sleep_minutes_7d", 0) or 0)
        difficulty_bias = str(get_slot_behavior_summary(behavior_summary, "B").get("difficulty_bias") or "neutral")

        stretch_candidates = [5, 10, 15] if avg_active_kcal_7d <= 150 else [10, 15, 20]
        stretch_candidates = shift_numeric_candidates_by_bias(stretch_candidates, STRETCH_DURATION_MASTER, difficulty_bias)

        if avg_sleep_minutes_7d and avg_sleep_minutes_7d < 360:
            sleep_candidates = [10, 15]
        elif avg_sleep_minutes_7d and avg_sleep_minutes_7d < 420:
            sleep_candidates = [15, 20]
        else:
            sleep_candidates = [15, 20, 25]
        sleep_candidates = shift_numeric_candidates_by_bias(sleep_candidates, SLEEP_PREP_DURATION_MASTER, difficulty_bias)

        if prev_type == "B2_SLEEP_PREP":
            prev_duration = int(prev_params.get("duration_min", 0) or 0)
            return build_stretch_mission_data(choose_candidate(stretch_candidates, prev_duration or None))

        if prev_type == "B1_TIMER_STRETCH":
            return build_b3_routine_fallback_mission(
                activity_summary,
                previous_mission_summary,
                behavior_summary,
            )

        if prev_type == "B3_ROUTINE_CHECK":
            prev_duration = int(prev_params.get("duration_min", 0) or 0)
            return build_sleep_prep_mission_data(choose_candidate(sleep_candidates, prev_duration or None))

        if preferred_type == "B3_ROUTINE_CHECK":
            return build_b3_routine_fallback_mission(
                activity_summary,
                previous_mission_summary,
                behavior_summary,
            )

        if preferred_type == "B1_TIMER_STRETCH":
            prev_duration = int(prev_params.get("duration_min", 0) or 0)
            return build_stretch_mission_data(choose_candidate(stretch_candidates, prev_duration or None))

        if avg_sleep_minutes_7d == 0:
            return build_b3_routine_fallback_mission(
                activity_summary,
                previous_mission_summary,
                behavior_summary,
            )

        prev_duration = int(prev_params.get("duration_min", 0) or 0)
        return build_sleep_prep_mission_data(choose_candidate(sleep_candidates, prev_duration or None))

    return build_c1_fallback_mission(previous_mission_summary, behavior_summary)

def attach_generation_meta(
    mission_data: Dict[str, Any],
    *,
    provider: str,
    attempt_count: int,
    phase: str,
    fallback_reason: Optional[str] = None,
    validation_reason: Optional[str] = None,
) -> Dict[str, Any]:
    copied = dict(mission_data)

    copied["_generation_meta"] = {
        "provider": provider,
        "attempt_count": attempt_count,
        "phase": phase,
        "fallback_reason": fallback_reason,
        "validation_reason": validation_reason,
    }

    return copied


def add_generation_log(
    db: Optional[Session],
    *,
    user_id: int,
    mode: str,
    slot_code: Optional[str],
    requested_count: int,
    phase: str,
    attempt_no: int,
    provider: str,
    outcome: str,
    mission_type: Optional[str] = None,
    validation_status: Optional[str] = None,
    validation_reason: Optional[str] = None,
    fallback_reason: Optional[str] = None,
    error_message: Optional[str] = None,
    raw_response_text: Optional[str] = None,
    input_summary: Optional[Dict[str, Any]] = None,
    output_mission: Optional[Dict[str, Any]] = None,
) -> None:
    if db is None:
        return

    db.add(
        MissionGenerationLog(
            user_id=user_id,
            mode=mode,
            slot_code=slot_code,
            requested_count=requested_count,
            phase=phase,
            attempt_no=attempt_no,
            provider=provider,
            outcome=outcome,
            mission_type=mission_type,
            validation_status=validation_status,
            validation_reason=validation_reason,
            fallback_reason=fallback_reason,
            error_message=error_message,
            raw_response_text=raw_response_text,
            input_summary_json=input_summary,
            output_mission_json=output_mission,
        )
    )



async def generate_single_slot_mission_with_fallback(
    *,
    mode: str,
    slot_code: str,
    user_profile: Dict[str, Any],
    activity_summary: Dict[str, Any],
    comparison: Dict[str, Any],
    public_average: Dict[str, Any],
    health_gap: Dict[str, Any],
    existing_missions_summary: List[Dict[str, Any]],
    previous_mission_summary: Optional[Dict[str, Any]],
    disallowed_types: set[str],
    behavior_summary: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    refresh / retry / complete_regen 공용 생성 함수

    1) GPT 생성 + 서버 검수
    2) GPT 성공이면 provider='gpt'
    3) GPT 실패/검수 실패가 반복되면 provider='server_fallback'
    """

    try:
        return await generate_unique_single_slot_mission(
            mode=mode,
            slot_code=slot_code,
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            existing_missions_summary=existing_missions_summary,
            previous_mission_summary=previous_mission_summary,
            disallowed_types=disallowed_types,
            max_attempts=3,
            behavior_summary=behavior_summary,
            db=db,
            user_id=user_id,
        )

    except Exception as e:
        raw_response_text = getattr(e, "raw_response_text", None)
        fallback_reason = f"GPT 생성/검수 3회 실패 후 서버 fallback 사용: {str(e)}"

        fallback_mission = build_retry_fallback_mission(
            slot_code=slot_code,
            previous_mission_summary=previous_mission_summary,
            activity_summary=activity_summary,
            behavior_summary=behavior_summary,
        )

        if user_id is not None:
            add_generation_log(
                db,
                user_id=user_id,
                mode=mode,
                slot_code=slot_code,
                requested_count=1,
                phase="fallback",
                attempt_no=0,
                provider="server_fallback",
                outcome="fallback_used",
                mission_type=fallback_mission.get("suggested_type"),
                validation_status="approved",
                fallback_reason=fallback_reason,
                error_message=str(e),
                raw_response_text=raw_response_text,
                input_summary={
                    "user_profile": user_profile,
                    "activity_summary": activity_summary,
                    "comparison": comparison,
                    "public_average": public_average,
                    "health_gap": health_gap,
                    "existing_missions": existing_missions_summary,
                    "previous_mission": previous_mission_summary,
                    "disallowed_types": list(disallowed_types),
                    "behavior_summary": behavior_summary,
                },
                output_mission=fallback_mission,
            )

        return attach_generation_meta(
            fallback_mission,
            provider="server_fallback",
            attempt_count=3,
            phase="fallback",
            fallback_reason=fallback_reason,
        )

async def generate_unique_single_slot_mission(
    *,
    mode: str,
    slot_code: str,
    user_profile: Dict[str, Any],
    activity_summary: Dict[str, Any],
    comparison: Dict[str, Any],
    public_average: Dict[str, Any],
    health_gap: Dict[str, Any],
    existing_missions_summary: List[Dict[str, Any]],
    previous_mission_summary: Optional[Dict[str, Any]],
    disallowed_types: set[str],
    max_attempts: int = 3,
    behavior_summary: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    GPT로 단일 슬롯 미션을 생성하고 서버 검수를 통과한 경우만 반환한다.
    실패한 GPT 원본 응답은 mission_generation_logs.raw_response_text에 저장한다.
    """

    last_error: Optional[Exception] = None

    input_summary = {
        "user_profile": user_profile,
        "activity_summary": activity_summary,
        "comparison": comparison,
        "public_average": public_average,
        "health_gap": health_gap,
        "existing_missions": existing_missions_summary,
        "previous_mission": previous_mission_summary,
        "disallowed_types": list(disallowed_types),
        "behavior_summary": behavior_summary,
    }

    for attempt in range(1, max_attempts + 1):
        try:
            missions = await GPTService.generate_structured_missions(
                mode=mode,
                mission_count=1,
                slot_codes=[slot_code],
                user_profile=user_profile,
                activity_summary=activity_summary,
                comparison=comparison,
                public_average=public_average,
                health_gap=health_gap,
                existing_missions=existing_missions_summary,
                previous_mission=previous_mission_summary,
                retry_attempt=attempt,
                behavior_summary=behavior_summary,
            )

            if len(missions) != 1:
                raise ValueError("GPT가 슬롯 재생성 미션 1개를 정확히 반환하지 않았습니다.")

            mission_data = normalize_generated_mission(missions[0])

            validate_single_slot_mission(mission_data, expected_slot_code=slot_code)
            validate_not_same_as_previous(mission_data, previous_mission_summary)

            validate_regeneration_type_rotation(
                slot_code=slot_code,
                new_mission_data=mission_data,
                previous_mission=previous_mission_summary,
                attempt=attempt,
                max_attempts=max_attempts,
            )

            if mission_data["suggested_type"] in disallowed_types:
                raise ValueError(
                    f"재생성 미션 타입이 다른 활성 미션과 중복되었습니다: {mission_data['suggested_type']}"
                )

            if user_id is not None:
                add_generation_log(
                    db,
                    user_id=user_id,
                    mode=mode,
                    slot_code=slot_code,
                    requested_count=1,
                    phase="strict",
                    attempt_no=attempt,
                    provider="gpt",
                    outcome="approved",
                    mission_type=mission_data.get("suggested_type"),
                    validation_status="approved",
                    input_summary=input_summary,
                    output_mission=mission_data,
                )

            return attach_generation_meta(
                mission_data,
                provider="gpt",
                attempt_count=attempt,
                phase="strict",
            )

        except Exception as e:
            last_error = e
            raw_response_text = getattr(e, "raw_response_text", None)

            if user_id is not None:
                add_generation_log(
                    db,
                    user_id=user_id,
                    mode=mode,
                    slot_code=slot_code,
                    requested_count=1,
                    phase="strict",
                    attempt_no=attempt,
                    provider="gpt",
                    outcome="rejected",
                    validation_status="rejected",
                    validation_reason=str(e),
                    error_message=str(e),
                    raw_response_text=raw_response_text,
                    input_summary=input_summary,
                    output_mission=None,
                )

    final_error = ValueError(
        f"동일하지 않은 새 미션 생성에 {max_attempts}회 실패했습니다: {str(last_error)}"
    )

    # 마지막 GPT 원본 응답을 fallback 로그까지 이어주기 위함
    setattr(
        final_error,
        "raw_response_text",
        getattr(last_error, "raw_response_text", None),
    )

    raise final_error


# ============================
# 미션 보상 계산 헬퍼
# ============================

REWARD_MIN_EXP = 10
REWARD_MAX_EXP = 30

REWARD_MIN_COINS = 20
REWARD_MAX_COINS = 50

C_TYPE_FIXED_REWARD = {
    "exp": 5,
    "coins": 5,
}


def clamp_number(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def normalize_range(value: float, min_value: float, max_value: float) -> float:
    """
    value가 min_value면 0.0,
    max_value면 1.0,
    그 사이는 0~1 사이 비율로 변환.
    """
    if max_value <= min_value:
        return 0.0

    value = clamp_number(value, min_value, max_value)
    return (value - min_value) / (max_value - min_value)


def scale_reward_by_ratio(ratio: float) -> Dict[str, int]:
    """
    ratio 0.0 = 가장 쉬움 = EXP 10 / 코인 20
    ratio 1.0 = 가장 어려움 = EXP 30 / 코인 50
    """
    ratio = clamp_number(ratio, 0.0, 1.0)

    exp = round(REWARD_MIN_EXP + (REWARD_MAX_EXP - REWARD_MIN_EXP) * ratio)
    coins = round(REWARD_MIN_COINS + (REWARD_MAX_COINS - REWARD_MIN_COINS) * ratio)

    return {
        "exp": int(exp),
        "coins": int(coins),
    }

def scale_a_reward_by_ratio(ratio: float) -> Dict[str, int]:
    """
    A 타입 전용 보상 계산.

    ratio 0.0 = 가장 쉬움 = EXP 30 / 코인 10
    ratio 1.0 = 가장 어려움 = EXP 50 / 코인 30
    """
    ratio = clamp_number(ratio, 0.0, 1.0)

    exp = round(30 + (50 - 30) * ratio)
    coins = round(10 + (30 - 10) * ratio)

    return {
        "exp": int(exp),
        "coins": int(coins),
    }

def scale_b3_reward_by_ratio(ratio: float) -> Dict[str, int]:
    """
    B3 루틴 체크 전용 보상 계산.

    B1/B2보다 EXP와 코인을 각각 10씩 더 지급한다.

    ratio 0.0 = 가장 쉬움 = EXP 20 / 코인 30
    ratio 1.0 = 가장 어려움 = EXP 40 / 코인 60
    """
    ratio = clamp_number(ratio, 0.0, 1.0)

    exp = round((REWARD_MIN_EXP + 10) + ((REWARD_MAX_EXP + 10) - (REWARD_MIN_EXP + 10)) * ratio)
    coins = round((REWARD_MIN_COINS + 10) + ((REWARD_MAX_COINS + 10) - (REWARD_MIN_COINS + 10)) * ratio)

    return {
        "exp": int(exp),
        "coins": int(coins),
    }

def get_mission_reward(
    *,
    mission_type: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """
    GPT가 생성한 mission_type + params 수치를 기준으로 보상을 계산한다.

    보상 규칙:
    - C1_HEALTH_CHECKIN은 항상 EXP 5 / 코인 5
    - 나머지 A/B 타입은 난이도 비율에 따라 EXP 10~30, 코인 20~50
    """

    params = params or {}

    # C 타입은 항상 고정 보상
    if mission_type == "C1_HEALTH_CHECKIN":
        return C_TYPE_FIXED_REWARD

    # A1: 걸음 수 목표
    # 2500보 = 쉬움, 9000보 = 어려움
    if mission_type == "A1_STEP_TARGET":
        target_steps = int(params.get("target_steps", 2500) or 2500)
        ratio = normalize_range(
            target_steps,
            min(STEP_TARGET_MASTER),
            max(STEP_TARGET_MASTER),
        )
        return scale_a_reward_by_ratio(ratio)

    # A2: 활동 칼로리 목표
    # 80kcal = 쉬움, 300kcal = 어려움
    if mission_type == "A2_ACTIVE_KCAL_TARGET":
        target_kcal = int(params.get("target_kcal", 80) or 80)
        ratio = normalize_range(
            target_kcal,
            min(KCAL_TARGET_MASTER),
            max(KCAL_TARGET_MASTER),
        )
        return scale_a_reward_by_ratio(ratio)

    # B1: 스트레칭 타이머
    # 5분 = 쉬움, 30분 = 어려움
    if mission_type == "B1_TIMER_STRETCH":
        duration_min = int(params.get("duration_min", 5) or 5)
        ratio = normalize_range(
            duration_min,
            min(STRETCH_DURATION_MASTER),
            max(STRETCH_DURATION_MASTER),
        )
        return scale_reward_by_ratio(ratio)

    # B2: 수면 준비 / 휴식 타이머
    # 10분 = 쉬움, 30분 = 어려움
    if mission_type == "B2_SLEEP_PREP":
        duration_min = int(params.get("duration_min", 10) or 10)
        ratio = normalize_range(
            duration_min,
            min(SLEEP_PREP_DURATION_MASTER),
            max(SLEEP_PREP_DURATION_MASTER),
        )
        return scale_reward_by_ratio(ratio)

    # B3: 루틴 체크
    # repeat_count가 높을수록 어렵고,
    # interval_min이 짧을수록 더 자주 체크해야 하므로 어렵게 계산
    if mission_type == "B3_ROUTINE_CHECK":
        repeat_count = int(params.get("repeat_count", 2) or 2)
        interval_min = int(params.get("interval_min", 15) or 15)

        repeat_ratio = normalize_range(repeat_count, 2, 5)

        # interval은 15분이 쉬움, 5분이 어려움
        interval_min = clamp_number(interval_min, 5, 15)
        interval_ratio = normalize_range(15 - interval_min, 0, 10)

        # 루틴은 반복 횟수가 더 중요하다고 보고 70%, 간격은 30%
        ratio = (repeat_ratio * 0.7) + (interval_ratio * 0.3)

        return scale_b3_reward_by_ratio(ratio)

    # 혹시 알 수 없는 타입이면 안전하게 가장 쉬운 보상
    return {
        "exp": REWARD_MIN_EXP,
        "coins": REWARD_MIN_COINS,
    }


def get_slot_reward(slot_code: str) -> Dict[str, int]:
    """
    구버전 호환용 fallback.
    새 미션 생성에서는 get_mission_reward()를 사용한다.
    """
    return {
        "exp": REWARD_MIN_EXP,
        "coins": REWARD_MIN_COINS,
    }


def consume_refresh_cost(
    profile: UserGameProfile,
    use_mission_coin_if_needed: bool = True,
) -> Dict[str, Any]:
    """
    무료 재생성 우선 사용
    무료 0이면 미션 코인 사용
    둘 다 없으면 실패 정보 반환
    """
    if profile.daily_free_regen_remaining is None:
        profile.daily_free_regen_remaining = 3

    if profile.mission_coins is None:
        profile.mission_coins = 0

    # 무료 재생성 우선 차감
    if profile.daily_free_regen_remaining > 0:
        profile.daily_free_regen_remaining -= 1
        if profile.daily_free_regen_remaining < 0:
            profile.daily_free_regen_remaining = 0

        return {
            "ok": True,
            "cost_type": "free_regen",
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    # 무료가 없고, 코인 사용 허용이면 코인 차감
    if use_mission_coin_if_needed and profile.mission_coins > 0:
        profile.mission_coins -= 1
        if profile.mission_coins < 0:
            profile.mission_coins = 0

        return {
            "ok": True,
            "cost_type": "mission_coin",
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    return {
        "ok": False,
        "reason": "MISSION_COIN_REQUIRED",
        "daily_free_regen_remaining": profile.daily_free_regen_remaining,
        "mission_coins": profile.mission_coins,
    }

def refund_refresh_cost(
    profile: UserGameProfile,
    cost_type: Optional[str],
) -> None:
    """
    GPT 생성 실패 등으로 재생성이 실제 완료되지 못했을 때
    직전에 차감한 무료 재생성 / 미션 쿠폰을 복구한다.
    """
    if profile.daily_free_regen_remaining is None:
        profile.daily_free_regen_remaining = 3

    if profile.mission_coins is None:
        profile.mission_coins = 0

    if cost_type == "free_regen":
        profile.daily_free_regen_remaining += 1
        if profile.daily_free_regen_remaining > 3:
            profile.daily_free_regen_remaining = 3

    elif cost_type == "mission_coin":
        profile.mission_coins += 1


def mark_slot_mission_refreshed(target_mission: UserMission) -> None:
    target_mission.status = "refreshed"
    target_mission.is_refreshed = True


def create_mission_row(
    *,
    user_id: int,
    mission_data: Dict[str, Any],
    generation_source: str,
    latest_activity: Optional[UserActivity] = None,
    comparison: Optional[Dict[str, Any]] = None,
    activity_summary: Optional[Dict[str, Any]] = None,
    public_average: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> UserMission:
    mission_data = apply_a_type_minimum_label(mission_data)

    slot_code = mission_data["slot_code"]
    mission_type = mission_data["suggested_type"]

    reward_info = get_mission_reward(
        mission_type=mission_type,
        params=mission_data.get("params") or {},
    )

    progress_json = {}
    reason = sanitize_mission_reason(
        raw_reason=mission_data.get("reason"),
        mission_type=mission_type,
        params=mission_data.get("params") or {},
        comparison=comparison,
        activity_summary=activity_summary,
        public_average=public_average,
        behavior_summary=behavior_summary,
    )
    today_str = datetime.utcnow().date().isoformat()

    if mission_type == "A1_STEP_TARGET":
        current_steps = latest_activity.steps if latest_activity and latest_activity.steps else 0
        progress_json = {
            "baseline_steps": current_steps,
            "current_steps": current_steps,
            "delta_steps": 0,
            "tracking_date": today_str,
        }

    elif mission_type == "A2_ACTIVE_KCAL_TARGET":
        current_kcal = int(latest_activity.calories) if latest_activity and latest_activity.calories else 0
        progress_json = {
            "baseline_kcal": current_kcal,
            "current_kcal": current_kcal,
            "delta_kcal": 0,
            "tracking_date": today_str,
        }

    generation_meta = mission_data.get("_generation_meta") or {}

    return UserMission(
        user_id=user_id,
        title=mission_data["title"],
        content=mission_data["description"],
        reason=reason,
        category="AI_MISSION",
        difficulty="normal",
        is_completed=False,
        is_refreshed=False,
        slot_code=slot_code,
        mission_type=mission_type,
        status="active",
        params_json=mission_data["params"],
        progress_json=progress_json,
        reward_exp=reward_info["exp"],
        reward_coins=reward_info["coins"],
        generation_source=generation_source,
        validation_status="approved",
        validation_reason=None,
        generation_provider=generation_meta.get("provider", "unknown"),
        generation_attempt_count=int(generation_meta.get("attempt_count") or 0),
        fallback_reason=generation_meta.get("fallback_reason"),
        generation_meta_json=generation_meta or None,
    )

def evaluate_mission_completion(
    mission: UserMission,
    latest_activity: Optional[UserActivity],
    client_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    실패 상태는 없고,
    조건을 만족하면 success=True,
    아니면 success=False만 반환
    """
    mission_type = mission.mission_type
    params = mission.params_json or {}

    if mission_type == "A1_STEP_TARGET":
        target_steps = params.get("target_steps", 0)
        current_steps = latest_activity.steps if latest_activity and latest_activity.steps else 0

        progress_json = mission.progress_json or {}
        baseline_steps = int(progress_json.get("baseline_steps", 0) or 0)
        tracking_date = str(progress_json.get("tracking_date", "") or "")

        from datetime import datetime
        today_str = datetime.utcnow().date().isoformat()

        if tracking_date != today_str:
            baseline_steps = current_steps

        delta_steps = max(current_steps - baseline_steps, 0)

        return {
            "success": delta_steps >= target_steps,
            "progress": {
                "baseline_steps": baseline_steps,
                "current_steps": current_steps,
                "delta_steps": delta_steps,
                "target_steps": target_steps,
                "tracking_date": today_str,
            },
            "message": f"{delta_steps}/{target_steps}보",
        }

    elif mission_type == "A2_ACTIVE_KCAL_TARGET":
        target_kcal = params.get("target_kcal", 0)
        current_kcal = int(latest_activity.calories) if latest_activity and latest_activity.calories else 0

        progress_json = mission.progress_json or {}
        baseline_kcal = int(progress_json.get("baseline_kcal", 0) or 0)
        tracking_date = str(progress_json.get("tracking_date", "") or "")

        from datetime import datetime
        today_str = datetime.utcnow().date().isoformat()

        if tracking_date != today_str:
            baseline_kcal = current_kcal

        delta_kcal = max(current_kcal - baseline_kcal, 0)

        return {
            "success": delta_kcal >= target_kcal,
            "progress": {
                "baseline_kcal": baseline_kcal,
                "current_kcal": current_kcal,
                "delta_kcal": delta_kcal,
                "target_kcal": target_kcal,
                "tracking_date": today_str,
            },
            "message": f"{delta_kcal}/{target_kcal}kcal",
        }

    elif mission_type == "B1_TIMER_STRETCH":
        timer_completed = bool(
            client_payload.get("timer_completed", client_payload.get("interaction_completed", False))
        )
        duration_min = params.get("duration_min", 0)

        return {
            "success": timer_completed,
            "progress": {
                "timer_completed": timer_completed,
                "duration_min": duration_min,
            },
            "message": "스트레칭 타이머 완료 여부 확인",
        }

    elif mission_type == "B2_SLEEP_PREP":
        timer_completed = bool(
            client_payload.get("timer_completed", client_payload.get("interaction_completed", False))
        )
        duration_min = params.get("duration_min", 0)

        return {
            "success": timer_completed,
            "progress": {
                "timer_completed": timer_completed,
                "duration_min": duration_min,
            },
            "message": "휴식 타이머 완료 여부 확인",
        }

    elif mission_type == "B3_ROUTINE_CHECK":
        repeat_count = params.get("repeat_count", 0)
        checked_count = int(client_payload.get("checked_count", 0))
        routine_completed = bool(
            client_payload.get("routine_completed", client_payload.get("interaction_completed", False))
        )

        success = routine_completed or checked_count >= repeat_count

        return {
            "success": success,
            "progress": {
                "checked_count": checked_count,
                "repeat_count": repeat_count,
                "routine_completed": routine_completed,
            },
            "message": f"{checked_count}/{repeat_count}회",
        }

    elif mission_type == "C1_HEALTH_CHECKIN":
        min_length = params.get("min_length", 15)
        checkin_text = str(client_payload.get("checkin_text", "") or "").strip()
        success = len(checkin_text) >= min_length

        return {
            "success": success,
            "progress": {
                "checkin_text": checkin_text,
                "text_length": len(checkin_text),
                "min_length": min_length,
            },
            "message": f"체크인 글자 수 {len(checkin_text)}/{min_length}",
        }

    return {
        "success": False,
        "progress": {},
        "message": "지원하지 않는 mission_type 입니다.",
    }


def apply_mission_reward(db: Session, profile: UserGameProfile, mission: UserMission) -> None:
    if profile.current_exp is None:
        profile.current_exp = 0
    if profile.total_exp is None:
        profile.total_exp = 0
    if profile.coins is None:
        profile.coins = 0
    if profile.level is None or profile.level < 1:
        profile.level = 1

    owned_char = db.query(UserOwnedCharacter).filter(
        UserOwnedCharacter.user_game_profile_id == profile.id,
        UserOwnedCharacter.character_id == profile.selected_character_id
    ).first()

    if owned_char:
        if owned_char.level is None or owned_char.level < 1: #레벨 방어 로직 추가
            owned_char.level = 1
        if owned_char.current_exp is None:
            owned_char.current_exp = 0
        
        # 개별 캐릭터 경험치 추가
        owned_char.current_exp += mission.reward_exp or 0
        
        # 전역 프로필 수치 동기화 (피드백 권장 사항)
        profile.current_exp = owned_char.current_exp
        profile.level = owned_char.level
    else:
        # 장착 캐릭터가 없는 예외 케이스 처리 (fallback)
        profile.current_exp += mission.reward_exp or 0

    profile.total_exp += mission.reward_exp or 0
    profile.coins += mission.reward_coins or 0

    if profile.total_missions_completed is None:
        profile.total_missions_completed = 0
    if profile.total_coins_earned is None:
        profile.total_coins_earned = 0
    if profile.total_purchases is None:
        profile.total_purchases = 0

    profile.total_missions_completed += 1
    profile.total_coins_earned += mission.reward_coins or 0


def build_mission_response(mission: UserMission) -> Dict[str, Any]:
    return {
        "id": mission.id,
        "slot_code": mission.slot_code,
        "mission_type": mission.mission_type,
        "title": mission.title,
        "description": mission.content,
        "status": mission.status,
        "params": mission.params_json or {},
        "progress": mission.progress_json or {},
        "reward_exp": mission.reward_exp,
        "reward_coins": mission.reward_coins,
        "reason": mission.reason,
        "category": mission.category,
        "difficulty": mission.difficulty,
        "is_completed": mission.is_completed,
        "is_refreshed": mission.is_refreshed,
        "generation_source": mission.generation_source,
        "validation_status": mission.validation_status,
        "validation_reason": mission.validation_reason,
        "generation_provider": mission.generation_provider,
        "generation_attempt_count": mission.generation_attempt_count,
        "fallback_reason": mission.fallback_reason,
        "generation_meta": mission.generation_meta_json,
    }


# ============================
# 1. 데이터 동기화 및 관리
# ============================

@router.post("/sync-healthcare", response_model=HealthcareResponse, status_code=status.HTTP_201_CREATED)
async def sync_healthcare_data(
    data: HealthcareSyncRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """헬스케어 플랫폼 데이터 동기화 및 자동 분석"""

    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="유저 없음")

    analysis_input = {
        "age": data.age,
        "gender": data.gender,
        "height": data.height or 170.0,
        "weight": data.weight,
        "body_fat": data.body_fat,
        "muscle_mass": data.muscle_mass or 0.0,
        "bmr": 1600.0,
    }
    analysis = HealthAnalyzer.get_comparison(db, analysis_input)

    db.query(UserInbody).filter(UserInbody.user_id == current_user_id).delete()

    new_inbody = UserInbody(
        user_id=current_user_id,
        name=user.nickname,
        age=data.age,
        gender=data.gender,
        height=data.height or 170.0,
        weight=data.weight,
        body_fat=data.body_fat,
        muscle_mass=data.muscle_mass or 0.0,
        bmi=analysis["bmi_value"],
        bmr=1600.0,
    )
    db.add(new_inbody)

    new_activity = UserActivity(
        user_id=current_user_id,
        steps=data.steps,
        calories=data.calories,
        source=data.source,
        heart_rate=None,
        sleep_minutes=None,
    )
    db.add(new_activity)

    # 구버전/신버전 임시 호환: 텍스트 기반 자동 완료 체크
    active_missions = db.query(UserMission).filter(
        UserMission.user_id == current_user_id,
        UserMission.is_completed == False
    ).all()

    for mission in active_missions:
        numbers = re.findall(r"\d+", mission.content or "")
        if not numbers:
            continue

        target_value = int(numbers[0])

        if mission.category == "활동" or "걸음" in (mission.content or ""):
            if (data.steps or 0) >= target_value:
                mission.is_completed = True
                mission.status = "completed"

        elif "칼로리" in (mission.content or ""):
            if (data.calories or 0.0) >= target_value:
                mission.is_completed = True
                mission.status = "completed"

    db.commit()

    return {
        "bmi": analysis["bmi_value"],
        "muscle_ratio": analysis["muscle_ratio"],
        "bmi_result": analysis["bmi_result"],
        "fat_status": analysis["interpretation"]["fat"],
        "muscle_status": analysis["interpretation"]["muscle"],
        "status_message": f"동기화 완료: {analysis['summary']}",
    }


# ============================
# 2. 현재 미션 조회
# ============================

@router.get("/current", response_model=list[CurrentMissionResponse])
async def get_current_missions(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    현재 사용자에게 보여줄 '현재 슬롯 미션'만 조회
    - active / in_progress 상태만 조회
    - 슬롯별(A/B/C) 가장 최신 1개만 반환
    """
    missions = (
        db.query(UserMission)
        .filter(UserMission.user_id == current_user_id)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .order_by(UserMission.created_at.desc(), UserMission.id.desc())
        .all()
    )

    if not missions:
        return []

    latest_by_slot: Dict[str, UserMission] = {}
    for mission in missions:
        slot = (mission.slot_code or "").strip().upper()
        if slot in ["A", "B", "C"] and slot not in latest_by_slot:
            latest_by_slot[slot] = mission

    ordered_slots = ["A", "B", "C"]
    current_missions = [latest_by_slot[slot] for slot in ordered_slots if slot in latest_by_slot]

    return [build_mission_response(m) for m in current_missions]


# ============================
# 3. 기타 미션 관리 기능
# ============================

@router.get("/check-data", response_model=UserCheckResponse)
def check_user_data(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    유저 건강 데이터 존재 여부 확인
    """
    user_record = db.query(UserInbody).filter(UserInbody.user_id == current_user_id).first()

    if not user_record:
        return {"exists": False, "data": None, "message": "데이터가 없습니다."}

    return {"exists": True, "data": user_record, "message": "데이터 조회 성공."}


@router.post("/admin/seed-standards")
async def seed_standards(db: Session = Depends(get_db)):
    """
    표준 데이터 적재
    """
    count = await DataSeeder.seed_health_standards(db)
    return {"message": f"{count}개의 표준 데이터 적재 완료"}


# ============================
# 4. 신버전 슬롯 기반 미션 시스템
# ============================

@router.post("/generate-initial")
async def generate_initial_missions(
    req: GenerateInitialMissionsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    최초 AI 미션 3개 생성
    - 게임 프로필 없으면 여기서 최초 생성
    - A/B/C 슬롯 각각 1개씩 생성
    - 이미 active 미션이 있으면 중복 생성 방지
    """

    # 1) 헬스 데이터 확인
    latest_inbody = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )

    if not latest_inbody:
        raise HTTPException(
            status_code=400,
            detail="인바디 데이터가 없습니다. 삼성 헬스 연동 후 다시 시도해주세요."
        )

    latest_activity = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.recorded_at.desc())
        .first()
    )

    # 2) 기존 active / in_progress 미션 체크
    existing_active_missions = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .all()
    )

    if existing_active_missions and not req.force_regenerate:
        raise HTTPException(
            status_code=400,
            detail="이미 생성된 AI 미션이 있습니다."
        )

    # 강제 재생성이면 기존 활성 미션 상태 변경
    if req.force_regenerate:
        for mission in existing_active_missions:
            mission.status = "refreshed"
            mission.is_refreshed = True
            db.add(mission)
        db.flush()

    # 3) 게임 프로필 생성
    profile = ensure_game_profile(db, user.id)
    if profile.daily_free_regen_remaining is None:
        profile.daily_free_regen_remaining = 3
    if profile.daily_free_regen_remaining > 3:
        profile.daily_free_regen_remaining = 3
    if profile.mission_coins is None:
        profile.mission_coins = 0

    # 4) GPT 입력 데이터 준비
    user_profile = build_user_profile_summary(latest_inbody, user)
    recent_activities = get_recent_activity_records(db, user.id, days=7)
    activity_summary = build_activity_summary(latest_activity, recent_activities)

    public_average = await get_public_average_summary(db, latest_inbody, user)
    health_gap = build_health_gap_summary(latest_inbody, latest_activity, public_average)
    comparison = build_comparison_summary(latest_inbody, latest_activity, public_average)
    behavior_summary = build_behavior_adaptation_summary(db, user.id)

    # 5) GPT 호출 + 초기 타입 편향 보정
    missions: Optional[List[Dict[str, Any]]] = None
    last_generation_error: Optional[Exception] = None

    for attempt in range(1, 5):
        try:
            generated_missions = await GPTService.generate_structured_missions(
                mode="initial",
                mission_count=3,
                slot_codes=["A", "B", "C"],
                user_profile=user_profile,
                activity_summary=activity_summary,
                comparison=comparison,
                public_average=public_average,
                health_gap=health_gap,
                existing_missions=[],
                retry_attempt=attempt,
                behavior_summary=behavior_summary,
            )

            if not isinstance(generated_missions, list):
                raise ValueError("GPT 초기 미션 응답이 리스트 형식이 아닙니다.")

            generated_missions = [
                normalize_generated_mission(m)
                for m in generated_missions
                if isinstance(m, dict)
            ]

            validate_initial_missions(generated_missions)

            original_missions_by_slot = {
                m["slot_code"]: dict(m)
                for m in generated_missions
                if m.get("slot_code") in ["A", "B", "C"]
            }

            # GPT가 너무 기본 조합으로 치우친 경우에만 서버에서 보정
            generated_missions = rebalance_initial_missions(
                generated_missions,
                activity_summary,
                behavior_summary,
            )

            validate_initial_missions(generated_missions)
            validate_initial_type_balance(generated_missions, activity_summary)

            generated_missions_with_meta: List[Dict[str, Any]] = []

            for mission in generated_missions:
                slot_code = mission.get("slot_code")
                original_mission = original_missions_by_slot.get(slot_code)

                rebalance_changed = (
                    original_mission is None
                    or json.dumps(original_mission, ensure_ascii=False, sort_keys=True)
                    != json.dumps(mission, ensure_ascii=False, sort_keys=True)
                )

                provider = "server_rebalance" if rebalance_changed else "gpt"
                outcome = "rebalance_used" if rebalance_changed else "approved"
                fallback_reason = "initial_type_bias_rebalance" if rebalance_changed else None

                mission_with_meta = attach_generation_meta(
                    mission,
                    provider=provider,
                    attempt_count=attempt,
                    phase="initial",
                    fallback_reason=fallback_reason,
                )

                add_generation_log(
                    db,
                    user_id=user.id,
                    mode="initial",
                    slot_code=slot_code,
                    requested_count=3,
                    phase="initial",
                    attempt_no=attempt,
                    provider=provider,
                    outcome=outcome,
                    mission_type=mission_with_meta.get("suggested_type"),
                    validation_status="approved",
                    fallback_reason=fallback_reason,
                    input_summary={
                        "user_profile": user_profile,
                        "activity_summary": activity_summary,
                        "comparison": comparison,
                        "public_average": public_average,
                        "health_gap": health_gap,
                        "behavior_summary": behavior_summary,
                        "original_gpt_mission": original_mission,
                    },
                    output_mission=mission_with_meta,
                )

                generated_missions_with_meta.append(mission_with_meta)

            missions = generated_missions_with_meta
            break

        except Exception as e:
            last_generation_error = e
            raw_response_text = getattr(e, "raw_response_text", None)

            add_generation_log(
                db,
                user_id=user.id,
                mode="initial",
                slot_code=None,
                requested_count=3,
                phase="initial",
                attempt_no=attempt,
                provider="gpt",
                outcome="rejected",
                validation_status="rejected",
                validation_reason=str(e),
                error_message=str(e),
                raw_response_text=raw_response_text,
                input_summary={
                    "user_profile": user_profile,
                    "activity_summary": activity_summary,
                    "comparison": comparison,
                    "public_average": public_average,
                    "health_gap": health_gap,
                    "behavior_summary": behavior_summary,
                },
                output_mission=None,
            )

    if not missions:
        raise HTTPException(
            status_code=500,
            detail=f"GPT 미션 생성 또는 초기 타입 균형 검수 실패: {str(last_generation_error)}"
        )
    
    # 7) DB 저장
    created_missions: List[UserMission] = []

    for mission in missions:
        new_mission = create_mission_row(
            user_id=user.id,
            mission_data=mission,
            generation_source="initial",
            latest_activity=latest_activity,
            comparison=comparison,
            activity_summary=activity_summary,
            public_average=public_average,
            behavior_summary=behavior_summary,
        )
        db.add(new_mission)
        created_missions.append(new_mission)

    db.commit()
    refresh_behavior_profile_snapshot(db, user.id)
    db.commit()

    for mission in created_missions:
        db.refresh(mission)

    return {
        "ok": True,
        "message": "초기 AI 미션 3개가 생성되었습니다.",
        "game_initialized": True,
        "profile_id": profile.id,
        "missions": [build_mission_response(mission) for mission in created_missions],
    }

@router.post("/start-slot")
async def start_slot_mission(
    req: StartSlotRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    특정 슬롯 미션을 진행중(in_progress) 상태로 변경
    - active -> in_progress 전환
    - 이미 in_progress면 그대로 반환
    - 다른 슬롯이 이미 in_progress면 중복 진행 방지
    """
    slot_code = (req.slot_code or "").strip().upper()
    if slot_code not in ["A", "B", "C"]:
        raise HTTPException(
            status_code=400,
            detail="slot_code는 A, B, C 중 하나여야 합니다."
        )

    current_in_progress = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.status == "in_progress")
        .order_by(UserMission.created_at.desc(), UserMission.id.desc())
        .first()
    )

    if current_in_progress and current_in_progress.slot_code != slot_code:
        raise HTTPException(
            status_code=400,
            detail="이미 다른 슬롯의 미션이 진행중입니다."
        )

    target_mission = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.slot_code == slot_code)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .order_by(UserMission.created_at.desc(), UserMission.id.desc())
        .first()
    )

    if not target_mission:
        raise HTTPException(
            status_code=404,
            detail=f"{slot_code} 슬롯의 활성 미션을 찾을 수 없습니다."
        )

    if target_mission.status == "in_progress":
        return {
            "ok": True,
            "message": f"{slot_code} 슬롯 미션이 이미 진행중입니다.",
            "slot_code": slot_code,
            "mission": build_mission_response(target_mission),
        }

    target_mission.status = "in_progress"
    if not target_mission.started_at:
        from datetime import datetime
        target_mission.started_at = datetime.utcnow()

    db.add(target_mission)
    db.commit()
    db.refresh(target_mission)

    return {
        "ok": True,
        "message": f"{slot_code} 슬롯 미션이 진행중으로 시작되었습니다.",
        "slot_code": slot_code,
        "mission": build_mission_response(target_mission),
    }


@router.post("/refresh-slot")
async def refresh_slot_mission(
    req: RefreshSlotRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    특정 슬롯(A/B/C) 미션 1개 재생성
    - 무료 재생성 우선 차감
    - 무료가 0이면 mission coin 사용
    - 둘 다 없으면 결제 유도 응답 반환
    """

    slot_code = (req.slot_code or "").strip().upper()
    if slot_code not in ["A", "B", "C"]:
        raise HTTPException(
            status_code=400,
            detail="slot_code는 A, B, C 중 하나여야 합니다."
        )

    # 1) 헬스 데이터 확인
    latest_inbody = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )

    if not latest_inbody:
        raise HTTPException(
            status_code=400,
            detail="인바디 데이터가 없습니다. 삼성 헬스 연동 후 다시 시도해주세요."
        )

    latest_activity = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.recorded_at.desc())
        .first()
    )

    # 2) 게임 프로필 확인
    profile = ensure_game_profile(db, user.id)

    # 날짜 리셋은 game/profile에서 처리하고 있지만,
    # 안전하게 여기서도 3 초과 보정만 해둠
    if profile.daily_free_regen_remaining is None:
        profile.daily_free_regen_remaining = 3
    if profile.daily_free_regen_remaining > 3:
        profile.daily_free_regen_remaining = 3
    if profile.mission_coins is None:
        profile.mission_coins = 0

    # 3) 현재 슬롯의 active/in_progress 미션 찾기
    target_mission = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.slot_code == slot_code)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .order_by(UserMission.created_at.desc(), UserMission.id.desc())
        .first()
    )

    if not target_mission:
        raise HTTPException(
            status_code=404,
            detail=f"{slot_code} 슬롯의 활성 미션을 찾을 수 없습니다."
        )

    # 4) 재생성 비용 차감
    cost_result = consume_refresh_cost(
        profile=profile,
        use_mission_coin_if_needed=req.use_mission_coin_if_needed,
    )

    if not cost_result["ok"]:
        db.add(profile)
        db.commit()
        db.refresh(profile)

        return {
            "ok": False,
            "reason": "MISSION_COIN_REQUIRED",
            "message": "무료 재생성을 모두 사용했습니다. 미션 쿠폰이 필요합니다.",
            "slot_code": slot_code,
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    # 5) 기존 활성 미션 요약 준비
    existing_active_missions = get_existing_active_missions(db, user.id)

    other_active_missions = [
        m for m in existing_active_missions
        if m.id != target_mission.id
    ]

    existing_missions_summary = build_existing_mission_summary(other_active_missions)
    previous_mission_summary = build_previous_mission_summary(target_mission)

    # 같은 타입 중복 방지용
    disallowed_types = {m.mission_type for m in other_active_missions if m.mission_type}

    # 6) GPT 입력 데이터 준비
    user_profile = build_user_profile_summary(latest_inbody, user)
    recent_activities = get_recent_activity_records(db, user.id, days=7)
    activity_summary = build_activity_summary(latest_activity, recent_activities)

    public_average = await get_public_average_summary(db, latest_inbody, user)
    health_gap = build_health_gap_summary(latest_inbody, latest_activity, public_average)
    comparison = build_comparison_summary(latest_inbody, latest_activity, public_average)
    behavior_summary = build_behavior_adaptation_summary(db, user.id)

    # 7) GPT 호출 + 3회 자동 재시도 + 직전 미션 동일성 차단
    try:
        new_mission_data = await generate_single_slot_mission_with_fallback(
            mode="refresh",
            slot_code=slot_code,
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            existing_missions_summary=existing_missions_summary,
            previous_mission_summary=previous_mission_summary,
            disallowed_types=disallowed_types,
            behavior_summary=behavior_summary,
            db=db,
            user_id=user.id,
        )
    except Exception as e:
        refund_refresh_cost(profile, cost_result.get("cost_type"))
        db.add(profile)
        db.commit()
        db.refresh(profile)

        return {
            "ok": False,
            "reason": "REFRESH_GENERATION_FAILED",
            "message": "미션 재생성에 실패했습니다. 사용한 무료 재생성 또는 미션 쿠폰은 복구되었습니다. 다시 시도해주세요.",
            "slot_code": slot_code,
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }
    

    # 9) 기존 미션 refreshed 처리
    mark_slot_mission_refreshed(target_mission)
    db.add(target_mission)

    # 10) 새 미션 저장
    new_mission = create_mission_row(
        user_id=user.id,
        mission_data=new_mission_data,
        generation_source="refresh",
        latest_activity=latest_activity,
        comparison=comparison,
        activity_summary=activity_summary,
        public_average=public_average,
        behavior_summary=behavior_summary,
    )
    db.add(profile)
    db.add(new_mission)

    db.commit()
    refresh_behavior_profile_snapshot(db, user.id)
    db.commit()
    db.refresh(profile)
    db.refresh(new_mission)

    return {
        "ok": True,
        "message": f"{slot_code} 슬롯 미션이 재생성되었습니다.",
        "slot_code": slot_code,
        "cost_type": cost_result["cost_type"],  # free_regen / mission_coin
        "daily_free_regen_remaining": profile.daily_free_regen_remaining,
        "mission_coins": profile.mission_coins,
        "previous_mission_id": target_mission.id,
        "mission": build_mission_response(new_mission)
    }

@router.post("/retry-slot")
async def retry_slot_mission(
    req: RetrySlotRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    특정 슬롯에 현재 active/in_progress 미션이 없을 때
    같은 슬롯 미션을 다시 생성하는 전용 API
    - 비용 차감 없음
    - complete 후 next_mission 생성 실패한 슬롯 복구용
    - MissionsView의 빈 슬롯 fallback 카드에서 사용
    """

    slot_code = (req.slot_code or "").strip().upper()
    if slot_code not in ["A", "B", "C"]:
        raise HTTPException(
            status_code=400,
            detail="slot_code는 A, B, C 중 하나여야 합니다."
        )

    # 0) 게임 프로필 먼저 확보
    profile = ensure_game_profile(db, user.id)
    
    # 1) 현재 슬롯에 이미 active / in_progress 미션이 있으면 재시도 불가
    existing_slot_mission = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.slot_code == slot_code)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .order_by(UserMission.created_at.desc(), UserMission.id.desc())
        .first()
    )


    if existing_slot_mission:
        return {
            "ok": True,
            "message": f"{slot_code} 슬롯에는 이미 활성 미션이 있어 최신 상태를 유지합니다.",
            "slot_code": slot_code,
            "cost_type": None,
            "daily_free_regen_remaining": profile.daily_free_regen_remaining if profile.daily_free_regen_remaining is not None else 3,
            "mission_coins": profile.mission_coins if profile.mission_coins is not None else 0,
            "mission": build_mission_response(existing_slot_mission),
        }

    # 2) 헬스 데이터 확인
    latest_inbody = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )

    if not latest_inbody:
        raise HTTPException(
            status_code=400,
            detail="인바디 데이터가 없습니다. 삼성 헬스 연동 후 다시 시도해주세요."
        )

    latest_activity = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.recorded_at.desc())
        .first()
    )

    # 3) 게임 프로필 확보
    profile = ensure_game_profile(db, user.id)

    # 4) 다른 활성 미션들 요약
    other_active_missions = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .filter(UserMission.slot_code != slot_code)
        .all()
    )

    existing_missions_summary = build_existing_mission_summary(other_active_missions)
    disallowed_types = {m.mission_type for m in other_active_missions if m.mission_type}

    previous_same_slot_mission = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.slot_code == slot_code)
        .order_by(UserMission.created_at.desc(), UserMission.id.desc())
        .first()
    )
    previous_mission_summary = build_previous_mission_summary(previous_same_slot_mission)

    # 4-1) 빈 슬롯 재생성 비용 차감
    # 종료 UI에서 미션 쿠폰 사용 시 여기로 들어온다.
    cost_result = consume_refresh_cost(
        profile=profile,
        use_mission_coin_if_needed=req.use_mission_coin_if_needed,
    )

    if not cost_result["ok"]:
        db.add(profile)
        db.commit()
        db.refresh(profile)

        return {
            "ok": False,
            "reason": "MISSION_COIN_REQUIRED",
            "message": "무료 재생성을 모두 사용했습니다. 미션 쿠폰이 필요합니다.",
            "slot_code": slot_code,
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    # 5) GPT 입력 데이터 준비
    user_profile = build_user_profile_summary(latest_inbody, user)
    recent_activities = get_recent_activity_records(db, user.id, days=7)
    activity_summary = build_activity_summary(latest_activity, recent_activities)

    public_average = await get_public_average_summary(db, latest_inbody, user)
    health_gap = build_health_gap_summary(latest_inbody, latest_activity, public_average)
    comparison = build_comparison_summary(latest_inbody, latest_activity, public_average)
    behavior_summary = build_behavior_adaptation_summary(db, user.id)

    # 6) GPT 호출 + 3회 자동 재시도 + 직전 미션 동일성 차단 / # 7) 검수
    try:
        next_mission_data = await generate_single_slot_mission_with_fallback(
            mode="retry",
            slot_code=slot_code,
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            existing_missions_summary=existing_missions_summary,
            previous_mission_summary=previous_mission_summary,
            disallowed_types=disallowed_types,
            behavior_summary=behavior_summary,
            db=db,
            user_id=user.id,
        )
    except Exception as e:
        # ✅ 차감 복구
        refund_refresh_cost(profile, cost_result.get("cost_type"))
        db.add(profile)
        db.commit()
        db.refresh(profile)

        return {
            "ok": False,
            "reason": "RETRY_GENERATION_FAILED",
            "message": "새 미션 생성에 실패했습니다. 사용한 무료 재생성 또는 미션 쿠폰은 복구되었습니다. 다시 시도해주세요.",
            "slot_code": slot_code,
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    # 8) 저장
    new_mission = create_mission_row(
        user_id=user.id,
        mission_data=next_mission_data,
        generation_source="retry",
        latest_activity=latest_activity,
        comparison=comparison,
        activity_summary=activity_summary,
        public_average=public_average,
        behavior_summary=behavior_summary,
    )
    db.add(new_mission)
    db.commit()
    refresh_behavior_profile_snapshot(db, user.id)
    db.commit()
    db.refresh(new_mission)

    return {
        "ok": True,
        "message": f"{slot_code} 슬롯 미션이 다시 생성되었습니다.",
        "slot_code": slot_code,
        "cost_type": cost_result["cost_type"],
        "daily_free_regen_remaining": profile.daily_free_regen_remaining,
        "mission_coins": profile.mission_coins,
        "mission": build_mission_response(new_mission),
    }





@router.post("/complete-slot")
async def complete_slot_mission(
    req: CompleteSlotRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    특정 슬롯 미션 완료 처리
    - 실패 상태는 없음
    - 조건 만족 시 completed 처리 + 보상 지급 + 같은 슬롯 새 미션 자동 생성
    - 조건 미충족이면 그대로 유지
    """

    slot_code = (req.slot_code or "").strip().upper()
    if slot_code not in ["A", "B", "C"]:
        raise HTTPException(
            status_code=400,
            detail="slot_code는 A, B, C 중 하나여야 합니다."
        )


    # 1) 현재 슬롯 활성 미션 찾기
    target_mission = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.slot_code == slot_code)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .order_by(UserMission.created_at.desc(), UserMission.id.desc())
        .first()
    )

    if not target_mission:
        raise HTTPException(
            status_code=404,
            detail=f"{slot_code} 슬롯의 활성 미션을 찾을 수 없습니다."
        )

    # 2) 게임 프로필 확인
    profile = ensure_game_profile(db, user.id)

    # 3) 최신 활동 데이터 조회
    latest_activity = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.recorded_at.desc())
        .first()
    )

    # 4) 완료 판정
    evaluation = evaluate_mission_completion(
        mission=target_mission,
        latest_activity=latest_activity,
        client_payload=req.client_payload or {},
    )

    # 진행도는 항상 업데이트
    target_mission.progress_json = evaluation["progress"]
    db.add(target_mission)

    # 5) 아직 완료 조건 미충족이면 종료
    if not evaluation["success"]:
        db.commit()
        db.refresh(target_mission)

        return {
            "ok": True,
            "completed": False,
            "message": "아직 완료 조건이 충족되지 않았습니다.",
            "slot_code": slot_code,
            "mission": build_mission_response(target_mission),
            "evaluation": evaluation,
        }

    # 6) 완료 처리 + 보상 지급
    target_mission.status = "completed"
    target_mission.is_completed = True
    target_mission.progress_json = evaluation["progress"]

    apply_mission_reward(db, profile, target_mission)
    new_achievements = evaluate_and_grant_achievements(db, profile)

    db.add(profile)
    db.add(target_mission)

    # 6-1) 성공 처리만: 보상만 지급하고 다음 미션은 생성하지 않음
    # 무료 재생성 횟수와 미션 쿠폰도 차감하지 않음
    if req.regenerate_after_complete is False:
        db.commit()
        db.refresh(profile)
        db.refresh(target_mission)

        return {
            "ok": True,
            "completed": True,
            "message": "미션 완료 및 보상 지급이 완료되었습니다. 다음 미션은 생성되지 않았습니다.",
            "slot_code": slot_code,
            "profile": {
                "level": profile.level,
                "current_exp": profile.current_exp,
                "total_exp": profile.total_exp,
                "coins": profile.coins,
                "mission_coins": profile.mission_coins,
                "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            },
            "completed_mission": build_mission_response(target_mission),
            "next_mission": None,
            "next_mission_skipped": True,
            "evaluation": evaluation,
            "new_achievements": new_achievements,
            "cost_type": "complete_only",
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    # 6-2) 완료 후 다음 미션 자동 생성 비용 차감
    # 새로고침과 동일하게 무료 재생성 우선, 없으면 미션 쿠폰 사용
    cost_result = consume_refresh_cost(
        profile=profile,
        use_mission_coin_if_needed=True,
    )

    if not cost_result["ok"]:
        db.commit()
        db.refresh(profile)
        db.refresh(target_mission)

        return {
            "ok": True,
            "completed": True,
            "message": "미션 완료 및 보상 지급이 완료되었습니다. 무료 재생성이 없어 다음 미션은 생성되지 않았습니다.",
            "slot_code": slot_code,
            "profile": {
                "level": profile.level,
                "current_exp": profile.current_exp,
                "total_exp": profile.total_exp,
                "coins": profile.coins,
                "mission_coins": profile.mission_coins,
                "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            },
            "completed_mission": build_mission_response(target_mission),
            "next_mission": None,
            "evaluation": evaluation,
            "new_achievements": new_achievements,
            "cost_type": None,
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    # 7) 같은 슬롯 새 미션 자동 생성 준비
    latest_inbody = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )

    if not latest_inbody:
        # 이 경우는 거의 없지만, 있어도 완료/보상은 유지
        db.commit()
        db.refresh(profile)
        db.refresh(target_mission)

        return {
            "ok": True,
            "completed": True,
            "message": "미션 완료 및 보상 지급이 완료되었습니다. 새 미션은 생성하지 못했습니다.",
            "slot_code": slot_code,
            "profile": {
                "level": profile.level,
                "current_exp": profile.current_exp,
                "total_exp": profile.total_exp,
                "coins": profile.coins,
                "mission_coins": profile.mission_coins,
                "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            },
            "completed_mission": build_mission_response(target_mission),
            "next_mission": None,
            "evaluation": evaluation,
            "new_achievements": new_achievements,
            "cost_type": cost_result["cost_type"],
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    other_active_missions = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .filter(UserMission.status.in_(["active", "in_progress"]))
        .filter(UserMission.slot_code != slot_code)
        .all()
    )

    existing_missions_summary = build_existing_mission_summary(other_active_missions)
    disallowed_types = {m.mission_type for m in other_active_missions if m.mission_type}
    previous_mission_summary = build_previous_mission_summary(target_mission)

    user_profile = build_user_profile_summary(latest_inbody, user)
    recent_activities = get_recent_activity_records(db, user.id, days=7)
    activity_summary = build_activity_summary(latest_activity, recent_activities)

    public_average = await get_public_average_summary(db, latest_inbody, user)
    health_gap = build_health_gap_summary(latest_inbody, latest_activity, public_average)
    comparison = build_comparison_summary(latest_inbody, latest_activity, public_average)
    behavior_summary = build_behavior_adaptation_summary(db, user.id)

    # 8) GPT로 같은 슬롯 새 미션 생성 + 3회 자동 재시도 + 직전 미션 동일성 차단
    try:
        next_mission_data = await generate_single_slot_mission_with_fallback(
            mode="complete_regen",
            slot_code=slot_code,
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            existing_missions_summary=existing_missions_summary,
            previous_mission_summary=previous_mission_summary,
            disallowed_types=disallowed_types,
            behavior_summary=behavior_summary,
            db=db,
            user_id=user.id,
        )
    except Exception as e:
        db.commit()
        db.refresh(profile)
        db.refresh(target_mission)

        return {
            "ok": True,
            "completed": True,
            "message": f"미션 완료 및 보상 지급은 성공했지만 새 미션 생성은 실패했습니다: {str(e)}",
            "slot_code": slot_code,
            "profile": {
                "level": profile.level,
                "current_exp": profile.current_exp,
                "total_exp": profile.total_exp,
                "coins": profile.coins,
                "mission_coins": profile.mission_coins,
                "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            },
            "completed_mission": build_mission_response(target_mission),
            "next_mission": None,
            "evaluation": evaluation,
            "new_achievements": new_achievements,
            "cost_type": cost_result["cost_type"],
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
            "mission_coins": profile.mission_coins,
        }

    # 9) 새 미션 저장
    next_mission = create_mission_row(
        user_id=user.id,
        mission_data=next_mission_data,
        generation_source="complete_regen",
        latest_activity=latest_activity,
        comparison=comparison,
        activity_summary=activity_summary,
        public_average=public_average,
        behavior_summary=behavior_summary,
    )
    db.add(next_mission)

    db.commit()
    refresh_behavior_profile_snapshot(db, user.id)
    db.commit()
    db.refresh(profile)
    db.refresh(target_mission)
    db.refresh(next_mission)

    return {
        "ok": True,
        "completed": True,
        "message": "미션 완료, 보상 지급, 다음 미션 생성이 완료되었습니다.",
        "slot_code": slot_code,
        "profile": {
            "level": profile.level,
            "current_exp": profile.current_exp,
            "total_exp": profile.total_exp,
            "coins": profile.coins,
            "mission_coins": profile.mission_coins,
            "daily_free_regen_remaining": profile.daily_free_regen_remaining,
        },
        "completed_mission": build_mission_response(target_mission),
        "next_mission": build_mission_response(next_mission),
        "evaluation": evaluation,
        "new_achievements": new_achievements,
        "cost_type": cost_result["cost_type"],
        "daily_free_regen_remaining": profile.daily_free_regen_remaining,
        "mission_coins": profile.mission_coins,
    }


# ============================
# 🔴 구버전 미션 시스템 (미사용)
# - mission_id 기반 방식
# - 앞으로는 슬롯 기반 시스템으로 교체
# - 아래 API들은 참고용으로만 남기고 실제 사용하지 않음
# ============================

# @router.post("/generate-smart-missions")
# async def generate_smart_missions(
#     db: Session = Depends(get_db),
#     current_user_id: int = Depends(get_current_user_id)
# ):
#     """[구버전] 최초로 3개의 미션을 동시 생성합니다."""
#     existing_count = db.query(UserMission).filter(UserMission.user_id == current_user_id).count()
#     if existing_count > 0:
#         raise HTTPException(status_code=400, detail="이미 미션이 존재합니다. 재생성 기능을 이용하세요.")
#
#     user_record = db.query(UserInbody).filter(UserInbody.user_id == current_user_id).first()
#     if not user_record:
#         raise HTTPException(status_code=400, detail="데이터 동기화가 먼저 필요합니다.")
#
#     avg_data = await PublicHealthService.get_average_metrics(user_record.age, user_record.gender)
#     comparison_info = {
#         "weight_gap": round(user_record.weight - avg_data.get("avg_weight", 60), 1),
#         "fat_gap": round(user_record.body_fat - avg_data.get("avg_body_fat", 25), 1),
#         "public_prescription": avg_data.get("prescription", "꾸준한 운동"),
#     }
#
#     analysis = HealthAnalyzer.get_comparison(db, {
#         "age": user_record.age,
#         "gender": user_record.gender,
#         "height": user_record.height,
#         "weight": user_record.weight,
#         "body_fat": user_record.body_fat,
#         "muscle_mass": user_record.muscle_mass,
#         "bmr": user_record.bmr or 1600.0,
#     })
#
#     ai_response_list = await GPTService.generate_mission(
#         user_data=analysis,
#         comparison_data=comparison_info,
#         count=3,
#         existing_missions=[]
#     )
#
#     created_missions = []
#     for m in ai_response_list:
#         new_mission = UserMission(
#             user_id=current_user_id,
#             title=m.get("mission_title"),
#             content=m.get("content"),
#             reason=m.get("reason"),
#             category=m.get("category"),
#             difficulty=m.get("difficulty", "중"),
#             is_completed=False
#         )
#         db.add(new_mission)
#         created_missions.append(new_mission)
#
#     db.commit()
#     return {"status": "success", "count": len(created_missions), "missions": ai_response_list}


# @router.patch("/refresh/{mission_id}")
# async def refresh_single_mission(
#     mission_id: int,
#     db: Session = Depends(get_db),
#     current_user_id: int = Depends(get_current_user_id)
# ):
#     """[구버전] 기존 미션을 영구 삭제하고, 남은 미션과 중복되지 않는 1개를 새로 생성합니다."""
#     target = db.query(UserMission).filter(
#         UserMission.id == mission_id,
#         UserMission.user_id == current_user_id
#     ).first()
#     if not target:
#         raise HTTPException(status_code=404, detail="재생성할 미션을 찾을 수 없습니다.")
#
#     remaining_missions = db.query(UserMission).filter(
#         UserMission.user_id == current_user_id,
#         UserMission.id != mission_id
#     ).all()
#     existing_list = [{"title": m.title, "category": m.category} for m in remaining_missions]
#
#     db.delete(target)
#     db.commit()
#
#     user_record = db.query(UserInbody).filter(UserInbody.user_id == current_user_id).first()
#     avg_data = await PublicHealthService.get_average_metrics(user_record.age, user_record.gender)
#     comparison_info = {
#         "weight_gap": 0.0,
#         "fat_gap": 0.0,
#         "public_prescription": "건강 유지"
#     }
#
#     analysis = HealthAnalyzer.get_comparison(db, {
#         "age": user_record.age,
#         "gender": user_record.gender,
#         "height": user_record.height,
#         "weight": user_record.weight,
#         "body_fat": user_record.body_fat,
#         "muscle_mass": user_record.muscle_mass,
#         "bmr": user_record.bmr or 1600.0
#     })
#
#     new_ai_data = await GPTService.generate_mission(
#         user_data=analysis,
#         comparison_data=comparison_info,
#         count=1,
#         existing_missions=existing_list
#     )
#
#     m = new_ai_data[0] if isinstance(new_ai_data, list) else new_ai_data
#
#     new_mission = UserMission(
#         user_id=current_user_id,
#         title=m.get("mission_title"),
#         content=m.get("content"),
#         reason=m.get("reason"),
#         category=m.get("category"),
#         difficulty=m.get("difficulty", "중"),
#         is_completed=False
#     )
#     db.add(new_mission)
#     db.commit()
#     db.refresh(new_mission)
#
#     return {"status": "success", "new_mission": m}


# @router.post("/claim-reward")
# async def claim_reward(
#     db: Session = Depends(get_db),
#     current_user_id: int = Depends(get_current_user_id)
# ):
#     """[구버전] 3개 미션 완료 확인 후 보상을 지급합니다."""
#     incomplete_missions = db.query(UserMission).filter(
#         UserMission.user_id == current_user_id,
#         UserMission.is_completed == False
#     ).count()
#
#     if incomplete_missions > 0:
#         raise HTTPException(status_code=400, detail="모든 미션을 완료해야 보상을 수령할 수 있습니다.")
#
#     user = db.query(User).filter(User.id == current_user_id).first()
#     user.exp += 100
#     db.commit()
#
#     db.query(UserMission).filter(UserMission.user_id == current_user_id).delete()
#     db.commit()
#
#     return {"message": "보상이 성공적으로 지급되었습니다. 이제 재생성 버튼을 통해 새로운 미션을 시작하세요."}


# @router.patch("/complete/{mission_id}")
# def complete_mission(
#     mission_id: int,
#     db: Session = Depends(get_db)
# ):
#     """[구버전] 특정 미션의 수행 상태를 완료(True)로 변경합니다."""
#     mission = db.query(UserMission).filter(UserMission.id == mission_id).first()
#     if not mission:
#         raise HTTPException(status_code=404, detail="미션 없음")
#
#     mission.is_completed = True
#     db.commit()
#
#     return {"message": "미션 완료!"}