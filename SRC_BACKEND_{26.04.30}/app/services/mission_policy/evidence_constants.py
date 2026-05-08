# app/services/mission_policy/evidence_constants.py

"""
공식/공공 기준값 정책 상수.

중요 원칙:
- 이 파일의 공식 기준값은 의학적 진단용이 아니라 AI 미션 난이도 조정과 설명 근거용이다.
- 걸음 수/활동칼로리의 보편적인 공식 일일 기준은 WHO/CDC/KDCA 기준으로 확정하기 어렵다.
  따라서 steps/active_kcal 기준은 app_internal 기준으로 분리한다.
- 물 섭취량, 체중감량 속도처럼 사용자별 차이가 큰 값은 미션 목표로 직접 쓰지 않도록 플래그를 둔다.
"""

from __future__ import annotations

from typing import Any, Dict


EVIDENCE_POLICY_VERSION = "evidence_policy_v1_2026_05_05"


EVIDENCE_SOURCES = {
    "physical_activity": {
        "source_name": "WHO physical activity fact sheet / guidelines",
        "summary": "성인은 주 150~300분 중강도 또는 75~150분 고강도 유산소 활동, 주 2일 이상 근력 활동 권고",
    },
    "bmi_korea": {
        "source_name": "질병관리청 국가건강정보포털 / 서울시민 건강포털 BMI 기준",
        "summary": "한국 성인 BMI 기준: 18.5 미만 저체중, 18.5~22.9 정상, 23~24.9 비만전단계, 25 이상 비만",
    },
    "sleep_adult": {
        "source_name": "CDC Sleep recommendations",
        "summary": "성인 권장 수면 시간은 하루 7시간 이상",
    },
    "weight_loss": {
        "source_name": "CDC Healthy Weight and Growth",
        "summary": "점진적 체중감량 참고 속도는 주 1~2파운드이나, 본 앱에서는 직접 감량 목표 산출에 사용하지 않음",
    },
}


KOREAN_ADULT_BMI_POLICY: Dict[str, Any] = {
    "basis": "korean_adult_bmi_kdca_seoul_health",
    "unit": "kg/m^2",
    "normal_min": 18.5,
    "normal_max": 22.9,
    "normal_mid": 20.7,
    "categories": [
        {
            "key": "underweight",
            "label_ko": "저체중",
            "min_inclusive": None,
            "max_exclusive": 18.5,
        },
        {
            "key": "normal",
            "label_ko": "정상",
            "min_inclusive": 18.5,
            "max_exclusive": 23.0,
        },
        {
            "key": "pre_obesity",
            "label_ko": "비만전단계",
            "min_inclusive": 23.0,
            "max_exclusive": 25.0,
        },
        {
            "key": "obesity_class_1",
            "label_ko": "1단계 비만",
            "min_inclusive": 25.0,
            "max_exclusive": 30.0,
        },
        {
            "key": "obesity_class_2",
            "label_ko": "2단계 비만",
            "min_inclusive": 30.0,
            "max_exclusive": 35.0,
        },
        {
            "key": "obesity_class_3",
            "label_ko": "3단계 비만",
            "min_inclusive": 35.0,
            "max_exclusive": None,
        },
    ],
}


ADULT_PHYSICAL_ACTIVITY_GUIDELINE: Dict[str, Any] = {
    "basis": "who_adult_physical_activity_guideline",
    "moderate_aerobic_min_per_week": 150,
    "moderate_aerobic_max_per_week": 300,
    "vigorous_aerobic_min_per_week": 75,
    "vigorous_aerobic_max_per_week": 150,
    "muscle_strengthening_min_days_per_week": 2,
    "can_evaluate_with_current_data": False,
    "required_missing_fields": [
        "moderate_activity_minutes_7d",
        "vigorous_activity_minutes_7d",
        "strength_training_days_7d",
    ],
}


ADULT_SLEEP_GUIDELINE: Dict[str, Any] = {
    "basis": "cdc_adult_sleep_recommendation",
    "adult_18_60_min_hours_per_day": 7,
    "adult_61_64_min_hours_per_day": 7,
    "adult_61_64_max_hours_per_day": 9,
    "adult_65_plus_min_hours_per_day": 7,
    "adult_65_plus_max_hours_per_day": 8,
}


WEIGHT_LOSS_POLICY: Dict[str, Any] = {
    "basis": "cdc_gradual_weight_loss_reference",
    "gradual_loss_lb_per_week_min": 1,
    "gradual_loss_lb_per_week_max": 2,
    "use_for_direct_mission_target": False,
    "note": "식단/의료 상담 없이 앱이 kg 감량 목표를 자동 산출하지 않는다. 목표 유형 가중치에만 사용한다.",
}


# 공식 기준이 아니라 서비스 운영 기준이다.
# WHO/CDC/KDCA가 특정 일일 걸음수나 active_kcal 목표를 모든 성인에게 공통 기준으로 제시하지 않으므로
# 미션 난이도 분기용 내부 기준으로만 사용한다.
APP_INTERNAL_ACTIVITY_THRESHOLDS: Dict[str, Any] = {
    "basis": "app_internal_steps_kcal_thresholds_v1",
    "is_official_guideline": False,
    "steps": {
        "below_average_max_exclusive": 4000,
        "moderate_min_inclusive": 4000,
        "good_min_inclusive": 7000,
    },
    "active_kcal": {
        "low_max_exclusive": 150,
        "moderate_min_inclusive": 150,
        "good_min_inclusive": 300,
    },
}
