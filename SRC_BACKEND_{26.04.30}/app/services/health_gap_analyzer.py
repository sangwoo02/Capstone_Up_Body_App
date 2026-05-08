# app/services/mission_policy/health_gap_analyzer.py

"""
GPT 입력 전 건강 격차 분석 엔진.

역할:
1. 공식/공공 기준값을 이용해 BMI 상태를 계산한다.
2. 현재 앱이 가진 steps/active_kcal 데이터로 활동 상태를 계산하되,
   이 기준은 공식 기준이 아니라 app_internal 기준임을 명확히 표시한다.
3. 목표 유형을 서비스 정책 key로 정리한다.
4. GPT에 넘길 health_gap_summary를 만든다.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.models.user import UserActivity, UserInbody
from app.services.mission_policy.evidence_constants import (
    ADULT_PHYSICAL_ACTIVITY_GUIDELINE,
    ADULT_SLEEP_GUIDELINE,
    APP_INTERNAL_ACTIVITY_THRESHOLDS,
    EVIDENCE_POLICY_VERSION,
    EVIDENCE_SOURCES,
    KOREAN_ADULT_BMI_POLICY,
    WEIGHT_LOSS_POLICY,
)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_goal_type(goal: Optional[str]) -> Dict[str, str]:
    """프론트/DB 목표 문구를 정책 key로 정규화한다."""
    raw_goal = str(goal or "").strip()

    if raw_goal == "체중 감량":
        return {
            "goal_type": "weight_loss",
            "goal_label": "체중 감량",
            "goal_policy": "gradual_activity_support",
        }

    return {
        "goal_type": "health_maintenance",
        "goal_label": "건강 유지",
        "goal_policy": "steady_habit_support",
    }


def classify_bmi(bmi_value: Optional[float]) -> Dict[str, Any]:
    """한국 성인 BMI 기준으로 상세/호환 상태를 함께 반환한다."""
    value = _to_float(bmi_value)
    if value is None or value <= 0:
        return {
            "bmi": None,
            "bmi_status": "unknown",
            "bmi_category_detail": "unknown",
            "bmi_label_ko": "알 수 없음",
            "weight_status": "unknown",
            "basis": KOREAN_ADULT_BMI_POLICY["basis"],
        }

    selected = None
    for category in KOREAN_ADULT_BMI_POLICY["categories"]:
        min_value = category["min_inclusive"]
        max_value = category["max_exclusive"]
        if min_value is not None and value < float(min_value):
            continue
        if max_value is not None and value >= float(max_value):
            continue
        selected = category
        break

    if selected is None:
        selected = KOREAN_ADULT_BMI_POLICY["categories"][-1]

    detail = selected["key"]

    if detail == "underweight":
        legacy_bmi_status = "underweight"
        weight_status = "low"
    elif detail == "normal":
        legacy_bmi_status = "normal"
        weight_status = "normal"
    elif detail == "pre_obesity":
        legacy_bmi_status = "pre_obesity"
        weight_status = "slightly_high"
    else:
        legacy_bmi_status = "obesity"
        weight_status = "high"

    return {
        "bmi": round(value, 1),
        "bmi_status": legacy_bmi_status,
        "bmi_category_detail": detail,
        "bmi_label_ko": selected["label_ko"],
        "weight_status": weight_status,
        "basis": KOREAN_ADULT_BMI_POLICY["basis"],
    }


def get_bmi_weight_range(height_cm: Optional[float]) -> Optional[Dict[str, float]]:
    """사용자 키 기준 한국 성인 BMI 정상 범위 체중을 계산한다."""
    height = _to_float(height_cm)
    if height is None or height <= 0:
        return None

    height_m = height / 100.0
    normal_min = float(KOREAN_ADULT_BMI_POLICY["normal_min"])
    normal_max = float(KOREAN_ADULT_BMI_POLICY["normal_max"])
    normal_mid = float(KOREAN_ADULT_BMI_POLICY["normal_mid"])

    return {
        "min": round(normal_min * height_m * height_m, 1),
        "max": round(normal_max * height_m * height_m, 1),
        "avg": round(normal_mid * height_m * height_m, 1),
    }


def classify_activity_status(
    *,
    activity: Optional[UserActivity],
    activity_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    현재 확보 가능한 steps/active_kcal 기반 활동 상태.

    주의:
    - WHO/CDC의 성인 신체활동 기준은 중강도/고강도 활동 시간과 근력운동 일수가 필요하다.
    - 현재 DB에는 그 필드가 없으므로 WHO 기준 충족 여부는 판정하지 않는다.
    - 아래 low/moderate/good은 서비스 난이도 조절용 app_internal 기준이다.
    """
    activity_summary = activity_summary or {}

    today_steps = _to_int(
        activity_summary.get("today_steps"),
        _to_int(getattr(activity, "steps", 0), 0),
    )
    today_active_kcal = _to_int(
        activity_summary.get("today_active_kcal"),
        _to_int(getattr(activity, "calories", 0), 0),
    )
    avg_steps_7d = _to_int(activity_summary.get("avg_steps_7d"), today_steps)
    avg_active_kcal_7d = _to_int(activity_summary.get("avg_active_kcal_7d"), today_active_kcal)

    step_policy = APP_INTERNAL_ACTIVITY_THRESHOLDS["steps"]
    kcal_policy = APP_INTERNAL_ACTIVITY_THRESHOLDS["active_kcal"]

    if avg_steps_7d >= int(step_policy["good_min_inclusive"]):
        step_status = "good"
    elif avg_steps_7d >= int(step_policy["moderate_min_inclusive"]):
        step_status = "moderate"
    else:
        step_status = "below_average"

    if avg_active_kcal_7d >= int(kcal_policy["good_min_inclusive"]):
        activity_status = "good"
    elif avg_active_kcal_7d >= int(kcal_policy["moderate_min_inclusive"]):
        activity_status = "moderate"
    else:
        activity_status = "low"

    return {
        "today_steps": today_steps,
        "today_active_kcal": today_active_kcal,
        "avg_steps_7d": avg_steps_7d,
        "avg_active_kcal_7d": avg_active_kcal_7d,
        "step_status": step_status,
        "activity_status": activity_status,
        "activity_status_basis": APP_INTERNAL_ACTIVITY_THRESHOLDS["basis"],
        "activity_status_is_official_guideline": False,
        "who_activity_guideline_status": "not_evaluable_with_current_fields",
        "who_activity_guideline_required_fields": ADULT_PHYSICAL_ACTIVITY_GUIDELINE[
            "required_missing_fields"
        ],
    }


def classify_sleep_status(
    *,
    activity: Optional[UserActivity],
    activity_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    activity_summary = activity_summary or {}
    latest_sleep = _to_int(
        activity_summary.get("sleep_minutes_latest"),
        _to_int(getattr(activity, "sleep_minutes", 0), 0),
    )
    avg_sleep = _to_int(activity_summary.get("avg_sleep_minutes_7d"), latest_sleep)

    min_minutes = int(ADULT_SLEEP_GUIDELINE["adult_18_60_min_hours_per_day"] * 60)

    if avg_sleep <= 0:
        sleep_status = "unknown"
    elif avg_sleep < min_minutes:
        sleep_status = "below_recommended"
    else:
        sleep_status = "recommended_or_more"

    return {
        "sleep_minutes_latest": latest_sleep,
        "avg_sleep_minutes_7d": avg_sleep,
        "sleep_status": sleep_status,
        "sleep_basis": ADULT_SLEEP_GUIDELINE["basis"],
        "adult_min_sleep_minutes": min_minutes,
    }


def build_data_confidence(
    *,
    inbody: UserInbody,
    activity: Optional[UserActivity],
    activity_summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    activity_summary = activity_summary or {}

    has_height = _to_float(getattr(inbody, "height", None)) is not None
    has_weight = _to_float(getattr(inbody, "weight", None)) is not None
    has_bmi = _to_float(getattr(inbody, "bmi", None)) is not None

    latest_steps = _to_int(getattr(activity, "steps", 0), 0)
    latest_kcal = _to_int(getattr(activity, "calories", 0), 0)
    latest_sleep = _to_int(getattr(activity, "sleep_minutes", 0), 0)

    avg_steps = _to_int(activity_summary.get("avg_steps_7d"), latest_steps)
    avg_kcal = _to_int(activity_summary.get("avg_active_kcal_7d"), latest_kcal)
    avg_sleep = _to_int(activity_summary.get("avg_sleep_minutes_7d"), latest_sleep)

    # activity_summary는 활동 데이터가 없어도 0으로 채워진 dict일 수 있다.
    # 따라서 dict 존재 여부가 아니라 실제 측정값이 하나라도 있는지를 기준으로 판정한다.
    has_steps = avg_steps > 0 or latest_steps > 0
    has_kcal = avg_kcal > 0 or latest_kcal > 0
    has_sleep = avg_sleep > 0 or latest_sleep > 0
    has_activity = has_steps or has_kcal or has_sleep

    score = 0
    score += 2 if has_height and has_weight and has_bmi else 0
    score += 1 if has_activity else 0
    score += 1 if has_steps else 0
    score += 1 if has_kcal else 0

    if score >= 5:
        confidence = "high"
    elif score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "data_confidence": confidence,
        "available_data": {
            "has_height": has_height,
            "has_weight": has_weight,
            "has_bmi": has_bmi,
            "has_activity": has_activity,
            "has_steps": has_steps,
            "has_active_kcal": has_kcal,
            "has_sleep_minutes": has_sleep,
        },
    }


def build_health_gap_summary(
    inbody: UserInbody,
    activity: Optional[UserActivity],
    public_average: Optional[Dict[str, Any]] = None,
    activity_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """GPT/정책 엔진에 전달할 health_gap_summary 생성."""
    public_average = public_average or {}

    bmi_result = classify_bmi(getattr(inbody, "bmi", None))
    activity_result = classify_activity_status(
        activity=activity,
        activity_summary=activity_summary,
    )
    sleep_result = classify_sleep_status(
        activity=activity,
        activity_summary=activity_summary,
    )
    goal_result = normalize_goal_type(getattr(inbody, "goal", None))
    confidence_result = build_data_confidence(
        inbody=inbody,
        activity=activity,
        activity_summary=activity_summary,
    )

    avg_weight = public_average.get("avg_weight")
    avg_bmi = public_average.get("avg_bmi")
    avg_body_fat = public_average.get("avg_body_fat")

    weight = _to_float(getattr(inbody, "weight", None))
    bmi = _to_float(getattr(inbody, "bmi", None))
    body_fat = _to_float(getattr(inbody, "body_fat", None))

    public_weight_gap_kg = None
    public_bmi_gap = None
    public_body_fat_gap = None

    if weight is not None and avg_weight is not None:
        public_weight_gap_kg = round(weight - float(avg_weight), 1)
    if bmi is not None and avg_bmi is not None:
        public_bmi_gap = round(bmi - float(avg_bmi), 1)
    if body_fat is not None and avg_body_fat is not None:
        public_body_fat_gap = round(body_fat - float(avg_body_fat), 1)

    normal_weight_range = get_bmi_weight_range(getattr(inbody, "height", None))
    weight_gap_kg = None
    if normal_weight_range and weight is not None:
        if weight < normal_weight_range["min"]:
            weight_gap_kg = round(weight - normal_weight_range["min"], 1)
        elif weight > normal_weight_range["max"]:
            weight_gap_kg = round(weight - normal_weight_range["max"], 1)
        else:
            weight_gap_kg = 0.0

    summary = {
        "policy_version": EVIDENCE_POLICY_VERSION,
        "goal_type": goal_result["goal_type"],
        "goal_label": goal_result["goal_label"],
        "goal_policy": goal_result["goal_policy"],
        "weight_gap_kg": weight_gap_kg,
        "bmi_gap": None,
        "body_fat_gap": public_body_fat_gap,
        "weight_status": bmi_result["weight_status"],
        "bmi_status": bmi_result["bmi_status"],
        "bmi_category_detail": bmi_result["bmi_category_detail"],
        "bmi_label_ko": bmi_result["bmi_label_ko"],
        "body_fat_status": "reference_only" if public_body_fat_gap is not None else "unknown",
        "normal_weight_range": normal_weight_range,
        "bmi_basis": bmi_result["basis"],
        "public_weight_gap_kg": public_weight_gap_kg,
        "public_bmi_gap": public_bmi_gap,
        "public_body_fat_gap": public_body_fat_gap,
        "public_average_is_reference_only": True,
        "public_data_source": public_average.get("source"),
        "step_status": activity_result["step_status"],
        "activity_status": activity_result["activity_status"],
        "activity_status_basis": activity_result["activity_status_basis"],
        "activity_status_is_official_guideline": activity_result[
            "activity_status_is_official_guideline"
        ],
        "who_activity_guideline_status": activity_result["who_activity_guideline_status"],
        "who_activity_guideline_required_fields": activity_result[
            "who_activity_guideline_required_fields"
        ],
        "sleep_status": sleep_result["sleep_status"],
        "sleep_basis": sleep_result["sleep_basis"],
        "adult_min_sleep_minutes": sleep_result["adult_min_sleep_minutes"],
        "guidelines": {
            "bmi": KOREAN_ADULT_BMI_POLICY,
            "physical_activity": ADULT_PHYSICAL_ACTIVITY_GUIDELINE,
            "sleep": ADULT_SLEEP_GUIDELINE,
            "weight_loss": WEIGHT_LOSS_POLICY,
        },
        "evidence_sources": EVIDENCE_SOURCES,
    }

    summary.update(activity_result)
    summary.update(sleep_result)
    summary.update(confidence_result)

    return summary
