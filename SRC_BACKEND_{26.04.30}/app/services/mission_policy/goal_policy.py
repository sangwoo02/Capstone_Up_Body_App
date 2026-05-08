"""목표별 AI 미션 개인화 정책.

이 파일은 GPT 프롬프트를 길게 만들기 위한 파일이 아니라,
FastAPI 서버가 먼저 사용자 목표에 맞는 타입 우선순위/난이도 방향을 정리하기 위한 정책 파일이다.

주의:
- 이 정책은 의학적 처방이 아니라 앱 미션 난이도 조정 정책이다.
- 체중 감량 목표가 있어도 체중 감량 수치 자체를 미션 목표로 만들지 않는다.
- 실패/마감/압박 표현이 들어가는 정책은 만들지 않는다.
"""

from __future__ import annotations

from typing import Any, Dict

POLICY_VERSION = "mission_policy_step2_personalization_2026_05_06"

GOAL_DIRECTIONS = {
    "health_maintenance": {
        "goal_type": "건강 유지",
        "goal_label": "건강 유지",
        "goal_direction": "health_maintenance",
        "description": "꾸준한 활동, 생활 루틴, 컨디션 기록을 우선하는 정책",
    },
    "weight_loss_support": {
        "goal_type": "체중 감량",
        "goal_label": "체중 감량",
        "goal_direction": "weight_loss_support",
        "description": "체중 압박 없이 활동량과 생활 루틴을 자연스럽게 늘리는 정책",
    },
}

# 슬롯별 type_priority는 최종값이 아니라 base 정책이다.
# personalization_engine.py에서 건강 격차, 행동 이력, 직전 미션을 반영해 재정렬한다.
GOAL_MISSION_POLICIES: Dict[str, Dict[str, Any]] = {
    "health_maintenance": {
        "target_intensity": "gentle",
        "slot_type_priority": {
            "A": ["A2_ACTIVE_KCAL_TARGET", "A1_STEP_TARGET"],
            "B": ["B3_ROUTINE_CHECK", "B1_TIMER_STRETCH", "B2_SLEEP_PREP"],
            "C": ["C1_HEALTH_CHECKIN"],
        },
        "slot_focus": {
            "A": "무리한 수치보다 꾸준한 움직임 유지",
            "B": "생활 루틴과 가벼운 회복 습관",
            "C": "컨디션 기록과 생활 패턴 점검",
        },
        "reason_basis": [
            "건강 유지 목표는 높은 강도보다 꾸준히 이어가기 쉬운 활동과 루틴을 우선합니다.",
            "생활 루틴과 컨디션 기록을 함께 반영해 부담이 낮은 미션으로 조정합니다.",
        ],
    },
    "weight_loss_support": {
        "target_intensity": "gradual",
        "slot_type_priority": {
            "A": ["A2_ACTIVE_KCAL_TARGET", "A1_STEP_TARGET"],
            "B": ["B3_ROUTINE_CHECK", "B1_TIMER_STRETCH", "B2_SLEEP_PREP"],
            "C": ["C1_HEALTH_CHECKIN"],
        },
        "slot_focus": {
            "A": "활동량을 자연스럽게 늘리는 목표 수치",
            "B": "체중 압박보다 생활 습관을 늘리는 루틴",
            "C": "컨디션과 실천 흐름 기록",
        },
        "reason_basis": [
            "체중 감량 목표는 직접적인 체중 압박 대신 활동량을 자연스럽게 늘리는 방향으로 반영합니다.",
            "최근 활동 흐름을 기준으로 무리하지 않는 후보 수치 안에서 미션을 조정합니다.",
        ],
    },
}


def normalize_goal_direction(user_profile: Dict[str, Any] | None, health_gap: Dict[str, Any] | None) -> str:
    """서비스 목표값을 정책 key로 정규화한다."""

    health_gap = health_gap or {}
    user_profile = user_profile or {}

    gap_direction = str(health_gap.get("goal_direction") or "").strip()
    if gap_direction in GOAL_MISSION_POLICIES:
        return gap_direction

    raw_goal = str(
        user_profile.get("goal")
        or user_profile.get("goal_type")
        or health_gap.get("goal_type")
        or ""
    ).strip()

    if raw_goal in {"체중 감량", "체중감량", "weight_loss", "weight_loss_support"}:
        return "weight_loss_support"

    return "health_maintenance"


def get_goal_policy(user_profile: Dict[str, Any] | None, health_gap: Dict[str, Any] | None) -> Dict[str, Any]:
    """개인화 엔진에서 사용할 목표 정책 payload를 반환한다."""

    direction = normalize_goal_direction(user_profile, health_gap)
    base = GOAL_MISSION_POLICIES.get(direction) or GOAL_MISSION_POLICIES["health_maintenance"]
    meta = GOAL_DIRECTIONS.get(direction) or GOAL_DIRECTIONS["health_maintenance"]

    return {
        "policy_version": POLICY_VERSION,
        **meta,
        "target_intensity": base["target_intensity"],
        "slot_type_priority": base["slot_type_priority"],
        "slot_focus": base["slot_focus"],
        "reason_basis": list(base["reason_basis"]),
    }
