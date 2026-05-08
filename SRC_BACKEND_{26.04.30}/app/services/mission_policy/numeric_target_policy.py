"""A 슬롯 숫자 목표 산출 정책.

이 파일은 FastAPI 서버가 사용자 최근 활동 요약과 행동 이력에 따라
권장 목표값과 허용 목표 밴드를 계산하기 위한 정책 모듈이다.

중요:
- 걸음 수/활동칼로리 목표는 의학 공식 기준이 아니라 앱 내부 난이도 정책이다.
- GPT는 서버가 계산한 recommended target을 우선 참고하되, allowed_target_band 안에서
  사용자에게 자연스러운 수치를 선택할 수 있다.
- 서버는 allowed_target_band 밖의 숫자는 검수에서 거절한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 앱 내부 A타입 허용 목표값.
# 기존 2500보/80kcal 최소값은 활동량이 낮은 사용자에게 너무 높게 느껴질 수 있어
# 낮은 시작 구간을 추가했다. 이 값들은 의학 기준이 아니라 앱 난이도 정책이다.
STEP_TARGET_MASTER = [1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 7000, 8000, 9000]
KCAL_TARGET_MASTER = [40, 60, 80, 100, 120, 150, 180, 220, 250, 300]

A_TARGET_POLICY_VERSION = "a_target_policy_hybrid_band_v1_2026_05_06"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, min_value: int, max_value: int) -> float:
    return max(min_value, min(max_value, value))


def _round_up_to_allowed(value: float, allowed_values: List[int]) -> int:
    for candidate in allowed_values:
        if value <= candidate:
            return candidate
    return allowed_values[-1]


def _nearest_index(allowed_values: List[int], value: int) -> int:
    if value in allowed_values:
        return allowed_values.index(value)
    return min(range(len(allowed_values)), key=lambda i: abs(allowed_values[i] - value))


def _shift_allowed_value(value: int, allowed_values: List[int], bias: str, *, steps: int = 1) -> int:
    if bias not in {"up", "down"}:
        return value
    idx = _nearest_index(allowed_values, value)
    offset = steps if bias == "up" else -steps
    return allowed_values[max(0, min(len(allowed_values) - 1, idx + offset))]


def _candidate_window(selected: int, allowed_values: List[int], *, radius: int = 1) -> List[int]:
    idx = _nearest_index(allowed_values, selected)
    start = max(0, idx - radius)
    end = min(len(allowed_values), idx + radius + 1)
    window = allowed_values[start:end]
    # recommended target을 항상 맨 앞에 둔다. GPT가 밴드 안에서 선택하더라도
    # 서버 권장값을 가장 먼저 보게 하기 위함이다.
    return [selected] + [value for value in window if value != selected]


def _make_hybrid_target_payload(
    *,
    metric_key: str,
    recommended: int,
    allowed_values: List[int],
    basis: str,
    formula: Dict[str, Any],
    explanation_ko: str,
) -> Dict[str, Any]:
    band = _candidate_window(int(recommended), allowed_values, radius=1)
    payload = {
        metric_key: int(recommended),  # fallback/backward compatibility: 서버 권장값
        f"recommended_{metric_key}": int(recommended),
        "server_recommended_target": int(recommended),
        "allowed_target_band": band,
        "candidate_values": band,
        "selection_mode": "server_recommended_target_band",
        "basis": basis,
        "formula": formula,
        "explanation_ko": explanation_ko,
        "is_official_guideline": False,
    }
    return payload


def _difficulty_weight(goal_direction: str, difficulty: str, metric: str) -> tuple[float, int]:
    """최근 평균에 곱할 비율과 추가 시작값을 반환한다.

    평균이 매우 낮은 사용자에게 2500보/80kcal 같은 고정 최소값을 바로 주지 않고,
    현재 평균에서 한 단계만 올리는 느낌의 숫자를 만든다.
    """

    goal_direction = str(goal_direction or "health_maintenance")
    difficulty = str(difficulty or "easy")

    if metric == "steps":
        if goal_direction == "weight_loss_support":
            return (0.65, 700) if difficulty == "easy" else (0.8, 1000)
        return (0.5, 500) if difficulty == "easy" else (0.65, 800)

    # active kcal
    if goal_direction == "weight_loss_support":
        return (0.75, 25) if difficulty == "easy" else (0.95, 35)
    return (0.6, 20) if difficulty == "easy" else (0.8, 30)


def calculate_step_target(
    *,
    avg_steps_7d: int,
    goal_direction: str,
    difficulty: str,
    difficulty_bias: str = "neutral",
) -> Dict[str, Any]:
    avg_steps_7d = max(0, _safe_int(avg_steps_7d))
    multiplier, add_on = _difficulty_weight(goal_direction, difficulty, "steps")

    if avg_steps_7d <= 0:
        raw_target = 1000 if difficulty == "easy" else 1500
    else:
        raw_target = avg_steps_7d * multiplier + add_on

    raw_target = _clamp(raw_target, min(STEP_TARGET_MASTER), max(STEP_TARGET_MASTER))
    selected = _round_up_to_allowed(raw_target, STEP_TARGET_MASTER)
    selected = _shift_allowed_value(selected, STEP_TARGET_MASTER, difficulty_bias)

    return _make_hybrid_target_payload(
        metric_key="target_steps",
        recommended=int(selected),
        allowed_values=STEP_TARGET_MASTER,
        basis="server_recommended_band_from_recent_7d_steps",
        formula={
            "avg_steps_7d": avg_steps_7d,
            "multiplier": multiplier,
            "add_on": add_on,
            "rounded_policy": "round_up_to_allowed_app_target",
            "difficulty": difficulty,
            "difficulty_bias": difficulty_bias,
            "goal_direction": goal_direction,
        },
        explanation_ko=(
            f"이번 주 7일 평균 {avg_steps_7d}보에서 사용자가 부담 없이 한 단계 올릴 수 있도록 "
            f"서버가 {int(selected)}보를 권장하고 주변 수치를 허용 밴드로 열었습니다."
            if avg_steps_7d > 0
            else f"최근 걸음 데이터가 부족해 서버가 {int(selected)}보를 권장하고 낮은 시작 밴드를 열었습니다."
        ),
    )


def calculate_kcal_target(
    *,
    avg_active_kcal_7d: int,
    goal_direction: str,
    difficulty: str,
    difficulty_bias: str = "neutral",
) -> Dict[str, Any]:
    avg_active_kcal_7d = max(0, _safe_int(avg_active_kcal_7d))
    multiplier, add_on = _difficulty_weight(goal_direction, difficulty, "kcal")

    if avg_active_kcal_7d <= 0:
        raw_target = 40 if difficulty == "easy" else 60
    else:
        raw_target = avg_active_kcal_7d * multiplier + add_on

    raw_target = _clamp(raw_target, min(KCAL_TARGET_MASTER), max(KCAL_TARGET_MASTER))
    selected = _round_up_to_allowed(raw_target, KCAL_TARGET_MASTER)
    selected = _shift_allowed_value(selected, KCAL_TARGET_MASTER, difficulty_bias)

    return _make_hybrid_target_payload(
        metric_key="target_kcal",
        recommended=int(selected),
        allowed_values=KCAL_TARGET_MASTER,
        basis="server_recommended_band_from_recent_7d_active_kcal",
        formula={
            "avg_active_kcal_7d": avg_active_kcal_7d,
            "multiplier": multiplier,
            "add_on": add_on,
            "rounded_policy": "round_up_to_allowed_app_target",
            "difficulty": difficulty,
            "difficulty_bias": difficulty_bias,
            "goal_direction": goal_direction,
        },
        explanation_ko=(
            f"이번 주 7일 평균 활동칼로리 {avg_active_kcal_7d}kcal에서 부담이 낮은 증가폭을 적용해 "
            f"서버가 {int(selected)}kcal를 권장하고 주변 수치를 허용 밴드로 열었습니다."
            if avg_active_kcal_7d > 0
            else f"최근 활동칼로리 데이터가 부족해 서버가 {int(selected)}kcal를 권장하고 낮은 시작 밴드를 열었습니다."
        ),
    )


def build_a_selected_target_policy(
    *,
    activity_summary: Dict[str, Any],
    goal_direction: str,
    difficulty: str,
    difficulty_bias: str = "neutral",
    previous_mission: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A1/A2 각각의 서버 결정 목표값을 만든다."""

    avg_steps = _safe_int((activity_summary or {}).get("avg_steps_7d"), 0)
    avg_kcal = _safe_int((activity_summary or {}).get("avg_active_kcal_7d"), 0)

    step_policy = calculate_step_target(
        avg_steps_7d=avg_steps,
        goal_direction=goal_direction,
        difficulty=difficulty,
        difficulty_bias=difficulty_bias,
    )
    kcal_policy = calculate_kcal_target(
        avg_active_kcal_7d=avg_kcal,
        goal_direction=goal_direction,
        difficulty=difficulty,
        difficulty_bias=difficulty_bias,
    )

    # 직전과 같은 타입을 다시 생성하는 마지막 retry 상황에서도 숫자만은 반복되지 않게 한 단계 조정한다.
    prev = previous_mission or {}
    prev_type = str(prev.get("mission_type") or prev.get("suggested_type") or "").strip()
    prev_params = prev.get("params") or {}

    if prev_type == "A1_STEP_TARGET":
        prev_steps = _safe_int(prev_params.get("target_steps"), 0)
        if prev_steps == step_policy["target_steps"]:
            step_policy["target_steps"] = _shift_allowed_value(
                int(step_policy["target_steps"]),
                STEP_TARGET_MASTER,
                "down" if difficulty_bias == "down" else "up",
            )
            step_policy["candidate_values"] = _candidate_window(step_policy["target_steps"], STEP_TARGET_MASTER)
            step_policy["allowed_target_band"] = step_policy["candidate_values"]
            step_policy["recommended_target_steps"] = int(step_policy["target_steps"])
            step_policy["server_recommended_target"] = int(step_policy["target_steps"])
            step_policy["basis"] += "+avoid_previous_same_value"

    if prev_type == "A2_ACTIVE_KCAL_TARGET":
        prev_kcal = _safe_int(prev_params.get("target_kcal"), 0)
        if prev_kcal == kcal_policy["target_kcal"]:
            kcal_policy["target_kcal"] = _shift_allowed_value(
                int(kcal_policy["target_kcal"]),
                KCAL_TARGET_MASTER,
                "down" if difficulty_bias == "down" else "up",
            )
            kcal_policy["candidate_values"] = _candidate_window(kcal_policy["target_kcal"], KCAL_TARGET_MASTER)
            kcal_policy["allowed_target_band"] = kcal_policy["candidate_values"]
            kcal_policy["recommended_target_kcal"] = int(kcal_policy["target_kcal"])
            kcal_policy["server_recommended_target"] = int(kcal_policy["target_kcal"])
            kcal_policy["basis"] += "+avoid_previous_same_value"

    return {
        "policy_version": A_TARGET_POLICY_VERSION,
        "selection_mode": "server_recommended_target_band",
        "A1_STEP_TARGET": step_policy,
        "A2_ACTIVE_KCAL_TARGET": kcal_policy,
        "note": "GPT는 server_recommended_target을 우선 참고하되 allowed_target_band 안에서만 수치를 선택할 수 있습니다.",
    }
