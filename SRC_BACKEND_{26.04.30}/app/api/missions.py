# app/api/missions.py

import asyncio
import re
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import StreamingResponse
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
    MISSION_GPT_EXPERIMENT_VARIANT,
    MISSION_GPT_PROMPT_VERSION,
    SYSTEM_PROMPT_ENABLED,
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
    MISSION_EVENT_COMPLETED,
    MISSION_EVENT_REFRESHED,
    MISSION_EVENT_STARTED,
    build_pending_event_history_item,
    get_behavior_summary_with_pending_event,
    get_effective_behavior_summary,
    log_mission_event,
    upsert_user_behavior_profile,
)
from app.services.mission_policy.health_gap_analyzer import (
    build_health_gap_summary as build_policy_health_gap_summary,
)
from app.services.mission_policy.routine_catalog import (
    ALLOWED_INTERVAL_MINUTES,
    ALLOWED_REPEAT_COUNTS,
    ROUTINE_CATALOG_VERSION,
    build_routine_mission_payload,
    build_routine_candidates,
    get_allowed_routine_keys,
    get_allowed_routine_names,
    get_routine_by_key,
    get_routine_by_name,
    is_allowed_routine_name_for_key,
    normalize_routine_key,
    normalize_routine_params,
)
from app.services.mission_policy.checkin_catalog import (
    CHECKIN_CATALOG_VERSION,
    ALLOWED_CHECKIN_MIN_LENGTHS,
    build_checkin_mission_payload,
    build_checkin_candidates,
    get_allowed_checkin_keys,
    get_allowed_checkin_labels,
    get_checkin_by_key,
    is_allowed_checkin_label_for_key,
    normalize_checkin_params,
)
from app.services.mission_policy.numeric_target_policy import build_a_selected_target_policy
from app.services.mission_policy.mission_contract import (
    MISSION_OUTPUT_CONTRACT_VERSION,
    REQUIRED_MISSION_KEYS,
    REQUIRED_B3_PARAM_KEYS,
    REQUIRED_C1_PARAM_KEYS,
    TARGET_VALUE_CONSTRAINTS,
)
from app.services.data_seeder import DataSeeder
from app.models.standard import HealthStandard
from app.services.kosis_api import KosisHealthStatsService
from app.services.activity_summary_service import (
    build_activity_summary_from_records,
    get_activity_records_for_range,
    get_current_kst_week_range,
)
from app.api.game import ensure_game_profile
from app.api.auth import get_current_user_id
from app.models.game import UserGameProfile
from pydantic import BaseModel, Field
from app.services.achievement_service import evaluate_and_grant_achievements
from app.models.game import UserOwnedCharacter

router = APIRouter(prefix="/missions", tags=["Missions"])

MissionProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


async def emit_generation_progress(
    progress: Optional[MissionProgressCallback],
    *,
    stage: str,
    label: str,
    detail: str,
    progress_percent: int,
    step_index: int,
    total_steps: int,
    status_value: str = "running",
    generation_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """미션 생성 파이프라인의 실제 서버 처리 지점을 SSE 이벤트로 전달한다."""
    if progress is None:
        return

    payload = {
        "generation_id": generation_id,
        "status": status_value,
        "stage": stage,
        "label": label,
        "detail": detail,
        "progress": max(0, min(100, int(progress_percent))),
        "step_index": step_index,
        "total_steps": total_steps,
    }
    if meta:
        payload["meta"] = meta
    await progress(payload)


def format_sse_event(event_name: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


INITIAL_GENERATION_TOTAL_STEPS = 10
REFRESH_SLOT_TOTAL_STEPS = 8



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
    params = {"target_steps": target_steps}
    return {
        "slot_code": "A",
        "title": f"{target_steps}보 걷기에 도전해보세요",
        "description": f"지금부터 {target_steps}보를 더 걸어보세요.",
        "mission_type": "A1_STEP_TARGET",
        "suggested_type": "A1_STEP_TARGET",
        "params": params,
        "reason": generate_reason_fallback(
            mission_type="A1_STEP_TARGET",
            params=params,
        ),
    }


def build_active_kcal_mission_data(target_kcal: int) -> Dict[str, Any]:
    params = {"target_kcal": target_kcal}
    return {
        "slot_code": "A",
        "title": f"활동칼로리 {target_kcal}kcal 달성에 도전해보세요",
        "description": f"지금부터 {target_kcal}kcal를 더 쌓아보세요.",
        "mission_type": "A2_ACTIVE_KCAL_TARGET",
        "suggested_type": "A2_ACTIVE_KCAL_TARGET",
        "params": params,
        "reason": generate_reason_fallback(
            mission_type="A2_ACTIVE_KCAL_TARGET",
            params=params,
        ),
    }


def build_stretch_mission_data(duration_min: int) -> Dict[str, Any]:
    params = {"duration_min": duration_min}
    return {
        "slot_code": "B",
        "title": f"스트레칭 {duration_min}분을 완료해보세요",
        "description": f"가볍게 {duration_min}분 동안 몸을 풀어보세요.",
        "mission_type": "B1_TIMER_STRETCH",
        "suggested_type": "B1_TIMER_STRETCH",
        "params": params,
        "reason": generate_reason_fallback(
            mission_type="B1_TIMER_STRETCH",
            params=params,
        ),
    }


def build_sleep_prep_mission_data(duration_min: int) -> Dict[str, Any]:
    params = {"duration_min": duration_min}
    return {
        "slot_code": "B",
        "title": f"편안한 휴식을 위한 {duration_min}분 루틴을 진행해보세요",
        "description": f"부담 없는 {duration_min}분 휴식 루틴으로 몸과 마음을 정리해보세요.",
        "mission_type": "B2_SLEEP_PREP",
        "suggested_type": "B2_SLEEP_PREP",
        "params": params,
        "reason": generate_reason_fallback(
            mission_type="B2_SLEEP_PREP",
            params=params,
        ),
    }


def build_routine_check_mission_data(
    routine_name: str,
    repeat_count: int,
    interval_min: int,
    routine_key: Optional[str] = None,
) -> Dict[str, Any]:
    """B3 루틴 체크 미션 데이터 생성.

    기존 호출부 호환을 위해 routine_name 인자를 유지하되,
    실제 params는 routine_catalog 기준으로 routine_key까지 포함해 표준화한다.
    """

    params = normalize_routine_params(
        {
            "routine_key": routine_key or normalize_routine_key(routine_name),
            "routine_name": routine_name,
            "repeat_count": repeat_count,
            "interval_min": interval_min,
        }
    )
    routine = get_routine_by_key(params["routine_key"])

    if routine:
        title = routine["title_template"].format(**params)
        description = routine["description_template"].format(**params)
    else:
        title = f"{params['routine_name']} 루틴 {params['repeat_count']}회 체크해보세요"
        description = f"{params['interval_min']}분마다 {params['routine_name']} 루틴을 체크해보세요."

    return {
        "slot_code": "B",
        "title": title,
        "description": description,
        "mission_type": "B3_ROUTINE_CHECK",
        "suggested_type": "B3_ROUTINE_CHECK",
        "params": params,
        "reason": generate_reason_fallback(
            mission_type="B3_ROUTINE_CHECK",
            params=params,
        ),
    }


def build_checkin_mission_data(
    title: str,
    description_template: str,
    min_length: int,
    checkin_key: str = "condition_today",
) -> Dict[str, Any]:
    """C1 fallback/호환용 미션 payload 생성.

    기존 호출부 호환을 유지하되 params는 checkin_catalog 기준으로
    checkin_key/checkin_label까지 포함한 표준 구조로 저장한다.
    """

    params = normalize_checkin_params({"checkin_key": checkin_key, "min_length": min_length})
    return {
        "slot_code": "C",
        "title": title,
        "description": description_template.format(min_length=params["min_length"]),
        "mission_type": "C1_HEALTH_CHECKIN",
        "suggested_type": "C1_HEALTH_CHECKIN",
        "params": params,
        "reason": generate_reason_fallback(
            mission_type="C1_HEALTH_CHECKIN",
            params=params,
        ),
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




def mentions_unavailable_sleep_data(reason: Optional[str]) -> bool:
    """앱이 실제 수면 데이터를 수집하지 않는 상황에서 부자연스러운 수면 데이터 부족 표현을 감지한다."""
    normalized = normalize_reason_text(reason)
    if not normalized:
        return False

    sleep_terms = ["수면 데이터", "수면 기록", "수면 측정", "수면 정보"]
    shortage_terms = ["부족", "없", "적", "누락"]
    return any(term in normalized for term in sleep_terms) and any(term in normalized for term in shortage_terms)


def has_sleep_activity_data(activity_summary: Optional[Dict[str, Any]]) -> bool:
    activity_summary = activity_summary or {}
    try:
        latest = int(activity_summary.get("sleep_minutes_latest", 0) or 0)
        avg = int(activity_summary.get("avg_sleep_minutes_7d", 0) or 0)
    except (TypeError, ValueError):
        return False
    return latest > 0 or avg > 0

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
        "C1_HEALTH_CHECKIN": ["기록", "컨디션", "상태", "패턴", "수면", "기분", "에너지", "활동", "회고", "몸"],
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

    params = params or {}
    b3_params = normalize_routine_params(params) if mission_type == "B3_ROUTINE_CHECK" else {}
    c1_params = normalize_checkin_params(params) if mission_type == "C1_HEALTH_CHECKIN" else {}

    target_steps = int(params.get("target_steps", 0) or 0)
    target_kcal = int(params.get("target_kcal", 0) or 0)
    duration_min = int(params.get("duration_min", 0) or 0)

    templates = {
        "A1_STEP_TARGET": (
            f"{prefix} {target_steps}보 목표로 부담 없이 걸음 루틴을 이어갈 수 있도록 추천했어요."
            if target_steps
            else f"{prefix} 부담 없이 시작할 수 있는 걸음 미션으로 추천했어요."
        ),
        "A2_ACTIVE_KCAL_TARGET": (
            f"{prefix} {target_kcal}kcal 활동 목표로 가볍게 움직일 수 있게 구성했어요."
            if target_kcal
            else f"{prefix} 가볍게 움직이며 실천할 수 있는 활동 미션으로 구성했어요."
        ),
        "B1_TIMER_STRETCH": (
            f"{prefix} {duration_min}분 스트레칭 루틴으로 몸을 풀며 이어가기 좋게 추천했어요."
            if duration_min
            else f"{prefix} 가볍게 실천할 수 있는 스트레칭 루틴으로 추천했어요."
        ),
        "B2_SLEEP_PREP": (
            f"{prefix} {duration_min}분 휴식 루틴으로 몸과 마음을 정리하기 쉽게 조정했어요."
            if duration_min
            else f"{prefix} 꾸준히 이어가기 쉬운 휴식 루틴으로 조정했어요."
        ),
        "B3_ROUTINE_CHECK": (
            f"{prefix} {b3_params.get('routine_name', '생활')} 루틴을 "
            f"{b3_params.get('repeat_count', 3)}회 체크하며 습관으로 이어가기 좋게 구성했어요."
        ),
        "C1_HEALTH_CHECKIN": (
            f"{prefix} {c1_params.get('checkin_label', '컨디션')} 주제로 현재 상태를 "
            f"{c1_params.get('min_length', 15)}자 이상 기록하며 건강 패턴을 돌아볼 수 있도록 추천했어요."
        ),
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
        or (
            mission_type in {"B1_TIMER_STRETCH", "B2_SLEEP_PREP", "B3_ROUTINE_CHECK"}
            and not has_sleep_activity_data(activity_summary)
            and mentions_unavailable_sleep_data(reason)
        )
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


def ensure_mission_reason_for_validation(
    mission: Dict[str, Any],
    *,
    comparison: Optional[Dict[str, Any]] = None,
    activity_summary: Optional[Dict[str, Any]] = None,
    public_average: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    GPT가 reason을 누락하거나 너무 일반적으로 작성했을 때 서버가 검수 가능한 reason을 합성한다.

    목적:
    - System Prompt 자연어 지시를 GPT가 일부 놓쳐도 전체 미션 생성을 실패시키지 않는다.
    - 서버 구조화 데이터(params/type/activity_summary)를 기준으로 사용자 표시용 추천 이유를 보강한다.
    - 원본 GPT 응답은 mission_generation_logs.raw_response_text에 남고, DB 저장 전 payload만 안전하게 정규화한다.
    """

    copied = dict(mission or {})
    mission_type = str(
        copied.get("suggested_type")
        or copied.get("mission_type")
        or ""
    ).strip()
    params = copied.get("params") or {}
    original_reason = normalize_reason_text(copied.get("reason"))

    copied["reason"] = sanitize_mission_reason(
        raw_reason=original_reason,
        mission_type=mission_type,
        params=params,
        comparison=comparison,
        activity_summary=activity_summary,
        public_average=public_average,
        behavior_summary=behavior_summary,
    )

    if copied["reason"] != original_reason:
        copied["server_reason_synthesized"] = True
        copied["server_reason_synthesized_reason"] = "missing_or_invalid_gpt_reason"

    return copied


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
    """
    AI 미션과 활동 히스토리의 평균 계산 기준을 통일한다.

    기존에는 UTC rolling 7일 + 조회된 record 개수 평균이었고,
    HistoryPage는 KST 월~일 7일 고정 평균이었다.
    이제 미션 생성도 HistoryPage 기본 화면과 같은 KST 월~일 범위를 사용한다.
    """
    start_date, end_date = get_current_kst_week_range()
    return get_activity_records_for_range(db, user_id, start_date, end_date)



def build_activity_summary(
    activity: Optional[UserActivity],
    recent_activities: Optional[List[UserActivity]] = None,
) -> Dict[str, Any]:
    """Build the exact same summary shape/rule used by /healthcare/history."""
    start_date, end_date = get_current_kst_week_range()
    return build_activity_summary_from_records(recent_activities or [], start_date, end_date)


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
    activity_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    GPT에게 전달할 건강 격차 요약.

    1차 고도화부터 실제 계산은 app.services.mission_policy.health_gap_analyzer로 분리한다.
    이 wrapper는 기존 missions.py 호출부와의 호환성을 위한 얇은 연결 함수다.
    """
    return build_policy_health_gap_summary(
        inbody=inbody,
        activity=activity,
        public_average=public_average,
        activity_summary=activity_summary,
    )

def build_comparison_summary(
    inbody: UserInbody,
    activity: Optional[UserActivity],
    public_average: Optional[Dict[str, Any]] = None,
    activity_summary: Optional[Dict[str, Any]] = None,
    health_gap: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    미션 생성용 간단 비교 요약.

    1차 보정부터 comparison도 health_gap/activity_summary 기준으로 맞춘다.
    - step_status/activity_status는 최신 하루값이 아니라 이번 주 7일 평균 기반 health_gap 값을 우선 사용한다.
    - weight_status는 한국 성인 BMI 기준 health_gap 값을 우선 사용한다.
    - public_average는 정상/위험 판정 기준이 아니라 참고 평균값으로만 둔다.
    """

    activity_summary = activity_summary or {}
    public_average = public_average or {}

    if health_gap is None:
        health_gap = build_health_gap_summary(
            inbody=inbody,
            activity=activity,
            public_average=public_average,
            activity_summary=activity_summary,
        )

    latest_steps = int(getattr(activity, "steps", 0) or 0) if activity else 0
    latest_kcal = int(getattr(activity, "calories", 0) or 0) if activity else 0

    return {
        "step_status": health_gap.get("step_status", "below_average"),
        "activity_status": health_gap.get("activity_status", "low"),
        "weight_status": health_gap.get("weight_status", get_weight_status_by_bmi(inbody.bmi)),
        "bmi_status": health_gap.get("bmi_status", "unknown"),
        "bmi_category_detail": health_gap.get("bmi_category_detail", "unknown"),
        "bmi_label_ko": health_gap.get("bmi_label_ko"),
        "goal_type": health_gap.get("goal_type"),
        "goal_label": health_gap.get("goal_label"),
        "data_confidence": health_gap.get("data_confidence"),
        "today_steps": int(activity_summary.get("today_steps", latest_steps) or 0),
        "today_active_kcal": int(activity_summary.get("today_active_kcal", latest_kcal) or 0),
        "avg_steps_7d": int(health_gap.get("avg_steps_7d", activity_summary.get("avg_steps_7d", 0)) or 0),
        "avg_active_kcal_7d": int(
            health_gap.get("avg_active_kcal_7d", activity_summary.get("avg_active_kcal_7d", 0)) or 0
        ),
        "weight_status_basis": health_gap.get("bmi_basis", "korean_adult_bmi_18.5_22.9"),
        "activity_status_basis": health_gap.get("activity_status_basis"),
        "activity_status_is_official_guideline": health_gap.get(
            "activity_status_is_official_guideline", False
        ),
        "public_average_is_reference_only": health_gap.get("public_average_is_reference_only", True),
    }

def infer_slot_code_from_type(suggested_type: Optional[str]) -> Optional[str]:
    suggested_type = str(suggested_type or "").strip()
    if not suggested_type:
        return None

    for slot_code, allowed_types in ALLOWED_TYPES_BY_SLOT.items():
        if suggested_type in allowed_types:
            return slot_code

    return None


def normalize_generated_b3_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """GPT가 낸 B3 params를 카탈로그 기준으로 보강한다.

    5차 계약부터는 GPT가 낸 repeat_count / interval_min을 조용히 보정하지 않는다.
    routine_key 또는 routine_name이 카탈로그에 매칭될 때 프론트 연결용 필드만 채우고,
    숫자 후보값 검수는 validate_params_by_type에서 엄격하게 처리한다.
    """

    params = dict(params or {})
    routine_key = normalize_routine_key(params.get("routine_key"))
    routine_from_name = get_routine_by_name(params.get("routine_name"))

    if not routine_key and routine_from_name:
        routine_key = str(routine_from_name["routine_key"])

    routine = get_routine_by_key(routine_key) if routine_key else None
    if not routine:
        return params

    return {
        "routine_key": routine["routine_key"],
        "routine_name": routine["routine_name"],
        "routine_label": routine["routine_label"],
        "routine_category": routine["routine_category"],
        "icon_key": routine["icon_key"],
        "action_label": routine["action_label"],
        "repeat_count": params.get("repeat_count"),
        "interval_min": params.get("interval_min"),
        "catalog_version": params.get("catalog_version") or ROUTINE_CATALOG_VERSION,
    }


def normalize_generated_mission(mission: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(mission or {})

    raw_suggested_type = str(normalized.get("suggested_type") or "").strip()
    raw_mission_type = str(normalized.get("mission_type") or "").strip()

    if raw_suggested_type and raw_mission_type and raw_suggested_type != raw_mission_type:
        normalized["_contract_error"] = (
            f"mission_type과 suggested_type이 일치하지 않습니다: "
            f"mission_type={raw_mission_type}, suggested_type={raw_suggested_type}"
        )
    elif raw_mission_type and not raw_suggested_type:
        normalized["suggested_type"] = raw_mission_type
    elif raw_suggested_type and not raw_mission_type:
        normalized["mission_type"] = raw_suggested_type

    slot_code = normalized.get("slot_code")
    suggested_type = normalized.get("suggested_type") or normalized.get("mission_type")

    if slot_code is None or str(slot_code).strip() == "":
        inferred = infer_slot_code_from_type(suggested_type)
        if inferred:
            normalized["slot_code"] = inferred

    if str(normalized.get("suggested_type") or "").strip() == "B3_ROUTINE_CHECK":
        normalized["params"] = normalize_generated_b3_params(normalized.get("params") or {})

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
    if mission.get("_contract_error"):
        raise ValueError(str(mission["_contract_error"]))

    for key in REQUIRED_MISSION_KEYS:
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

    if not isinstance(mission["mission_type"], str) or not mission["mission_type"].strip():
        raise ValueError("mission_type은 비어 있지 않은 문자열이어야 합니다.")

    if not isinstance(mission["suggested_type"], str) or not mission["suggested_type"].strip():
        raise ValueError("suggested_type은 비어 있지 않은 문자열이어야 합니다.")

    if str(mission["mission_type"]).strip() != str(mission["suggested_type"]).strip():
        raise ValueError("mission_type과 suggested_type은 반드시 같은 값이어야 합니다.")

    if not isinstance(mission["params"], dict):
        raise ValueError("params는 객체(JSON object)여야 합니다.")

    if not isinstance(mission["reason"], str) or not mission["reason"].strip():
        raise ValueError("reason은 비어 있지 않은 문자열이어야 합니다.")


def validate_slot_and_type(slot_code: str, suggested_type: str, mission_type: Optional[str] = None) -> None:
    if slot_code not in ALLOWED_TYPES_BY_SLOT:
        raise ValueError(f"허용되지 않은 slot_code: {slot_code}")

    normalized_type = str(suggested_type or "").strip()
    normalized_mission_type = str(mission_type or normalized_type).strip()

    if normalized_type != normalized_mission_type:
        raise ValueError(
            f"mission_type과 suggested_type이 일치하지 않습니다: "
            f"mission_type={normalized_mission_type}, suggested_type={normalized_type}"
        )

    if normalized_type not in ALLOWED_TYPES_BY_SLOT[slot_code]:
        raise ValueError(
            f"slot_code {slot_code} 에 mission_type {normalized_type} 는 허용되지 않습니다."
        )


def validate_forbidden_text(title: str, description: str, reason: Optional[str] = None) -> None:
    if contains_forbidden_phrase(title):
        raise ValueError(f"금지 문구가 title에 포함되어 있습니다: {title}")
    if contains_forbidden_phrase(description):
        raise ValueError(f"금지 문구가 description에 포함되어 있습니다: {description}")
    if reason and contains_forbidden_reason_phrase(reason):
        raise ValueError(f"금지 문구가 reason에 포함되어 있습니다: {reason}")


def _validate_int_candidate(params: Dict[str, Any], key: str, allowed_values: List[int], mission_type: str) -> int:
    value = params.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{mission_type}은 params.{key}(int)가 필요합니다.")
    if value not in allowed_values:
        raise ValueError(f"{mission_type} params.{key}는 {allowed_values} 중 하나여야 합니다. actual={value}")
    return value


def validate_reason_contract(reason: str, suggested_type: str, params: Dict[str, Any]) -> None:
    normalized = normalize_reason_text(reason)
    if not normalized:
        raise ValueError("reason은 비어 있지 않은 문자열이어야 합니다.")
    if len(normalized) < REASON_MIN_LENGTH:
        raise ValueError("reason이 너무 짧습니다.")
    if len(normalized) > REASON_MAX_LENGTH:
        raise ValueError("reason이 너무 깁니다.")
    if contains_forbidden_reason_phrase(normalized):
        raise ValueError(f"reason에 금지 문구가 포함되어 있습니다: {normalized}")
    if is_generic_reason(normalized):
        raise ValueError(f"reason이 너무 일반적입니다: {normalized}")
    if not reason_matches_type(suggested_type, normalized):
        raise ValueError(f"reason이 미션 타입과 충분히 연결되지 않습니다: {suggested_type}")


def validate_params_by_type(suggested_type: str, params: Dict[str, Any]) -> None:
    if suggested_type == "A1_STEP_TARGET":
        _validate_int_candidate(
            params,
            "target_steps",
            TARGET_VALUE_CONSTRAINTS["A1_STEP_TARGET"]["target_steps"],
            suggested_type,
        )

    elif suggested_type == "A2_ACTIVE_KCAL_TARGET":
        _validate_int_candidate(
            params,
            "target_kcal",
            TARGET_VALUE_CONSTRAINTS["A2_ACTIVE_KCAL_TARGET"]["target_kcal"],
            suggested_type,
        )

    elif suggested_type == "B1_TIMER_STRETCH":
        _validate_int_candidate(
            params,
            "duration_min",
            TARGET_VALUE_CONSTRAINTS["B1_TIMER_STRETCH"]["duration_min"],
            suggested_type,
        )

    elif suggested_type == "B2_SLEEP_PREP":
        _validate_int_candidate(
            params,
            "duration_min",
            TARGET_VALUE_CONSTRAINTS["B2_SLEEP_PREP"]["duration_min"],
            suggested_type,
        )

    elif suggested_type == "B3_ROUTINE_CHECK":
        for key in REQUIRED_B3_PARAM_KEYS:
            if key not in params or params.get(key) is None:
                raise ValueError(f"B3_ROUTINE_CHECK는 params.{key} 값이 필요합니다.")

        routine_key = str(params.get("routine_key") or "").strip()
        routine_name = str(params.get("routine_name") or "").strip()

        if routine_key not in get_allowed_routine_keys():
            raise ValueError(f"B3_ROUTINE_CHECK routine_key가 허용 목록에 없습니다: {routine_key}")
        if not isinstance(params.get("routine_name"), str) or not routine_name:
            raise ValueError("B3_ROUTINE_CHECK는 params.routine_name(str)이 필요합니다.")
        if routine_name not in get_allowed_routine_names() and not is_allowed_routine_name_for_key(routine_key, routine_name):
            raise ValueError(f"B3_ROUTINE_CHECK routine_name이 허용 목록에 없습니다: {routine_name}")
        if not is_allowed_routine_name_for_key(routine_key, routine_name):
            raise ValueError(f"B3_ROUTINE_CHECK routine_key와 routine_name이 일치하지 않습니다: {routine_key}/{routine_name}")

        for key in ["routine_label", "routine_category", "icon_key", "action_label"]:
            if not isinstance(params.get(key), str) or not str(params.get(key) or "").strip():
                raise ValueError(f"B3_ROUTINE_CHECK는 params.{key}(str)가 필요합니다.")

        _validate_int_candidate(
            params,
            "repeat_count",
            TARGET_VALUE_CONSTRAINTS["B3_ROUTINE_CHECK"]["repeat_count"],
            suggested_type,
        )
        _validate_int_candidate(
            params,
            "interval_min",
            TARGET_VALUE_CONSTRAINTS["B3_ROUTINE_CHECK"]["interval_min"],
            suggested_type,
        )

    elif suggested_type == "C1_HEALTH_CHECKIN":
        for key in REQUIRED_C1_PARAM_KEYS:
            if key not in params or params.get(key) is None:
                raise ValueError(f"C1_HEALTH_CHECKIN은 params.{key} 값이 필요합니다.")

        checkin_key = str(params.get("checkin_key") or "").strip()
        checkin_label = str(params.get("checkin_label") or "").strip()

        if checkin_key not in get_allowed_checkin_keys():
            raise ValueError(f"C1_HEALTH_CHECKIN checkin_key가 허용 목록에 없습니다: {checkin_key}")
        if not isinstance(params.get("checkin_label"), str) or not checkin_label:
            raise ValueError("C1_HEALTH_CHECKIN은 params.checkin_label(str)이 필요합니다.")
        if checkin_label not in get_allowed_checkin_labels() and not is_allowed_checkin_label_for_key(checkin_key, checkin_label):
            raise ValueError(f"C1_HEALTH_CHECKIN checkin_label이 허용 목록에 없습니다: {checkin_label}")
        if not is_allowed_checkin_label_for_key(checkin_key, checkin_label):
            raise ValueError(f"C1_HEALTH_CHECKIN checkin_key와 checkin_label이 일치하지 않습니다: {checkin_key}/{checkin_label}")

        for key in ["checkin_category", "icon_key", "prompt_label"]:
            if not isinstance(params.get(key), str) or not str(params.get(key) or "").strip():
                raise ValueError(f"C1_HEALTH_CHECKIN은 params.{key}(str)가 필요합니다.")

        _validate_int_candidate(
            params,
            "min_length",
            TARGET_VALUE_CONSTRAINTS["C1_HEALTH_CHECKIN"]["min_length"],
            suggested_type,
        )

    else:
        raise ValueError(f"알 수 없는 suggested_type: {suggested_type}")

def validate_initial_missions(missions: List[Dict[str, Any]]) -> None:
    if len(missions) != 3:
        raise ValueError("초기 미션 생성은 정확히 3개여야 합니다.")

    suggested_types: List[str] = []
    slot_codes: List[str] = []

    for mission in missions:
        validate_mission_shape(mission)
        validate_forbidden_text(mission["title"], mission["description"], mission.get("reason"))
        validate_slot_and_type(mission["slot_code"], mission["suggested_type"], mission.get("mission_type"))
        validate_params_by_type(mission["suggested_type"], mission["params"])
        validate_reason_contract(mission["reason"], mission["suggested_type"], mission["params"])

        slot_codes.append(str(mission["slot_code"]).strip())
        suggested_types.append(mission["suggested_type"])

    if sorted(slot_codes) != ["A", "B", "C"]:
        raise ValueError("초기 미션은 A/B/C 슬롯 각각 1개씩 있어야 합니다.")

    if len(set(suggested_types)) != 3:
        raise ValueError("초기 미션 3개는 mission type이 중복되면 안 됩니다.")

def validate_single_slot_mission(
    mission: Dict[str, Any],
    expected_slot_code: str,
    personalization_policy: Optional[Dict[str, Any]] = None,
) -> None:
    validate_mission_shape(mission)
    validate_forbidden_text(mission["title"], mission["description"], mission.get("reason"))

    actual_slot_code = str(mission.get("slot_code") or "").strip()
    if actual_slot_code != expected_slot_code:
        raise ValueError(
            f"단일 슬롯 미션의 slot_code가 올바르지 않습니다. expected={expected_slot_code}, actual={actual_slot_code}"
        )

    validate_slot_and_type(expected_slot_code, mission["suggested_type"], mission.get("mission_type"))
    validate_params_by_type(mission["suggested_type"], mission["params"])
    validate_a_type_uses_server_selected_target(mission, personalization_policy)
    validate_b3_routine_rotation(mission, personalization_policy)
    validate_reason_contract(mission["reason"], mission["suggested_type"], mission["params"])


def get_allowed_a_target_band_from_policy(
    personalization_policy: Optional[Dict[str, Any]],
    mission_type: str,
) -> List[int]:
    """개인화 정책에서 A타입 허용 target band를 가져온다.

    서버는 권장값을 계산하지만 GPT가 개인화 문맥에 따라 한 단계 주변 값을
    고를 수 있도록 allowed_target_band 안의 값만 허용한다.
    """

    if not personalization_policy:
        return []

    a_targets = ((personalization_policy.get("target_candidates_by_slot") or {}).get("A") or {})
    band_by_type = a_targets.get("allowed_target_band_by_type") or {}
    raw_band = band_by_type.get(mission_type) or []

    # 이전 서버 결정형 구조와의 호환: allowed_target_band_by_type이 없으면
    # selected/recommended policy의 candidate_values를 허용 밴드로 사용한다.
    if not raw_band:
        selected = a_targets.get("recommended_targets") or a_targets.get("selected_targets") or {}
        type_policy = selected.get(mission_type) or {}
        raw_band = type_policy.get("allowed_target_band") or type_policy.get("candidate_values") or []

    result: List[int] = []
    for item in raw_band:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value not in result:
            result.append(value)
    return result




def get_recommended_a_target_from_policy(
    personalization_policy: Optional[Dict[str, Any]],
    mission_type: str,
) -> Optional[int]:
    """개인화 정책에서 A타입 서버 권장 target을 가져온다.

    fallback/rebalance도 GPT 검수 기준과 동일한 숫자 밴드를 사용해야 하므로
    target_candidates_by_slot.A 안의 recommended 값을 우선 사용한다.
    """

    if mission_type not in {"A1_STEP_TARGET", "A2_ACTIVE_KCAL_TARGET"}:
        return None

    a_targets = ((personalization_policy or {}).get("target_candidates_by_slot") or {}).get("A") or {}
    metric_key = "target_steps" if mission_type == "A1_STEP_TARGET" else "target_kcal"
    top_key = "server_recommended_target_steps" if mission_type == "A1_STEP_TARGET" else "server_recommended_target_kcal"

    candidates = [
        a_targets.get(top_key),
        ((a_targets.get("recommended_targets") or {}).get(mission_type) or {}).get(metric_key),
        ((a_targets.get("selected_targets") or {}).get(mission_type) or {}).get(metric_key),
        ((a_targets.get("recommended_targets") or {}).get(mission_type) or {}).get("server_recommended_target"),
        ((a_targets.get("selected_targets") or {}).get(mission_type) or {}).get("server_recommended_target"),
    ]
    for raw in candidates:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value

    band = get_allowed_a_target_band_from_policy(personalization_policy, mission_type)
    return band[0] if band else None


def build_a_target_values_for_fallback(
    activity_summary: Dict[str, Any],
    behavior_summary: Optional[Dict[str, Any]] = None,
    personalization_policy: Optional[Dict[str, Any]] = None,
    previous_mission: Optional[Dict[str, Any]] = None,
) -> tuple[int, int]:
    """A fallback/rebalance가 GPT 검수 기준과 같은 target을 쓰도록 통일한다."""

    policy_steps = get_recommended_a_target_from_policy(personalization_policy, "A1_STEP_TARGET")
    policy_kcal = get_recommended_a_target_from_policy(personalization_policy, "A2_ACTIVE_KCAL_TARGET")
    if policy_steps and policy_kcal:
        return int(policy_steps), int(policy_kcal)

    avg_steps_7d = int((activity_summary or {}).get("avg_steps_7d", 0) or 0)
    avg_active_kcal_7d = int((activity_summary or {}).get("avg_active_kcal_7d", 0) or 0)
    difficulty_bias = str(get_slot_behavior_summary(behavior_summary, "A").get("difficulty_bias") or "neutral")
    # 행동 이력이 부족해 neutral이어도 실제 활동 평균이 낮으면 easy로 계산한다.
    low_activity = avg_steps_7d < 2500 or avg_active_kcal_7d < 80
    effective_difficulty = "easy" if difficulty_bias == "down" or low_activity else "normal"
    goal_direction = str((activity_summary or {}).get("goal_direction") or "health_maintenance")
    a_policy = build_a_selected_target_policy(
        activity_summary=activity_summary,
        goal_direction=goal_direction,
        difficulty=effective_difficulty,
        difficulty_bias=difficulty_bias,
        previous_mission=previous_mission,
    )
    return int(a_policy["A1_STEP_TARGET"]["target_steps"]), int(a_policy["A2_ACTIVE_KCAL_TARGET"]["target_kcal"])

def validate_a_type_uses_server_target_band(
    mission: Dict[str, Any],
    personalization_policy: Optional[Dict[str, Any]],
) -> None:
    """A타입 GPT 출력이 서버가 계산한 허용 target band 안에 있는지 검수한다."""

    mission_type = str(mission.get("suggested_type") or mission.get("mission_type") or "").strip()
    if mission_type not in {"A1_STEP_TARGET", "A2_ACTIVE_KCAL_TARGET"}:
        return

    allowed_band = get_allowed_a_target_band_from_policy(personalization_policy, mission_type)
    if not allowed_band:
        return

    params = mission.get("params") or {}
    key = "target_steps" if mission_type == "A1_STEP_TARGET" else "target_kcal"
    try:
        actual = int(params.get(key))
    except (TypeError, ValueError):
        raise ValueError(f"{mission_type}은 서버 허용 밴드 안의 {key} 값을 사용해야 합니다. allowed={allowed_band}")

    if actual not in allowed_band:
        raise ValueError(
            f"{mission_type} {key}는 서버 허용 밴드 안에서만 선택할 수 있습니다. allowed={allowed_band}, actual={actual}"
        )


# 이전 함수명 호환용 alias. 내부 동작은 exact selected가 아니라 target band 검수다.
def validate_a_type_uses_server_selected_target(
    mission: Dict[str, Any],
    personalization_policy: Optional[Dict[str, Any]],
) -> None:
    validate_a_type_uses_server_target_band(mission, personalization_policy)


def get_blocked_b3_routine_keys_from_policy(personalization_policy: Optional[Dict[str, Any]]) -> List[str]:
    if not personalization_policy:
        return []
    b_targets = ((personalization_policy.get("target_candidates_by_slot") or {}).get("B") or {})
    rotation = b_targets.get("routine_rotation") or {}
    blocked = rotation.get("blocked_routine_keys") or []
    result: List[str] = []
    for item in blocked:
        key = normalize_routine_key(item)
        if key and key not in result:
            result.append(key)
    return result


def validate_b3_routine_rotation(
    mission: Dict[str, Any],
    personalization_policy: Optional[Dict[str, Any]],
) -> None:
    """B3 루틴이 최근 사용한 routine_key를 반복하지 않는지 검수한다."""

    mission_type = str(mission.get("suggested_type") or mission.get("mission_type") or "").strip()
    if mission_type != "B3_ROUTINE_CHECK":
        return

    blocked_keys = get_blocked_b3_routine_keys_from_policy(personalization_policy)
    if not blocked_keys:
        return

    params = mission.get("params") or {}
    routine_key = normalize_routine_key(params.get("routine_key") or params.get("routine_name"))
    if routine_key in blocked_keys:
        raise ValueError(
            f"B3_ROUTINE_CHECK routine_key가 최근 사용된 루틴과 반복됩니다: {routine_key}. blocked={blocked_keys}"
        )


def build_initial_slot_fallback_mission(
    slot_code: str,
    activity_summary: Dict[str, Any],
    behavior_summary: Optional[Dict[str, Any]] = None,
    personalization_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    avg_steps_7d = int(activity_summary.get("avg_steps_7d", 0) or 0)
    avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
    avg_sleep_minutes_7d = int(activity_summary.get("avg_sleep_minutes_7d", 0) or 0)

    preferred_type = get_behavior_preferred_type(slot_code, behavior_summary)
    slot_behavior = get_slot_behavior_summary(behavior_summary, slot_code)
    difficulty_bias = str(slot_behavior.get("difficulty_bias") or "neutral")

    if slot_code == "A":
        selected_steps, selected_kcal = build_a_target_values_for_fallback(
            activity_summary,
            behavior_summary=behavior_summary,
            personalization_policy=personalization_policy,
        )

        if preferred_type == "A1_STEP_TARGET" and avg_active_kcal_7d > 120:
            return build_step_target_mission_data(selected_steps)

        return build_active_kcal_mission_data(selected_kcal)

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
    personalization_policy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    초기 3개 미션 타입 균형 보정.

    최신 정책:
    - GPT가 서버 계약을 통과한 미션은 가능한 한 그대로 사용한다.
    - A1/A2, B1/B2/B3 중 어떤 타입을 고를지는 GPT의 생성 선택을 우선한다.
    - 서버는 타입 선호를 이유로 정상 GPT 미션을 바꾸지 않는다.
    - 잘못된 타입/수치/카탈로그/금지 문구는 이 함수가 아니라 검수 단계에서 reject한다.

    이유:
    - 건강 유지/활동량 낮음 상황에서도 A1_STEP_TARGET은 정상적인 활동형 미션이다.
    - 이전 로직은 avg_active_kcal_7d가 낮으면 A1을 A2로 강제 변경해
      provider가 server_rebalance로 남고, GPT 개인화 생성 체감이 줄어들었다.
    """
    return missions


def validate_initial_type_balance(
    missions: List[Dict[str, Any]],
    activity_summary: Dict[str, Any],
) -> None:
    """
    초기 3개 미션 타입 균형 검수.

    최신 정책:
    - A/B/C 슬롯이 각각 존재하고 개별 미션 검수를 통과했다면 타입 균형은 통과로 본다.
    - 활동량이 낮다는 이유만으로 A2_ACTIVE_KCAL_TARGET을 강제하지 않는다.
    - 수면 데이터가 없거나 부족하다는 이유만으로 B2_SLEEP_PREP를 강제/차단하지 않는다.

    실제 안전성은 validate_initial_missions, validate_slot_and_type,
    validate_params_by_type, validate_a_type_uses_server_selected_target에서 처리한다.
    """
    mission_map = {m.get("slot_code"): m for m in missions if isinstance(m, dict)}
    missing_slots = [slot for slot in ["A", "B", "C"] if slot not in mission_map]
    if missing_slots:
        raise ValueError(f"초기 미션에 필요한 슬롯이 누락되었습니다: {missing_slots}")


def build_b3_routine_fallback_mission(
    activity_summary: Dict[str, Any],
    previous_mission_summary: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    avg_steps_7d = int(activity_summary.get("avg_steps_7d", 0) or 0)
    avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)

    prev_params = (previous_mission_summary or {}).get("params") or {}
    prev_routine_key = normalize_routine_key(prev_params.get("routine_key") or prev_params.get("routine_name"))
    prev_repeat_count = int(prev_params.get("repeat_count", 0) or 0)
    prev_interval_min = int(prev_params.get("interval_min", 0) or 0)

    slot_behavior = get_slot_behavior_summary(behavior_summary, "B")
    difficulty_bias = str(slot_behavior.get("difficulty_bias") or "neutral")
    routine_rotation = slot_behavior.get("routine_rotation") or (behavior_summary or {}).get("b3_routine_rotation") or {}
    recent_routine_keys = list((routine_rotation or {}).get("recent_routine_keys") or [])
    blocked_routine_keys = list((routine_rotation or {}).get("blocked_routine_keys") or [])

    activity_status = "good" if (avg_steps_7d >= 6000 or avg_active_kcal_7d >= 220) else "low"
    candidates = build_routine_candidates(
        difficulty="normal" if activity_status == "good" and difficulty_bias != "down" else "easy",
        goal_direction="health_maintenance",
        activity_status=activity_status,
        sleep_status="unknown",
        data_confidence="medium" if (avg_steps_7d or avg_active_kcal_7d) else "low",
        difficulty_bias=difficulty_bias,
        previous_routine_key=prev_routine_key,
        recent_routine_keys=recent_routine_keys,
        blocked_routine_keys=blocked_routine_keys,
        limit=8,
    )

    choice = candidates[0]
    for option in candidates:
        if (
            option["routine_key"] != prev_routine_key
            or option["repeat_count"] != prev_repeat_count
            or option["interval_min"] != prev_interval_min
        ):
            choice = option
            break

    return build_routine_mission_payload(
        routine_key=choice["routine_key"],
        repeat_count=choice["repeat_count"],
        interval_min=choice["interval_min"],
    )


def build_c1_fallback_mission(
    previous_mission_summary: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
    health_gap: Optional[Dict[str, Any]] = None,
    user_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    prev_params = (previous_mission_summary or {}).get("params") or {}
    prev_min_length = int(prev_params.get("min_length", 0) or 0)
    prev_checkin_key = str(prev_params.get("checkin_key") or "").strip()

    difficulty_bias = str(get_slot_behavior_summary(behavior_summary, "C").get("difficulty_bias") or "neutral")
    min_length_candidates = shift_numeric_candidates_by_bias(
        [15, 20, 25],
        CHECKIN_MIN_LENGTH_MASTER,
        difficulty_bias,
    )
    min_length = choose_candidate(min_length_candidates, prev_min_length or None)

    goal_direction = "weight_loss_support" if str((user_profile or {}).get("goal") or "").replace(" ", "") in {"체중감량", "weight_loss", "weightlosssupport"} else "health_maintenance"
    candidates = build_checkin_candidates(
        goal_direction=goal_direction,
        activity_status=str((health_gap or {}).get("activity_status") or "unknown"),
        sleep_status=str((health_gap or {}).get("sleep_status") or "unknown"),
        data_confidence=str((health_gap or {}).get("data_confidence") or "medium"),
        difficulty="easy" if difficulty_bias == "down" else "normal",
        difficulty_bias=difficulty_bias,
        previous_checkin_key=prev_checkin_key,
        limit=6,
    )

    choice = candidates[0] if candidates else {"checkin_key": "condition_today", "min_length": min_length}
    for candidate in candidates:
        if candidate.get("checkin_key") != prev_checkin_key or int(candidate.get("min_length") or 0) != prev_min_length:
            choice = candidate
            break

    return build_checkin_mission_payload(
        checkin_key=choice.get("checkin_key") or "condition_today",
        min_length=min_length,
    )


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
        normalized = normalize_routine_params(params)
        return {
            "routine_key": normalized["routine_key"],
            "routine_name": normalized["routine_name"],
            "repeat_count": int(normalized.get("repeat_count", 0) or 0),
            "interval_min": int(normalized.get("interval_min", 0) or 0),
        }

    if suggested_type == "C1_HEALTH_CHECKIN":
        normalized = normalize_checkin_params(params)
        return {
            "checkin_key": normalized["checkin_key"],
            "checkin_label": normalized["checkin_label"],
            "min_length": int(normalized.get("min_length", 0) or 0),
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
    health_gap: Optional[Dict[str, Any]] = None,
    user_profile: Optional[Dict[str, Any]] = None,
    personalization_policy: Optional[Dict[str, Any]] = None,
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
        avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
        selected_steps, selected_kcal = build_a_target_values_for_fallback(
            activity_summary,
            behavior_summary=behavior_summary,
            personalization_policy=personalization_policy,
            previous_mission=previous_mission_summary,
        )

        if prev_type == "A1_STEP_TARGET":
            return build_active_kcal_mission_data(selected_kcal)

        if prev_type == "A2_ACTIVE_KCAL_TARGET":
            return build_step_target_mission_data(selected_steps)

        if preferred_type == "A2_ACTIVE_KCAL_TARGET" or avg_active_kcal_7d <= 180:
            return build_active_kcal_mission_data(selected_kcal)

        return build_step_target_mission_data(selected_steps)

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

    return build_c1_fallback_mission(previous_mission_summary, behavior_summary, health_gap, user_profile)

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


def classify_validation_error_codes(message: Optional[str]) -> List[str]:
    """검수/생성 실패 문장을 발표용 코드로 축약한다.

    한 실패가 여러 원인을 가질 수 있으므로 list로 저장한다.
    이 값은 나중에 PPT에서 "금지 문구 실패율", "B3 계약 실패율"처럼
    카테고리별 그래프를 만들 때 사용한다.
    """

    text = str(message or "").lower()
    codes: List[str] = []

    checks = [
        ("json_parse_error", ["json", "파싱", "payload", "리스트 형식", "missions"]),
        ("missing_required_field", ["필드 누락", "값이 비어", "필요합니다", "required"]),
        ("forbidden_text", ["금지 문구", "실패", "마감", "오늘까지", "제한 시간"]),
        ("slot_type_mismatch", ["slot_code", "허용되지 않은", "일치하지", "mission_type과 suggested_type"]),
        ("params_candidate_invalid", ["params", "중 하나", "actual="]),
        ("routine_catalog_invalid", ["routine_key", "routine_name", "카탈로그", "b3_routine_check"]),
        ("reason_invalid", ["reason", "너무 일반적", "너무 짧", "너무 깁"]),
        ("duplicate_or_rotation", ["중복", "동일", "반복", "rotation"]),
        ("type_balance_invalid", ["초기 생성", "초기 a 슬롯", "초기 b 슬롯", "균형"]),
        ("openai_api_error", ["openai", "api", "timeout", "rate"]),
    ]

    for code, keywords in checks:
        if any(keyword in text for keyword in keywords):
            codes.append(code)

    if not codes and text:
        codes.append("other_validation_error")

    return codes


def build_generation_trace_for_log(
    *,
    mode: str,
    mission_count: int,
    slot_codes: List[str],
    user_profile: Dict[str, Any],
    activity_summary: Dict[str, Any],
    comparison: Dict[str, Any],
    public_average: Dict[str, Any],
    health_gap: Dict[str, Any],
    existing_missions: Optional[List[Dict[str, Any]]] = None,
    previous_mission: Optional[Dict[str, Any]] = None,
    retry_attempt: int = 1,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """GPT 입력 계약/개인화 정책을 로그에 같이 남기기 위한 trace payload.

    GPTService._build_user_prompt가 쓰는 payload와 같은 생성 함수를 호출하므로,
    실제 GPT 입력과 로그에 저장되는 정책 결과가 어긋나지 않는다.
    """

    return GPTService.build_generation_trace_context(
        mode=mode,
        mission_count=mission_count,
        slot_codes=slot_codes,
        user_profile=user_profile,
        activity_summary=activity_summary,
        comparison=comparison,
        public_average=public_average,
        health_gap=health_gap,
        existing_missions=existing_missions,
        previous_mission=previous_mission,
        retry_attempt=retry_attempt,
        behavior_summary=behavior_summary,
        system_prompt_enabled=SYSTEM_PROMPT_ENABLED,
    )


def build_generation_input_summary(
    *,
    user_profile: Dict[str, Any],
    activity_summary: Dict[str, Any],
    comparison: Dict[str, Any],
    public_average: Dict[str, Any],
    health_gap: Dict[str, Any],
    behavior_summary: Optional[Dict[str, Any]],
    generation_trace: Dict[str, Any],
    existing_missions: Optional[List[Dict[str, Any]]] = None,
    previous_mission: Optional[Dict[str, Any]] = None,
    disallowed_types: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    summary = {
        "user_profile": user_profile,
        "activity_summary": activity_summary,
        "comparison": comparison,
        "public_average": public_average,
        "health_gap": health_gap,
        "behavior_summary": behavior_summary,
        "existing_missions": existing_missions or [],
        "previous_mission": previous_mission,
        "disallowed_types": disallowed_types or [],
        "generation_trace": generation_trace,
    }
    if extra:
        summary.update(extra)
    return summary


def extract_policy_output_for_log(input_summary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    trace = (input_summary or {}).get("generation_trace") or {}
    policy = trace.get("personalization_policy")
    if not policy:
        return None
    return {
        "policy_version": policy.get("policy_version"),
        "source": policy.get("source"),
        "mode": policy.get("mode"),
        "slot_codes": policy.get("slot_codes"),
        "goal_policy": policy.get("goal_policy"),
        "difficulty_by_slot": policy.get("difficulty_by_slot"),
        "effective_bias_by_slot": policy.get("effective_bias_by_slot"),
        "type_priority_by_slot": policy.get("type_priority_by_slot"),
        "discouraged_types_by_slot": policy.get("discouraged_types_by_slot"),
        "target_candidates_by_slot": policy.get("target_candidates_by_slot"),
        "reason_basis_by_slot": policy.get("reason_basis_by_slot"),
        "reason_basis": policy.get("reason_basis"),
        "notes": policy.get("notes"),
    }


def extract_prompt_metadata_for_log(input_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    trace = (input_summary or {}).get("generation_trace") or {}
    metadata = trace.get("prompt_metadata") or {}
    personalization_policy = trace.get("personalization_policy") or {}
    output_contract = trace.get("output_contract") or {}
    routine_catalog = trace.get("routine_catalog") or {}

    return {
        "prompt_version": metadata.get("prompt_version") or MISSION_GPT_PROMPT_VERSION,
        "policy_version": metadata.get("policy_version") or personalization_policy.get("policy_version"),
        "contract_version": metadata.get("contract_version") or output_contract.get("contract_version") or MISSION_OUTPUT_CONTRACT_VERSION,
        "routine_catalog_version": routine_catalog.get("catalog_version") or ROUTINE_CATALOG_VERSION,
        "experiment_variant": metadata.get("experiment_variant") or MISSION_GPT_EXPERIMENT_VARIANT,
        "system_prompt_enabled": bool(metadata.get("system_prompt_enabled", SYSTEM_PROMPT_ENABLED)),
    }

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
    retry_count: Optional[int] = None,
    fallback_used: Optional[bool] = None,
    validation_error_codes: Optional[List[str]] = None,
    policy_output: Optional[Dict[str, Any]] = None,
    experiment_meta: Optional[Dict[str, Any]] = None,
) -> None:
    if db is None:
        return

    prompt_metadata = extract_prompt_metadata_for_log(input_summary)
    effective_retry_count = int(retry_count if retry_count is not None else max(attempt_no, 0))
    effective_fallback_used = bool(
        fallback_used
        if fallback_used is not None
        else (provider == "server_fallback" or outcome == "fallback_used")
    )
    effective_error_codes = validation_error_codes or classify_validation_error_codes(
        validation_reason or error_message or fallback_reason
    )
    effective_policy_output = policy_output or extract_policy_output_for_log(input_summary)

    effective_experiment_meta = {
        "mode": mode,
        "slot_code": slot_code,
        "requested_count": requested_count,
        "phase": phase,
        "attempt_no": attempt_no,
        "provider": provider,
        "outcome": outcome,
        "prompt_version": prompt_metadata["prompt_version"],
        "policy_version": prompt_metadata.get("policy_version"),
        "contract_version": prompt_metadata["contract_version"],
        "routine_catalog_version": prompt_metadata["routine_catalog_version"],
        "experiment_variant": prompt_metadata["experiment_variant"],
        "system_prompt_enabled": prompt_metadata["system_prompt_enabled"],
        "retry_count": effective_retry_count,
        "fallback_used": effective_fallback_used,
        "validation_error_codes": effective_error_codes,
    }
    if experiment_meta:
        effective_experiment_meta.update(experiment_meta)

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
            prompt_version=prompt_metadata["prompt_version"],
            policy_version=prompt_metadata.get("policy_version"),
            contract_version=prompt_metadata["contract_version"],
            routine_catalog_version=prompt_metadata["routine_catalog_version"],
            experiment_variant=prompt_metadata["experiment_variant"],
            system_prompt_enabled=prompt_metadata["system_prompt_enabled"],
            retry_count=effective_retry_count,
            fallback_used=effective_fallback_used,
            validation_error_codes_json=effective_error_codes,
            policy_output_json=effective_policy_output,
            experiment_meta_json=effective_experiment_meta,
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

    max_attempts = 2 if slot_code == "B" else 3

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
            max_attempts=max_attempts,
            behavior_summary=behavior_summary,
            db=db,
            user_id=user_id,
        )

    except Exception as e:
        raw_response_text = getattr(e, "raw_response_text", None)
        fallback_reason = f"GPT 생성/검수 {max_attempts}회 실패 후 서버 fallback 사용: {str(e)}"

        fallback_trace = build_generation_trace_for_log(
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
            retry_attempt=max_attempts,
            behavior_summary=behavior_summary,
        )
        fallback_policy = fallback_trace.get("personalization_policy") or {}
        fallback_mission = build_retry_fallback_mission(
            slot_code=slot_code,
            previous_mission_summary=previous_mission_summary,
            activity_summary=activity_summary,
            behavior_summary=behavior_summary,
            health_gap=health_gap,
            user_profile=user_profile,
            personalization_policy=fallback_policy,
        )
        validate_single_slot_mission(fallback_mission, slot_code, fallback_policy)

        if user_id is not None:
            fallback_input_summary = build_generation_input_summary(
                user_profile=user_profile,
                activity_summary=activity_summary,
                comparison=comparison,
                public_average=public_average,
                health_gap=health_gap,
                behavior_summary=behavior_summary,
                generation_trace=fallback_trace,
                existing_missions=existing_missions_summary,
                previous_mission=previous_mission_summary,
                disallowed_types=list(disallowed_types),
            )

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
                input_summary=fallback_input_summary,
                output_mission=fallback_mission,
                retry_count=max_attempts,
                fallback_used=True,
            )

        return attach_generation_meta(
            fallback_mission,
            provider="server_fallback",
            attempt_count=max_attempts,
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

    for attempt in range(1, max_attempts + 1):
        attempt_trace = build_generation_trace_for_log(
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
        input_summary = build_generation_input_summary(
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            behavior_summary=behavior_summary,
            generation_trace=attempt_trace,
            existing_missions=existing_missions_summary,
            previous_mission=previous_mission_summary,
            disallowed_types=list(disallowed_types),
        )

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

            mission_data = ensure_mission_reason_for_validation(
                normalize_generated_mission(missions[0]),
                comparison=comparison,
                activity_summary=activity_summary,
                public_average=public_average,
                behavior_summary=behavior_summary,
            )

            validate_single_slot_mission(
                mission_data,
                expected_slot_code=slot_code,
                personalization_policy=attempt_trace.get("personalization_policy"),
            )
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



def scale_c_reward_by_ratio(ratio: float) -> Dict[str, int]:
    """C1 기록형 보상 계산. min_length 15/20/25 기준으로 보상을 차등 지급한다."""
    ratio = clamp_number(ratio, 0.0, 1.0)
    exp = round(5 + (10 - 5) * ratio)
    coins = round(5 + (10 - 5) * ratio)
    return {"exp": int(exp), "coins": int(coins)}


def classify_difficulty_by_ratio(ratio: float) -> str:
    """수치형 params 비율을 easy/normal/hard로 변환한다."""
    ratio = clamp_number(ratio, 0.0, 1.0)
    if ratio <= 0.34:
        return "easy"
    if ratio <= 0.67:
        return "normal"
    return "hard"


def get_mission_difficulty(
    *,
    mission_type: str,
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """미션 params의 최소/최대 수치 기준으로 난이도를 판정한다."""
    params = params or {}
    try:
        if mission_type == "A1_STEP_TARGET":
            target_steps = int(params.get("target_steps", min(STEP_TARGET_MASTER)) or min(STEP_TARGET_MASTER))
            return classify_difficulty_by_ratio(normalize_range(target_steps, min(STEP_TARGET_MASTER), max(STEP_TARGET_MASTER)))

        if mission_type == "A2_ACTIVE_KCAL_TARGET":
            target_kcal = int(params.get("target_kcal", min(KCAL_TARGET_MASTER)) or min(KCAL_TARGET_MASTER))
            return classify_difficulty_by_ratio(normalize_range(target_kcal, min(KCAL_TARGET_MASTER), max(KCAL_TARGET_MASTER)))

        if mission_type == "B1_TIMER_STRETCH":
            duration_min = int(params.get("duration_min", min(STRETCH_DURATION_MASTER)) or min(STRETCH_DURATION_MASTER))
            return classify_difficulty_by_ratio(normalize_range(duration_min, min(STRETCH_DURATION_MASTER), max(STRETCH_DURATION_MASTER)))

        if mission_type == "B2_SLEEP_PREP":
            duration_min = int(params.get("duration_min", min(SLEEP_PREP_DURATION_MASTER)) or min(SLEEP_PREP_DURATION_MASTER))
            return classify_difficulty_by_ratio(normalize_range(duration_min, min(SLEEP_PREP_DURATION_MASTER), max(SLEEP_PREP_DURATION_MASTER)))

        if mission_type == "B3_ROUTINE_CHECK":
            repeat_count = int(params.get("repeat_count", min(ALLOWED_REPEAT_COUNTS)) or min(ALLOWED_REPEAT_COUNTS))
            interval_min = int(params.get("interval_min", max(ALLOWED_INTERVAL_MINUTES)) or max(ALLOWED_INTERVAL_MINUTES))
            repeat_ratio = normalize_range(repeat_count, min(ALLOWED_REPEAT_COUNTS), max(ALLOWED_REPEAT_COUNTS))
            interval_min = clamp_number(interval_min, min(ALLOWED_INTERVAL_MINUTES), max(ALLOWED_INTERVAL_MINUTES))
            interval_ratio = normalize_range(max(ALLOWED_INTERVAL_MINUTES) - interval_min, 0, max(ALLOWED_INTERVAL_MINUTES) - min(ALLOWED_INTERVAL_MINUTES))
            return classify_difficulty_by_ratio((repeat_ratio * 0.7) + (interval_ratio * 0.3))

        if mission_type == "C1_HEALTH_CHECKIN":
            min_length = int(params.get("min_length", min(ALLOWED_CHECKIN_MIN_LENGTHS)) or min(ALLOWED_CHECKIN_MIN_LENGTHS))
            return classify_difficulty_by_ratio(normalize_range(min_length, min(ALLOWED_CHECKIN_MIN_LENGTHS), max(ALLOWED_CHECKIN_MIN_LENGTHS)))

    except (TypeError, ValueError):
        return "easy"

    return "easy"

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

    # C1: 기록형 체크인
    # 15자 = 쉬움, 20자 = 보통, 25자 = 어려움
    if mission_type == "C1_HEALTH_CHECKIN":
        min_length = int(params.get("min_length", min(ALLOWED_CHECKIN_MIN_LENGTHS)) or min(ALLOWED_CHECKIN_MIN_LENGTHS))
        ratio = normalize_range(
            min_length,
            min(ALLOWED_CHECKIN_MIN_LENGTHS),
            max(ALLOWED_CHECKIN_MIN_LENGTHS),
        )
        return scale_c_reward_by_ratio(ratio)

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
    mission_data = normalize_generated_mission(mission_data)
    mission_data = apply_a_type_minimum_label(mission_data)

    slot_code = mission_data["slot_code"]
    mission_type = mission_data["suggested_type"]

    mission_params = mission_data.get("params") or {}
    reward_info = get_mission_reward(
        mission_type=mission_type,
        params=mission_params,
    )
    mission_difficulty = get_mission_difficulty(
        mission_type=mission_type,
        params=mission_params,
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
        difficulty=mission_difficulty,
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

async def generate_initial_missions_core(
    req: GenerateInitialMissionsRequest,
    db: Session,
    user: User,
    progress: Optional[MissionProgressCallback] = None,
    generation_id: Optional[str] = None,
):
    """
    최초 AI 미션 3개 생성
    - 게임 프로필 없으면 여기서 최초 생성
    - A/B/C 슬롯 각각 1개씩 생성
    - 이미 active 미션이 있으면 중복 생성 방지
    """

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="checking_health_data",
        label="헬스 데이터 확인 중",
        detail="인바디와 활동 기록이 미션 생성에 사용할 수 있는 상태인지 확인하고 있어요.",
        progress_percent=8,
        step_index=1,
        total_steps=INITIAL_GENERATION_TOTAL_STEPS,
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

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="checking_existing_missions",
        label="기존 미션 확인 중",
        detail="이미 활성화된 미션이 있는지 확인하고, 필요한 경우 교체 준비를 하고 있어요.",
        progress_percent=16,
        step_index=2,
        total_steps=INITIAL_GENERATION_TOTAL_STEPS,
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
            log_mission_event(
                db,
                user_id=user.id,
                mission=mission,
                event_type=MISSION_EVENT_REFRESHED,
                event_meta={
                    "source": "force_regenerate_initial",
                    "reason": "기존 활성 미션을 초기 미션 재생성으로 교체",
                },
            )
        db.flush()

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="preparing_game_profile",
        label="게임 프로필 준비 중",
        detail="EXP, 코인, 무료 재생성 횟수 같은 게임 정보를 확인하고 있어요.",
        progress_percent=24,
        step_index=3,
        total_steps=INITIAL_GENERATION_TOTAL_STEPS,
    )

    # 3) 게임 프로필 생성
    profile = ensure_game_profile(db, user.id)
    if profile.daily_free_regen_remaining is None:
        profile.daily_free_regen_remaining = 3
    if profile.daily_free_regen_remaining > 3:
        profile.daily_free_regen_remaining = 3
    if profile.mission_coins is None:
        profile.mission_coins = 0

    # 4) GPT 입력 데이터 준비
    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="building_user_summary",
        label="사용자 건강 요약 중",
        detail="키, 몸무게, BMI, 목표, 체지방 정보를 미션용 요약 데이터로 정리하고 있어요.",
        progress_percent=32,
        step_index=4,
        total_steps=INITIAL_GENERATION_TOTAL_STEPS,
    )
    user_profile = build_user_profile_summary(latest_inbody, user)

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="building_activity_summary",
        label="이번 주 활동 평균 계산 중",
        detail="히스토리 화면과 같은 기준으로 걸음 수와 활동 칼로리 평균을 계산하고 있어요.",
        progress_percent=40,
        step_index=5,
        total_steps=INITIAL_GENERATION_TOTAL_STEPS,
    )
    recent_activities = get_recent_activity_records(db, user.id, days=7)
    activity_summary = build_activity_summary(latest_activity, recent_activities)

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="building_health_gap",
        label="공공 기준과 건강 격차 분석 중",
        detail="공공 평균과 앱 기준을 참고해 현재 상태를 비교하고 있어요.",
        progress_percent=50,
        step_index=6,
        total_steps=INITIAL_GENERATION_TOTAL_STEPS,
    )
    public_average = await get_public_average_summary(db, latest_inbody, user)
    health_gap = build_health_gap_summary(latest_inbody, latest_activity, public_average, activity_summary)
    comparison = build_comparison_summary(
        latest_inbody,
        latest_activity,
        public_average,
        activity_summary,
        health_gap,
    )
    behavior_summary = build_behavior_adaptation_summary(db, user.id)

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="building_personalization_policy",
        label="개인화 정책 계산 중",
        detail="목표, 활동 평균, 최근 새로고침/완료 이력을 반영해 미션 수치와 루틴 후보를 정하고 있어요.",
        progress_percent=62,
        step_index=7,
        total_steps=INITIAL_GENERATION_TOTAL_STEPS,
    )

    # 5) GPT 호출 + 초기 타입 편향 보정
    missions: Optional[List[Dict[str, Any]]] = None
    last_generation_error: Optional[Exception] = None

    for attempt in range(1, 5):
        attempt_trace = build_generation_trace_for_log(
            mode="initial",
            mission_count=3,
            slot_codes=["A", "B", "C"],
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            existing_missions=[],
            previous_mission=None,
            retry_attempt=attempt,
            behavior_summary=behavior_summary,
        )
        base_input_summary = build_generation_input_summary(
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            behavior_summary=behavior_summary,
            generation_trace=attempt_trace,
            existing_missions=[],
            previous_mission=None,
        )

        try:
            await emit_generation_progress(
                progress,
                generation_id=generation_id,
                stage="calling_gpt",
                label="AI 미션 생성 중",
                detail=f"개인화 정책 안에서 A/B/C 미션과 추천 이유를 생성하고 있어요. ({attempt}차 시도)",
                progress_percent=72,
                step_index=8,
                total_steps=INITIAL_GENERATION_TOTAL_STEPS,
                meta={"attempt": attempt},
            )
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

            await emit_generation_progress(
                progress,
                generation_id=generation_id,
                stage="validating_result",
                label="서버 검수 중",
                detail="미션 타입, A타입 허용 수치 밴드, 루틴/체크인 키, 금지 문구를 확인하고 있어요.",
                progress_percent=84,
                step_index=9,
                total_steps=INITIAL_GENERATION_TOTAL_STEPS,
                meta={"attempt": attempt},
            )

            if not isinstance(generated_missions, list):
                raise ValueError("GPT 초기 미션 응답이 리스트 형식이 아닙니다.")

            generated_missions = [
                ensure_mission_reason_for_validation(
                    normalize_generated_mission(m),
                    comparison=comparison,
                    activity_summary=activity_summary,
                    public_average=public_average,
                    behavior_summary=behavior_summary,
                )
                for m in generated_missions
                if isinstance(m, dict)
            ]

            validate_initial_missions(generated_missions)
            for mission in generated_missions:
                validate_a_type_uses_server_selected_target(
                    mission,
                    attempt_trace.get("personalization_policy"),
                )

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
                attempt_trace.get("personalization_policy"),
            )

            validate_initial_missions(generated_missions)
            for mission in generated_missions:
                validate_a_type_uses_server_selected_target(
                    mission,
                    attempt_trace.get("personalization_policy"),
                )
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
                        **base_input_summary,
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

            await emit_generation_progress(
                progress,
                generation_id=generation_id,
                stage="validation_retry" if attempt < 4 else "validation_failed",
                label="검수 결과 재시도 준비 중" if attempt < 4 else "서버 fallback 준비 중",
                detail=(
                    "생성 결과가 서버 규칙과 맞지 않아 다시 생성하고 있어요."
                    if attempt < 4
                    else "반복 실패로 안전한 서버 fallback 미션을 준비하고 있어요."
                ),
                progress_percent=86 if attempt < 4 else 88,
                step_index=9,
                total_steps=INITIAL_GENERATION_TOTAL_STEPS,
                meta={"attempt": attempt, "reason": str(e)},
            )

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
                input_summary=base_input_summary,
                output_mission=None,
            )

    if not missions:
        await emit_generation_progress(
            progress,
            generation_id=generation_id,
            stage="using_fallback",
            label="안전 미션으로 보정 중",
            detail="AI 결과가 반복해서 규칙에 맞지 않아 서버가 검수 가능한 기본 맞춤 미션을 만들고 있어요.",
            progress_percent=90,
            step_index=9,
            total_steps=INITIAL_GENERATION_TOTAL_STEPS,
        )
        fallback_reason = f"초기 GPT 미션 생성/검수 4회 실패 후 서버 fallback 사용: {str(last_generation_error)}"
        fallback_trace = build_generation_trace_for_log(
            mode="initial",
            mission_count=3,
            slot_codes=["A", "B", "C"],
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            existing_missions=[],
            previous_mission=None,
            retry_attempt=4,
            behavior_summary=behavior_summary,
        )
        fallback_input_summary = build_generation_input_summary(
            user_profile=user_profile,
            activity_summary=activity_summary,
            comparison=comparison,
            public_average=public_average,
            health_gap=health_gap,
            behavior_summary=behavior_summary,
            generation_trace=fallback_trace,
            existing_missions=[],
            previous_mission=None,
        )

        fallback_policy = fallback_trace.get("personalization_policy") or {}
        fallback_missions = [
            build_initial_slot_fallback_mission("A", activity_summary, behavior_summary, fallback_policy),
            build_initial_slot_fallback_mission("B", activity_summary, behavior_summary, fallback_policy),
            build_initial_slot_fallback_mission("C", activity_summary, behavior_summary, fallback_policy),
        ]

        validate_initial_missions(fallback_missions)
        for fallback_mission in fallback_missions:
            validate_a_type_uses_server_selected_target(fallback_mission, fallback_policy)
            validate_b3_routine_rotation(fallback_mission, fallback_policy)
        validate_initial_type_balance(fallback_missions, activity_summary)

        missions = []
        for fallback_mission in fallback_missions:
            slot_code = fallback_mission.get("slot_code")
            mission_with_meta = attach_generation_meta(
                fallback_mission,
                provider="server_fallback",
                attempt_count=4,
                phase="fallback",
                fallback_reason=fallback_reason,
            )
            add_generation_log(
                db,
                user_id=user.id,
                mode="initial",
                slot_code=slot_code,
                requested_count=3,
                phase="fallback",
                attempt_no=0,
                provider="server_fallback",
                outcome="fallback_used",
                mission_type=mission_with_meta.get("suggested_type"),
                validation_status="approved",
                fallback_reason=fallback_reason,
                error_message=str(last_generation_error),
                raw_response_text=getattr(last_generation_error, "raw_response_text", None),
                input_summary=fallback_input_summary,
                output_mission=mission_with_meta,
                retry_count=4,
                fallback_used=True,
            )
            missions.append(mission_with_meta)
    
    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="saving_missions",
        label="DB 저장 중",
        detail="검수된 미션과 생성 로그를 저장하고 게임 화면에 반영할 준비를 하고 있어요.",
        progress_percent=94,
        step_index=10,
        total_steps=INITIAL_GENERATION_TOTAL_STEPS,
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


@router.post("/generate-initial")
async def generate_initial_missions(
    req: GenerateInitialMissionsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await generate_initial_missions_core(req=req, db=db, user=user)


@router.post("/generate-initial/stream")
async def generate_initial_missions_stream(
    req: GenerateInitialMissionsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """최초 미션 생성 과정을 SSE(text/event-stream)로 전달한다."""

    generation_id = f"initial-{user.id}-{int(datetime.utcnow().timestamp() * 1000)}"

    async def event_generator():
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        async def progress_callback(payload: Dict[str, Any]) -> None:
            await queue.put(payload)

        async def runner():
            return await generate_initial_missions_core(
                req=req,
                db=db,
                user=user,
                progress=progress_callback,
                generation_id=generation_id,
            )

        task = asyncio.create_task(runner())

        yield format_sse_event(
            "progress",
            {
                "generation_id": generation_id,
                "status": "queued",
                "stage": "queued",
                "label": "미션 생성 준비 중",
                "detail": "서버가 개인화 미션 생성 작업을 시작하고 있어요.",
                "progress": 2,
                "step_index": 0,
                "total_steps": INITIAL_GENERATION_TOTAL_STEPS,
            },
        )

        while True:
            if task.done() and queue.empty():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=0.25)
                yield format_sse_event("progress", payload)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

        try:
            result = await task
            yield format_sse_event(
                "complete",
                {
                    "generation_id": generation_id,
                    "status": "completed",
                    "stage": "completed",
                    "label": "미션 생성 완료",
                    "detail": "검수된 AI 미션이 게임 화면에 저장되었어요.",
                    "progress": 100,
                    "step_index": INITIAL_GENERATION_TOTAL_STEPS,
                    "total_steps": INITIAL_GENERATION_TOTAL_STEPS,
                    "result": result,
                },
            )
        except HTTPException as e:
            yield format_sse_event(
                "error",
                {
                    "generation_id": generation_id,
                    "status": "failed",
                    "stage": "failed",
                    "label": "미션 생성 실패",
                    "detail": str(e.detail),
                    "progress": 100,
                    "error": str(e.detail),
                    "status_code": e.status_code,
                },
            )
        except Exception as e:
            yield format_sse_event(
                "error",
                {
                    "generation_id": generation_id,
                    "status": "failed",
                    "stage": "failed",
                    "label": "미션 생성 실패",
                    "detail": "미션 생성 중 오류가 발생했습니다.",
                    "progress": 100,
                    "error": str(e),
                    "status_code": 500,
                },
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
        log_mission_event(
            db,
            user_id=user.id,
            mission=target_mission,
            event_type=MISSION_EVENT_STARTED,
            event_meta={
                "source": "start_slot",
                "already_in_progress": True,
            },
        )
        db.commit()
        db.refresh(target_mission)

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
    log_mission_event(
        db,
        user_id=user.id,
        mission=target_mission,
        event_type=MISSION_EVENT_STARTED,
        event_meta={
            "source": "start_slot",
            "already_in_progress": False,
        },
    )
    db.commit()
    db.refresh(target_mission)

    return {
        "ok": True,
        "message": f"{slot_code} 슬롯 미션이 진행중으로 시작되었습니다.",
        "slot_code": slot_code,
        "mission": build_mission_response(target_mission),
    }


async def refresh_slot_mission_core(
    req: RefreshSlotRequest,
    db: Session,
    user: User,
    progress: Optional[MissionProgressCallback] = None,
    generation_id: Optional[str] = None,
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

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="checking_slot",
        label=f"{slot_code} 슬롯 확인 중",
        detail="재생성할 미션 슬롯과 요청 정보를 확인하고 있어요.",
        progress_percent=10,
        step_index=1,
        total_steps=REFRESH_SLOT_TOTAL_STEPS,
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

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="checking_health_data",
        label="헬스 데이터 확인 중",
        detail="인바디와 이번 주 활동 평균을 재생성 기준으로 사용할 수 있는지 확인하고 있어요.",
        progress_percent=22,
        step_index=2,
        total_steps=REFRESH_SLOT_TOTAL_STEPS,
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

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="checking_regen_budget",
        label="재생성 가능 횟수 확인 중",
        detail="무료 재생성 횟수와 미션 쿠폰 사용 가능 여부를 확인하고 있어요.",
        progress_percent=34,
        step_index=3,
        total_steps=REFRESH_SLOT_TOTAL_STEPS,
    )

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

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="checking_current_mission",
        label="기존 미션 확인 중",
        detail="현재 미션과 직전 미션 정보를 비교해 중복을 피할 준비를 하고 있어요.",
        progress_percent=46,
        step_index=4,
        total_steps=REFRESH_SLOT_TOTAL_STEPS,
    )

    # 4) 재생성 비용 차감
    cost_result = consume_refresh_cost(
        profile=profile,
        use_mission_coin_if_needed=req.use_mission_coin_if_needed,
    )

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="consuming_regen_budget",
        label="재생성 비용 처리 중",
        detail="무료 재생성 또는 미션 쿠폰 사용 조건을 안전하게 반영하고 있어요.",
        progress_percent=56,
        step_index=5,
        total_steps=REFRESH_SLOT_TOTAL_STEPS,
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
    health_gap = build_health_gap_summary(latest_inbody, latest_activity, public_average, activity_summary)
    comparison = build_comparison_summary(
        latest_inbody,
        latest_activity,
        public_average,
        activity_summary,
        health_gap,
    )
    pending_refresh_event = build_pending_event_history_item(
        target_mission,
        MISSION_EVENT_REFRESHED,
        event_meta={
            "source": "refresh_slot",
            "cost_type": cost_result.get("cost_type"),
        },
    )
    behavior_summary = get_behavior_summary_with_pending_event(
        db,
        user.id,
        pending_event=pending_refresh_event,
        recent_window_size=BEHAVIOR_HISTORY_WINDOW,
    )

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="building_personalization_context",
        label="개인화 기준 계산 중",
        detail="건강 요약, 행동 이력, B3 반복 차단, A타입 목표 수치를 다시 계산하고 있어요.",
        progress_percent=68,
        step_index=6,
        total_steps=REFRESH_SLOT_TOTAL_STEPS,
    )

    # 7) GPT 호출 + 3회 자동 재시도 + 직전 미션 동일성 차단
    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="generating_and_validating",
        label="AI 미션 생성·검수 중",
        detail="AI가 새 미션을 만들고, 서버가 수치·루틴·중복 규칙을 검수하고 있어요.",
        progress_percent=80,
        step_index=7,
        total_steps=REFRESH_SLOT_TOTAL_STEPS,
    )

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
    

    await emit_generation_progress(
        progress,
        generation_id=generation_id,
        stage="saving_new_mission",
        label="새 미션 저장 중",
        detail="검수된 미션을 DB에 저장하고 카드에 반영할 준비를 하고 있어요.",
        progress_percent=92,
        step_index=8,
        total_steps=REFRESH_SLOT_TOTAL_STEPS,
    )

    # 9) 기존 미션 refreshed 처리
    mark_slot_mission_refreshed(target_mission)
    db.add(target_mission)
    log_mission_event(
        db,
        user_id=user.id,
        mission=target_mission,
        event_type=MISSION_EVENT_REFRESHED,
        event_meta={
            "source": "refresh_slot",
            "cost_type": cost_result.get("cost_type"),
            "next_mission_type": new_mission_data.get("suggested_type"),
        },
    )

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

@router.post("/refresh-slot")
async def refresh_slot_mission(
    req: RefreshSlotRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await refresh_slot_mission_core(req=req, db=db, user=user)


@router.post("/refresh-slot/stream")
async def refresh_slot_mission_stream(
    req: RefreshSlotRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """특정 슬롯 미션 재생성 과정을 SSE(text/event-stream)로 전달한다."""

    slot_code = (req.slot_code or "").strip().upper()
    generation_id = f"refresh-{slot_code or 'slot'}-{user.id}-{int(datetime.utcnow().timestamp() * 1000)}"

    async def event_generator():
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        async def progress_callback(payload: Dict[str, Any]) -> None:
            await queue.put(payload)

        async def runner():
            return await refresh_slot_mission_core(
                req=req,
                db=db,
                user=user,
                progress=progress_callback,
                generation_id=generation_id,
            )

        task = asyncio.create_task(runner())

        yield format_sse_event(
            "progress",
            {
                "generation_id": generation_id,
                "status": "queued",
                "stage": "queued",
                "label": "미션 재생성 준비 중",
                "detail": "업! 바디가 새 미션을 만들기 위해 서버 요청을 시작하고 있어요.",
                "progress": 2,
                "step_index": 0,
                "total_steps": REFRESH_SLOT_TOTAL_STEPS,
            },
        )

        while True:
            if task.done() and queue.empty():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=0.25)
                yield format_sse_event("progress", payload)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

        try:
            result = await task
            ok = bool(result.get("ok")) if isinstance(result, dict) else True
            yield format_sse_event(
                "complete",
                {
                    "generation_id": generation_id,
                    "status": "completed",
                    "stage": "completed",
                    "label": "미션 재생성 완료" if ok else "재생성 조건 확인 필요",
                    "detail": (
                        "새 미션이 카드에 반영될 준비를 마쳤어요."
                        if ok
                        else str(result.get("message") or "재생성 조건을 확인해주세요.")
                    ),
                    "progress": 100,
                    "step_index": REFRESH_SLOT_TOTAL_STEPS,
                    "total_steps": REFRESH_SLOT_TOTAL_STEPS,
                    "result": result,
                },
            )
        except HTTPException as e:
            yield format_sse_event(
                "error",
                {
                    "generation_id": generation_id,
                    "status": "failed",
                    "stage": "failed",
                    "label": "미션 재생성 실패",
                    "detail": str(e.detail),
                    "progress": 100,
                    "error": str(e.detail),
                    "status_code": e.status_code,
                },
            )
        except Exception as e:
            yield format_sse_event(
                "error",
                {
                    "generation_id": generation_id,
                    "status": "failed",
                    "stage": "failed",
                    "label": "미션 재생성 실패",
                    "detail": "미션 재생성 중 오류가 발생했습니다.",
                    "progress": 100,
                    "error": str(e),
                    "status_code": 500,
                },
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    health_gap = build_health_gap_summary(latest_inbody, latest_activity, public_average, activity_summary)
    comparison = build_comparison_summary(
        latest_inbody,
        latest_activity,
        public_average,
        activity_summary,
        health_gap,
    )
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
    target_mission.completed_at = datetime.utcnow()
    target_mission.progress_json = evaluation["progress"]

    apply_mission_reward(db, profile, target_mission)
    new_achievements = evaluate_and_grant_achievements(db, profile)

    db.add(profile)
    db.add(target_mission)
    completed_event_meta = {
        "source": "complete_slot",
        "evaluation": evaluation,
        "regenerate_after_complete": req.regenerate_after_complete,
    }
    log_mission_event(
        db,
        user_id=user.id,
        mission=target_mission,
        event_type=MISSION_EVENT_COMPLETED,
        event_meta=completed_event_meta,
    )
    refresh_behavior_profile_snapshot(db, user.id)

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
    health_gap = build_health_gap_summary(latest_inbody, latest_activity, public_average, activity_summary)
    comparison = build_comparison_summary(
        latest_inbody,
        latest_activity,
        public_average,
        activity_summary,
        health_gap,
    )
    pending_completed_event = build_pending_event_history_item(
        target_mission,
        MISSION_EVENT_COMPLETED,
        event_meta=completed_event_meta,
    )
    behavior_summary = get_behavior_summary_with_pending_event(
        db,
        user.id,
        pending_event=pending_completed_event,
        recent_window_size=BEHAVIOR_HISTORY_WINDOW,
    )

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