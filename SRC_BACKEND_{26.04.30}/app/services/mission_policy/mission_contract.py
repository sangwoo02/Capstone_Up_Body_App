"""GPT 미션 입출력 계약 정의.

FastAPI 서버가 GPT에게 요구하는 JSON 구조와 서버 검수 기준을 한 곳에서 관리한다.
이 계약은 GPT가 자유 생성기가 아니라 서버 정책 안에서 구조화된 미션을 생성하도록 제한한다.
"""

from __future__ import annotations

from typing import Any, Dict

from app.services.mission_policy.routine_catalog import summarize_routine_catalog_for_prompt
from app.services.mission_policy.checkin_catalog import summarize_checkin_catalog_for_prompt
from app.services.mission_policy.numeric_target_policy import STEP_TARGET_MASTER, KCAL_TARGET_MASTER

MISSION_OUTPUT_CONTRACT_VERSION = "mission_output_contract_v1_2026_05_06"

ALLOWED_TYPES_BY_SLOT_CONTRACT = {
    "A": ["A1_STEP_TARGET", "A2_ACTIVE_KCAL_TARGET"],
    "B": ["B1_TIMER_STRETCH", "B2_SLEEP_PREP", "B3_ROUTINE_CHECK"],
    "C": ["C1_HEALTH_CHECKIN"],
}

# GPT 출력과 서버 검수에서 공유하는 허용 후보값.
# 이 값 밖의 target은 GPT가 임의 생성한 값으로 보고 검수에서 거절한다.
TARGET_VALUE_CONSTRAINTS = {
    "A1_STEP_TARGET": {"target_steps": STEP_TARGET_MASTER},
    "A2_ACTIVE_KCAL_TARGET": {"target_kcal": KCAL_TARGET_MASTER},
    "B1_TIMER_STRETCH": {"duration_min": [5, 10, 15, 20, 25, 30]},
    "B2_SLEEP_PREP": {"duration_min": [10, 15, 20, 25, 30]},
    "B3_ROUTINE_CHECK": {
        "repeat_count": [2, 3, 4, 5],
        "interval_min": [5, 10, 15],
    },
    "C1_HEALTH_CHECKIN": {"min_length": [15, 20, 25]},
}

REQUIRED_MISSION_KEYS = [
    "slot_code",
    "title",
    "description",
    "mission_type",
    "suggested_type",
    "params",
    "reason",
]

REQUIRED_B3_PARAM_KEYS = [
    "routine_key",
    "routine_name",
    "routine_label",
    "routine_category",
    "icon_key",
    "action_label",
    "repeat_count",
    "interval_min",
]

REQUIRED_C1_PARAM_KEYS = [
    "checkin_key",
    "checkin_label",
    "checkin_category",
    "icon_key",
    "prompt_label",
    "min_length",
]


def _example_params_for_type(mission_type: str) -> Dict[str, Any]:
    if mission_type == "A1_STEP_TARGET":
        return {"target_steps": 1000}
    if mission_type == "A2_ACTIVE_KCAL_TARGET":
        return {"target_kcal": 40}
    if mission_type in {"B1_TIMER_STRETCH", "B2_SLEEP_PREP"}:
        return {"duration_min": 5 if mission_type == "B1_TIMER_STRETCH" else 10}
    if mission_type == "B3_ROUTINE_CHECK":
        return {
            "routine_key": "hydration",
            "routine_name": "물 마시기",
            "routine_label": "물 마시기",
            "routine_category": "hydration",
            "icon_key": "droplets",
            "action_label": "물 한 컵 마시기",
            "repeat_count": 2,
            "interval_min": 10,
        }
    if mission_type == "C1_HEALTH_CHECKIN":
        return {
            "checkin_key": "condition_today",
            "checkin_label": "오늘 컨디션",
            "checkin_category": "condition",
            "icon_key": "heart_pulse",
            "prompt_label": "오늘 몸 상태와 기분",
            "min_length": 15,
        }
    return {}


def build_gpt_output_contract(slot_codes: list[str] | None = None) -> Dict[str, Any]:
    """GPT user prompt에 넣을 출력 계약 payload."""

    slot_codes = slot_codes or ["A"]
    first_slot = slot_codes[0] if slot_codes else "A"
    first_type = ALLOWED_TYPES_BY_SLOT_CONTRACT.get(first_slot, ["A1_STEP_TARGET"])[0]

    return {
        "contract_version": MISSION_OUTPUT_CONTRACT_VERSION,
        "top_level_type": "object",
        "required_top_level_key": "missions",
        "missions_type": "array",
        "required_mission_keys": REQUIRED_MISSION_KEYS,
        "type_alias_rule": "mission_type and suggested_type must be identical",
        "slot_type_rule": "mission_type must be included in allowed_types_by_slot[slot_code]",
        "params_rule": "params must match the exact schema and allowed candidate values for mission_type",
        "a_type_hybrid_band_rule": "For A1_STEP_TARGET and A2_ACTIVE_KCAL_TARGET, use personalization_policy.target_candidates_by_slot.A.server_recommended_target_* as the first recommendation, but you may choose another value only if it is inside allowed_target_band_by_type for that mission type.",
        "reason_rule": "reason is required, non-empty, user-visible, and must explain selected params without diagnosis or pressure",
        "b3_rule": {
            "required_param_keys": REQUIRED_B3_PARAM_KEYS,
            "routine_key_rule": "routine_key must exist in routine_catalog.allowed_routines",
            "routine_name_rule": "routine_name must match the same catalog item as routine_key",
            "allowed_catalog": summarize_routine_catalog_for_prompt(),
        },
        "c1_rule": {
            "required_param_keys": REQUIRED_C1_PARAM_KEYS,
            "checkin_key_rule": "checkin_key must exist in checkin_catalog.allowed_checkins",
            "checkin_label_rule": "checkin_label must match the same catalog item as checkin_key",
            "allowed_catalog": summarize_checkin_catalog_for_prompt(),
        },
        "target_value_constraints": TARGET_VALUE_CONSTRAINTS,
        "must_return_example_shape": {
            "missions": [
                {
                    "slot_code": first_slot,
                    "title": "문자열",
                    "description": "문자열",
                    "mission_type": first_type,
                    "suggested_type": first_type,
                    "params": _example_params_for_type(first_type),
                    "reason": "선택한 타입과 params를 설명하는 사용자 표시용 문장",
                }
            ]
        },
    }
