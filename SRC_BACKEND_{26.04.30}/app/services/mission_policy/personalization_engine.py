"""AI 미션 개인화 정책 엔진.

GPT가 자유롭게 판단하기 전에 FastAPI 서버가 먼저 다음 항목을 계산한다.
- 목표별 타입 우선순위
- A/B/C 슬롯별 target 후보
- 사용자 상태 기반 난이도(easy/normal)
- reason 생성에 사용할 근거 문장(reason_basis)

이 엔진의 출력은 GPT user prompt에 그대로 들어가며,
GPT는 이 정책 안에서 자연어 미션 문장과 reason을 만드는 역할만 맡는다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.mission_policy.goal_policy import POLICY_VERSION, get_goal_policy
from app.services.mission_policy.routine_catalog import (
    build_routine_candidates,
    summarize_routine_catalog_for_prompt,
)
from app.services.mission_policy.checkin_catalog import (
    build_checkin_candidates,
    summarize_checkin_catalog_for_prompt,
)
from app.services.mission_policy.numeric_target_policy import (
    STEP_TARGET_MASTER,
    KCAL_TARGET_MASTER,
    build_a_selected_target_policy,
)


ALLOWED_TYPES_BY_SLOT = {
    "A": ["A1_STEP_TARGET", "A2_ACTIVE_KCAL_TARGET"],
    "B": ["B1_TIMER_STRETCH", "B2_SLEEP_PREP", "B3_ROUTINE_CHECK"],
    "C": ["C1_HEALTH_CHECKIN"],
}

STRETCH_DURATION_MASTER = [5, 10, 15, 20, 25, 30]
SLEEP_PREP_DURATION_MASTER = [10, 15, 20, 25, 30]
CHECKIN_MIN_LENGTH_MASTER = [15, 20, 25]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _move_items_to_front(items: List[str], front_items: List[str]) -> List[str]:
    return _dedupe_preserve_order(front_items + [item for item in items if item not in front_items])


def _remove_items(items: List[str], remove_items: List[str]) -> List[str]:
    remove_set = {item for item in remove_items if item}
    return [item for item in items if item not in remove_set]


def _get_mission_type(mission: Optional[Dict[str, Any]]) -> str:
    if not mission:
        return ""
    return str(mission.get("mission_type") or mission.get("suggested_type") or "").strip()


def _get_slot_behavior(behavior_summary: Optional[Dict[str, Any]], slot_code: str) -> Dict[str, Any]:
    if not behavior_summary:
        return {}
    return (behavior_summary.get("slots") or {}).get(slot_code, {}) or {}


def _get_b3_routine_rotation(behavior_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not behavior_summary:
        return {}
    slot_b = _get_slot_behavior(behavior_summary, "B")
    rotation = slot_b.get("routine_rotation") or behavior_summary.get("b3_routine_rotation") or {}
    return rotation if isinstance(rotation, dict) else {}


def _shift_numeric_candidates(
    candidates: List[int],
    allowed_values: List[int],
    bias: str,
) -> List[int]:
    if not candidates or bias not in {"up", "down"}:
        return candidates

    step = 1 if bias == "up" else -1
    shifted: List[int] = []

    for value in candidates:
        if value in allowed_values:
            idx = allowed_values.index(value)
        else:
            idx = min(range(len(allowed_values)), key=lambda i: abs(allowed_values[i] - value))
        shifted_idx = max(0, min(len(allowed_values) - 1, idx + step))
        shifted.append(allowed_values[shifted_idx])

    return sorted(set(shifted), key=lambda item: allowed_values.index(item))


def _build_existing_types_by_slot(existing_missions: Optional[List[Dict[str, Any]]]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for mission in existing_missions or []:
        slot_code = str(mission.get("slot_code") or "").strip()
        mission_type = _get_mission_type(mission)
        if slot_code and mission_type:
            result.setdefault(slot_code, []).append(mission_type)
    return result


def _rotation_preference(slot_code: str, previous_type: str) -> Tuple[List[str], List[str], List[str]]:
    """직전 미션과 같은 타입 반복을 줄이기 위한 우선/비권장 타입 계산."""

    if not previous_type:
        return [], [], []

    if slot_code == "A":
        if previous_type == "A1_STEP_TARGET":
            return ["A2_ACTIVE_KCAL_TARGET"], ["A1_STEP_TARGET"], ["직전 걸음 수 미션과 반복되지 않도록 활동칼로리형을 우선합니다."]
        if previous_type == "A2_ACTIVE_KCAL_TARGET":
            return ["A1_STEP_TARGET"], ["A2_ACTIVE_KCAL_TARGET"], ["직전 활동칼로리 미션과 반복되지 않도록 걸음 수 미션을 우선합니다."]

    if slot_code == "B":
        if previous_type == "B1_TIMER_STRETCH":
            return ["B3_ROUTINE_CHECK", "B2_SLEEP_PREP"], ["B1_TIMER_STRETCH"], ["직전 스트레칭 미션과 반복되지 않도록 루틴형 또는 휴식형을 우선합니다."]
        if previous_type == "B2_SLEEP_PREP":
            return ["B3_ROUTINE_CHECK", "B1_TIMER_STRETCH"], ["B2_SLEEP_PREP"], ["직전 휴식 준비 미션과 반복되지 않도록 생활 루틴형을 우선합니다."]
        if previous_type == "B3_ROUTINE_CHECK":
            return ["B1_TIMER_STRETCH", "B2_SLEEP_PREP"], ["B3_ROUTINE_CHECK"], ["직전 루틴 체크 미션과 반복되지 않도록 다른 B타입을 우선합니다."]

    return [], [], []


def _build_slot_difficulty(
    *,
    slot_code: str,
    goal_direction: str,
    activity_summary: Dict[str, Any],
    comparison: Dict[str, Any],
    health_gap: Dict[str, Any],
    behavior_summary: Optional[Dict[str, Any]],
    retry_attempt: int,
) -> Tuple[str, List[str], str]:
    """사용자 상태와 행동 이력으로 easy/normal 난이도 계산."""

    avg_steps = _safe_int(activity_summary.get("avg_steps_7d"), 0)
    avg_kcal = _safe_int(activity_summary.get("avg_active_kcal_7d"), 0)
    avg_sleep = _safe_int(activity_summary.get("avg_sleep_minutes_7d"), 0)

    step_status = str(health_gap.get("step_status") or comparison.get("step_status") or "")
    activity_status = str(health_gap.get("activity_status") or comparison.get("activity_status") or "")
    sleep_status = str(health_gap.get("sleep_status") or "")
    data_confidence = str(health_gap.get("data_confidence") or comparison.get("data_confidence") or "low")

    slot_behavior = _get_slot_behavior(behavior_summary, slot_code)
    behavior_bias = str(slot_behavior.get("difficulty_bias") or "neutral")

    reasons: List[str] = []
    difficulty = "normal"

    if data_confidence == "low":
        difficulty = "easy"
        reasons.append("측정 데이터가 아직 충분하지 않아 가벼운 난이도로 시작합니다.")

    if retry_attempt >= 2:
        difficulty = "easy"
        reasons.append("재시도 상황에서는 검수 안정성을 위해 더 쉬운 후보를 우선합니다.")

    if behavior_bias == "down":
        difficulty = "easy"
        reasons.append("최근 새로고침 비율이 높아 부담이 낮은 난이도로 조정합니다.")
    elif behavior_bias == "up":
        reasons.append("최근 완료 흐름이 좋아 기본 난이도 후보를 유지합니다.")

    if slot_code == "A":
        if avg_steps <= 2500 or avg_kcal <= 80 or step_status == "below_average" or activity_status == "low":
            difficulty = "easy"
            reasons.append("최근 활동량이 낮은 편이라 A타입 목표 수치를 낮게 잡습니다.")
        elif goal_direction == "weight_loss_support" and avg_steps >= 4000 and avg_kcal >= 120 and behavior_bias != "down":
            difficulty = "normal"
            reasons.append("체중 감량 목표를 활동량 증가 방향으로 반영하되 무리하지 않는 기본 후보를 사용합니다.")

    elif slot_code == "B":
        if activity_status == "low" or (avg_sleep and avg_sleep < 420) or sleep_status == "short":
            difficulty = "easy"
            reasons.append("활동 흐름과 실천 부담을 고려해 짧고 반복하기 쉬운 B타입 후보를 우선합니다.")

    elif slot_code == "C":
        if data_confidence == "low":
            difficulty = "easy"
            reasons.append("사용자 상태 기록을 늘릴 수 있도록 짧은 기록형 후보를 우선합니다.")

    if difficulty == "normal" and not reasons:
        reasons.append("최근 데이터가 기본 범위에 있어 보통 난이도 후보를 사용합니다.")

    effective_bias = "neutral"
    if difficulty == "easy":
        effective_bias = "down"
    elif behavior_bias == "up":
        effective_bias = "up"

    return difficulty, _dedupe_preserve_order(reasons), effective_bias


def _base_step_candidates(avg_steps: int, goal_direction: str) -> List[int]:
    if avg_steps <= 0:
        return [2500, 3000, 3500]

    if goal_direction == "weight_loss_support":
        if avg_steps <= 2000:
            return [3000, 3500, 4000]
        if avg_steps <= 4000:
            return [3500, 4000, 4500]
        if avg_steps <= 6000:
            return [4500, 5000, 5500]
        if avg_steps <= 8000:
            return [5500, 6000, 7000]
        return [7000, 8000, 9000]

    if avg_steps <= 2000:
        return [2500, 3000, 3500]
    if avg_steps <= 4000:
        return [3000, 3500, 4000]
    if avg_steps <= 6000:
        return [4000, 4500, 5000]
    if avg_steps <= 8000:
        return [5000, 5500, 6000]
    return [6000, 7000, 8000]


def _base_kcal_candidates(avg_kcal: int, goal_direction: str) -> List[int]:
    if avg_kcal <= 0:
        return [80, 100, 120]

    if goal_direction == "weight_loss_support":
        if avg_kcal <= 80:
            return [100, 120, 150]
        if avg_kcal <= 140:
            return [120, 150, 180]
        if avg_kcal <= 200:
            return [150, 180, 220]
        if avg_kcal <= 280:
            return [180, 220, 250]
        return [220, 250, 300]

    if avg_kcal <= 80:
        return [80, 100, 120]
    if avg_kcal <= 140:
        return [100, 120, 150]
    if avg_kcal <= 200:
        return [120, 150, 180]
    if avg_kcal <= 280:
        return [150, 180, 220]
    return [180, 220, 250]


def _build_target_candidates_by_slot(
    *,
    slot_codes: List[str],
    goal_direction: str,
    activity_summary: Dict[str, Any],
    health_gap: Dict[str, Any],
    difficulty_by_slot: Dict[str, str],
    effective_bias_by_slot: Dict[str, str],
    previous_mission: Optional[Dict[str, Any]] = None,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    avg_steps = _safe_int(activity_summary.get("avg_steps_7d"), 0)
    avg_kcal = _safe_int(activity_summary.get("avg_active_kcal_7d"), 0)
    avg_sleep = _safe_int(activity_summary.get("avg_sleep_minutes_7d"), 0)

    targets: Dict[str, Dict[str, Any]] = {}

    if "A" in slot_codes:
        a_bias = effective_bias_by_slot.get("A", "neutral")
        a_difficulty = difficulty_by_slot.get("A", "easy")
        selected_target_policy = build_a_selected_target_policy(
            activity_summary=activity_summary,
            goal_direction=goal_direction,
            difficulty=a_difficulty,
            difficulty_bias=a_bias,
            previous_mission=previous_mission,
        )
        step_policy = selected_target_policy["A1_STEP_TARGET"]
        kcal_policy = selected_target_policy["A2_ACTIVE_KCAL_TARGET"]
        targets["A"] = {
            "difficulty": a_difficulty,
            "selection_mode": "server_recommended_target_band",
            "selected_targets": selected_target_policy,  # backward compatibility for existing UI/log consumers
            "recommended_targets": selected_target_policy,
            "step_target_candidates": list(step_policy.get("allowed_target_band") or step_policy.get("candidate_values") or [step_policy.get("target_steps")]),
            "kcal_target_candidates": list(kcal_policy.get("allowed_target_band") or kcal_policy.get("candidate_values") or [kcal_policy.get("target_kcal")]),
            "allowed_target_band_by_type": {
                "A1_STEP_TARGET": list(step_policy.get("allowed_target_band") or step_policy.get("candidate_values") or []),
                "A2_ACTIVE_KCAL_TARGET": list(kcal_policy.get("allowed_target_band") or kcal_policy.get("candidate_values") or []),
            },
            "server_recommended_target_steps": int(step_policy.get("recommended_target_steps") or step_policy.get("target_steps") or 0),
            "server_recommended_target_kcal": int(kcal_policy.get("recommended_target_kcal") or kcal_policy.get("target_kcal") or 0),
            "basis": "server_recommended_band_recent_7d_activity_goal_behavior_policy",
        }

    if "B" in slot_codes:
        b_bias = effective_bias_by_slot.get("B", "neutral")
        activity_status = str(health_gap.get("activity_status") or "")

        if activity_status == "low" or avg_kcal <= 150:
            stretch_candidates = [5, 10, 15]
        else:
            stretch_candidates = [10, 15, 20]

        if avg_sleep and avg_sleep < 360:
            sleep_candidates = [10, 15]
        elif avg_sleep and avg_sleep < 420:
            sleep_candidates = [15, 20]
        else:
            sleep_candidates = [15, 20, 25]

        stretch_candidates = _shift_numeric_candidates(stretch_candidates, STRETCH_DURATION_MASTER, b_bias)
        sleep_candidates = _shift_numeric_candidates(sleep_candidates, SLEEP_PREP_DURATION_MASTER, b_bias)

        repeat_candidates = [2, 3] if difficulty_by_slot.get("B") == "easy" else [3, 4]
        interval_candidates = [10, 15] if difficulty_by_slot.get("B") == "easy" else [5, 10, 15]
        repeat_candidates = _shift_numeric_candidates(repeat_candidates, [2, 3, 4, 5], b_bias)
        interval_candidates = _shift_numeric_candidates(interval_candidates, [5, 10, 15], b_bias)

        prev_params = (previous_mission or {}).get("params") or {}
        previous_routine_key = str(prev_params.get("routine_key") or "").strip()
        routine_rotation = _get_b3_routine_rotation(behavior_summary)
        recent_routine_keys = list(routine_rotation.get("recent_routine_keys") or [])
        blocked_routine_keys = list(routine_rotation.get("blocked_routine_keys") or [])

        routine_candidates = build_routine_candidates(
            difficulty=difficulty_by_slot.get("B", "easy"),
            goal_direction=goal_direction,
            activity_status=str(health_gap.get("activity_status") or "low"),
            sleep_status=str(health_gap.get("sleep_status") or "unknown"),
            data_confidence=str(health_gap.get("data_confidence") or "medium"),
            difficulty_bias=b_bias,
            previous_routine_key=previous_routine_key,
            recent_routine_keys=recent_routine_keys,
            blocked_routine_keys=blocked_routine_keys,
            limit=6,
        )

        targets["B"] = {
            "difficulty": difficulty_by_slot.get("B", "easy"),
            "stretch_duration_candidates": stretch_candidates,
            "sleep_prep_duration_candidates": sleep_candidates,
            "routine_candidates": routine_candidates,
            "routine_catalog": summarize_routine_catalog_for_prompt(),
            "routine_rotation": {
                "recent_routine_keys": recent_routine_keys,
                "blocked_routine_keys": blocked_routine_keys,
                "preferred_routine_keys": list(routine_rotation.get("preferred_routine_keys") or []),
                "rotation_rule": routine_rotation.get("rotation_rule") or "최근 B3 루틴과 다른 routine_key를 우선 사용합니다.",
            },
            "repeat_count_candidates": repeat_candidates,
            "interval_min_candidates": interval_candidates,
            "basis": "recent_7d_activity_rest_routine_and_goal_policy",
        }

    if "C" in slot_codes:
        c_bias = effective_bias_by_slot.get("C", "neutral")
        if difficulty_by_slot.get("C") == "easy":
            min_length_candidates = [15, 20]
        else:
            min_length_candidates = [15, 20, 25]
        min_length_candidates = _shift_numeric_candidates(min_length_candidates, CHECKIN_MIN_LENGTH_MASTER, c_bias)

        prev_params = (previous_mission or {}).get("params") or {}
        previous_checkin_key = str(prev_params.get("checkin_key") or "").strip()
        checkin_candidates = build_checkin_candidates(
            goal_direction=goal_direction,
            activity_status=str(health_gap.get("activity_status") or "unknown"),
            sleep_status=str(health_gap.get("sleep_status") or "unknown"),
            data_confidence=str(health_gap.get("data_confidence") or "medium"),
            difficulty=difficulty_by_slot.get("C", "easy"),
            difficulty_bias=c_bias,
            previous_checkin_key=previous_checkin_key,
            limit=5,
        )

        targets["C"] = {
            "difficulty": difficulty_by_slot.get("C", "easy"),
            "checkin_min_length_candidates": min_length_candidates,
            "checkin_candidates": checkin_candidates,
            "checkin_catalog": summarize_checkin_catalog_for_prompt(),
            "basis": "data_confidence_goal_policy_and_checkin_rotation",
        }

    return targets


def _build_type_priority_by_slot(
    *,
    mode: str,
    slot_codes: List[str],
    goal_policy: Dict[str, Any],
    activity_summary: Dict[str, Any],
    health_gap: Dict[str, Any],
    previous_mission: Optional[Dict[str, Any]],
    behavior_summary: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]], List[str]]:
    base_priority = goal_policy.get("slot_type_priority") or {}
    priority_by_slot: Dict[str, List[str]] = {}
    discouraged_by_slot: Dict[str, List[str]] = {}
    notes: List[str] = []

    previous_type = _get_mission_type(previous_mission)
    avg_kcal = _safe_int(activity_summary.get("avg_active_kcal_7d"), 0)
    avg_sleep = _safe_int(activity_summary.get("avg_sleep_minutes_7d"), 0)
    goal_direction = str(goal_policy.get("goal_direction") or "health_maintenance")

    for slot_code in slot_codes:
        allowed = ALLOWED_TYPES_BY_SLOT.get(slot_code, [])
        priority = [item for item in list(base_priority.get(slot_code) or allowed) if item in allowed]
        discouraged: List[str] = []

        if slot_code == "A":
            if goal_direction == "weight_loss_support" and avg_kcal > 180:
                priority = _move_items_to_front(priority, ["A1_STEP_TARGET", "A2_ACTIVE_KCAL_TARGET"])
                notes.append("체중 감량 목표와 활동 흐름을 반영해 A1/A2 후보를 균형 있게 검토합니다.")
            elif avg_kcal <= 180:
                priority = _move_items_to_front(priority, ["A2_ACTIVE_KCAL_TARGET", "A1_STEP_TARGET"])
                notes.append("최근 활동칼로리 흐름을 반영해 A2 활동칼로리형을 우선 검토합니다.")

        if slot_code == "B":
            if avg_sleep and avg_sleep < 420:
                priority = _move_items_to_front(priority, ["B2_SLEEP_PREP", "B3_ROUTINE_CHECK", "B1_TIMER_STRETCH"])
                notes.append("최근 수면 시간이 짧아 B2 휴식 준비형을 우선 후보에 올립니다.")
            elif avg_sleep == 0:
                priority = _move_items_to_front(priority, ["B3_ROUTINE_CHECK", "B1_TIMER_STRETCH", "B2_SLEEP_PREP"])
                notes.append("별도 수면 측정값이 없어도 바로 수행 가능한 B3 생활 루틴형을 우선 후보에 올립니다.")
            else:
                priority = _move_items_to_front(priority, ["B3_ROUTINE_CHECK", "B1_TIMER_STRETCH", "B2_SLEEP_PREP"])
                notes.append("B 슬롯은 같은 타이머 미션 반복보다 생활 루틴형을 우선 검토합니다.")

        if len(slot_codes) == 1 and previous_type:
            rotation_preferred, rotation_discouraged, rotation_notes = _rotation_preference(slot_code, previous_type)
            priority = _move_items_to_front(priority, [item for item in rotation_preferred if item in allowed])
            discouraged.extend([item for item in rotation_discouraged if item in allowed])
            notes.extend(rotation_notes)

        slot_behavior = _get_slot_behavior(behavior_summary, slot_code)
        behavior_preferred = [item for item in list(slot_behavior.get("preferred_types") or []) if item in allowed]
        behavior_discouraged = [item for item in list(slot_behavior.get("discouraged_types") or []) if item in allowed]
        # C 슬롯은 허용 타입이 C1 하나뿐이다.
        # 새로고침이 잦다는 이유로 자기 자신을 discouraged로 넣으면
        # GPT가 선택할 수 있는 합법 타입이 사라져 fallback이 급증한다.
        if len(allowed) == 1:
            behavior_discouraged = []
        confidence = str(slot_behavior.get("confidence") or (behavior_summary or {}).get("confidence") or "low")

        if behavior_preferred:
            if confidence in {"medium", "high"} and not (len(slot_codes) == 1 and previous_type):
                priority = _move_items_to_front(priority, behavior_preferred)
            else:
                priority = _dedupe_preserve_order(priority + behavior_preferred)
            notes.append(f"최근 {slot_code} 슬롯에서 완료 흐름이 좋은 타입을 우선순위에 반영합니다.")

        if behavior_discouraged:
            discouraged.extend(behavior_discouraged)
            notes.append(f"최근 {slot_code} 슬롯에서 새로고침이 잦은 타입은 비중을 낮춥니다.")

        discouraged = _dedupe_preserve_order(discouraged)
        priority = _dedupe_preserve_order([item for item in priority if item in allowed])
        priority = _remove_items(priority, discouraged) + [item for item in priority if item in discouraged]
        priority = _dedupe_preserve_order(priority)

        if not priority:
            priority = allowed

        priority_by_slot[slot_code] = priority
        if discouraged:
            discouraged_by_slot[slot_code] = discouraged

    return priority_by_slot, discouraged_by_slot, _dedupe_preserve_order(notes)


def _build_reason_basis_by_slot(
    *,
    slot_codes: List[str],
    goal_policy: Dict[str, Any],
    health_gap: Dict[str, Any],
    activity_summary: Dict[str, Any],
    difficulty_by_slot: Dict[str, str],
    type_priority_by_slot: Dict[str, List[str]],
    difficulty_reasons_by_slot: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    avg_steps = _safe_int(activity_summary.get("avg_steps_7d"), 0)
    avg_kcal = _safe_int(activity_summary.get("avg_active_kcal_7d"), 0)
    avg_sleep = _safe_int(activity_summary.get("avg_sleep_minutes_7d"), 0)
    goal_direction = str(goal_policy.get("goal_direction") or "health_maintenance")

    common: List[str] = list(goal_policy.get("reason_basis") or [])
    data_confidence = str(health_gap.get("data_confidence") or "low")
    if data_confidence == "low":
        common.append("최근 데이터가 부족하면 구체적인 위험 판단 대신 가볍게 시작할 수 있다는 표현을 사용합니다.")

    if avg_steps > 0:
        common.append(f"이번 주 7일 평균 걸음 수 {avg_steps}보 흐름을 참고합니다.")
    if avg_kcal > 0:
        common.append(f"이번 주 7일 평균 활동칼로리 {avg_kcal}kcal 흐름을 참고합니다.")
    if avg_sleep > 0:
        common.append(f"이번 주 7일 평균 수면 {avg_sleep}분 흐름을 참고합니다.")

    result: Dict[str, List[str]] = {}
    for slot_code in slot_codes:
        slot_basis = list(common)
        slot_basis.extend(difficulty_reasons_by_slot.get(slot_code) or [])

        if slot_code == "A":
            slot_basis.append("A타입 숫자 목표는 서버가 이번 주 7일 평균과 행동 이력을 기준으로 권장값과 허용 밴드를 계산합니다.")
            slot_basis.append("A타입 reason은 GPT가 허용 밴드 안에서 선택한 수치가 왜 현재 사용자에게 부담이 낮은 한 단계 목표인지 설명합니다.")
            if goal_direction == "weight_loss_support":
                slot_basis.append("A타입 reason은 체중 수치 압박보다 활동량을 자연스럽게 늘리는 방향으로 작성합니다.")
            else:
                slot_basis.append("A타입 reason은 꾸준한 움직임 유지와 실천 가능성을 중심으로 작성합니다.")
        elif slot_code == "B":
            slot_basis.append("B타입 reason은 생활 루틴, 회복, 습관 형성을 중심으로 작성합니다.")
            if "B3_ROUTINE_CHECK" in type_priority_by_slot.get("B", [])[:2]:
                slot_basis.append("B3 루틴형을 선택할 경우 routine_key 후보 안에서 물 마시기만 반복하지 말고 루틴명과 반복 조건을 설명합니다.")
                slot_basis.append("B3 routine_rotation.blocked_routine_keys가 있으면 최근 나온 루틴이므로 다른 routine_key를 우선 사용합니다.")
        elif slot_code == "C":
            slot_basis.append("C타입 reason은 컨디션 기록과 생활 패턴 점검을 중심으로 작성합니다.")

        slot_basis.append(f"{slot_code} 슬롯 난이도는 {difficulty_by_slot.get(slot_code, 'easy')} 기준입니다.")
        result[slot_code] = _dedupe_preserve_order(slot_basis)

    return result


def _flatten_target_recommendation_context(targets_by_slot: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """기존 GPT prompt key와 호환되는 납작한 target_recommendation_context 생성."""

    a = targets_by_slot.get("A") or {}
    b = targets_by_slot.get("B") or {}
    c = targets_by_slot.get("C") or {}
    return {
        "step_target_candidates": a.get("step_target_candidates", [1000, 1500, 2000]),
        "kcal_target_candidates": a.get("kcal_target_candidates", [40, 60, 80]),
        "selected_a_targets": a.get("selected_targets", {}),
        "recommended_a_targets": a.get("recommended_targets", a.get("selected_targets", {})),
        "server_recommended_target_steps": a.get("server_recommended_target_steps"),
        "server_recommended_target_kcal": a.get("server_recommended_target_kcal"),
        "allowed_a_target_band_by_type": a.get("allowed_target_band_by_type", {}),
        "stretch_duration_candidates": b.get("stretch_duration_candidates", [5, 10, 15]),
        "sleep_prep_duration_candidates": b.get("sleep_prep_duration_candidates", [10, 15, 20]),
        "routine_candidates": b.get("routine_candidates", [
            {"routine_name": "물 마시기", "repeat_count": 3, "interval_min": 10},
            {"routine_name": "가볍게 일어나기", "repeat_count": 3, "interval_min": 15},
        ]),
        "checkin_min_length_candidates": c.get("checkin_min_length_candidates", [15, 20, 25]),
    }


def build_personalization_policy(
    *,
    mode: str,
    slot_codes: List[str],
    user_profile: Dict[str, Any],
    activity_summary: Dict[str, Any],
    comparison: Dict[str, Any],
    health_gap: Dict[str, Any],
    existing_missions: Optional[List[Dict[str, Any]]] = None,
    previous_mission: Optional[Dict[str, Any]] = None,
    retry_attempt: int = 1,
    behavior_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """GPT 미션 생성 전에 사용할 최종 개인화 정책 payload를 만든다."""

    slot_codes = [slot for slot in slot_codes if slot in ALLOWED_TYPES_BY_SLOT]
    activity_summary = activity_summary or {}
    comparison = comparison or {}
    health_gap = health_gap or {}

    goal_policy = get_goal_policy(user_profile, health_gap)
    goal_direction = str(goal_policy.get("goal_direction") or "health_maintenance")

    difficulty_by_slot: Dict[str, str] = {}
    difficulty_reasons_by_slot: Dict[str, List[str]] = {}
    effective_bias_by_slot: Dict[str, str] = {}

    for slot_code in slot_codes:
        difficulty, difficulty_reasons, effective_bias = _build_slot_difficulty(
            slot_code=slot_code,
            goal_direction=goal_direction,
            activity_summary=activity_summary,
            comparison=comparison,
            health_gap=health_gap,
            behavior_summary=behavior_summary,
            retry_attempt=retry_attempt,
        )
        difficulty_by_slot[slot_code] = difficulty
        difficulty_reasons_by_slot[slot_code] = difficulty_reasons
        effective_bias_by_slot[slot_code] = effective_bias

    type_priority_by_slot, discouraged_types_by_slot, type_notes = _build_type_priority_by_slot(
        mode=mode,
        slot_codes=slot_codes,
        goal_policy=goal_policy,
        activity_summary=activity_summary,
        health_gap=health_gap,
        previous_mission=previous_mission,
        behavior_summary=behavior_summary,
    )

    target_candidates_by_slot = _build_target_candidates_by_slot(
        slot_codes=slot_codes,
        goal_direction=goal_direction,
        activity_summary=activity_summary,
        health_gap=health_gap,
        difficulty_by_slot=difficulty_by_slot,
        effective_bias_by_slot=effective_bias_by_slot,
        previous_mission=previous_mission,
        behavior_summary=behavior_summary,
    )

    reason_basis_by_slot = _build_reason_basis_by_slot(
        slot_codes=slot_codes,
        goal_policy=goal_policy,
        health_gap=health_gap,
        activity_summary=activity_summary,
        difficulty_by_slot=difficulty_by_slot,
        type_priority_by_slot=type_priority_by_slot,
        difficulty_reasons_by_slot=difficulty_reasons_by_slot,
    )

    reason_basis: List[str] = []
    for slot_code in slot_codes:
        reason_basis.extend(reason_basis_by_slot.get(slot_code) or [])
    reason_basis = _dedupe_preserve_order(reason_basis)

    existing_types_by_slot = _build_existing_types_by_slot(existing_missions)
    target_recommendation_context = _flatten_target_recommendation_context(target_candidates_by_slot)

    return {
        "policy_version": POLICY_VERSION,
        "source": "server_personalization_engine_v1",
        "mode": mode,
        "slot_codes": slot_codes,
        "goal_policy": goal_policy,
        "difficulty_by_slot": difficulty_by_slot,
        "effective_bias_by_slot": effective_bias_by_slot,
        "type_priority_by_slot": type_priority_by_slot,
        "discouraged_types_by_slot": discouraged_types_by_slot,
        "target_candidates_by_slot": target_candidates_by_slot,
        "reason_basis_by_slot": reason_basis_by_slot,
        "reason_basis": reason_basis,
        "existing_types_by_slot": existing_types_by_slot,
        "previous_mission_type": _get_mission_type(previous_mission),
        "routine_catalog": summarize_routine_catalog_for_prompt(),
        "checkin_catalog": summarize_checkin_catalog_for_prompt(),
        "notes": type_notes,
        "type_preference_context": {
            "preferred_types_by_slot": type_priority_by_slot,
            "discouraged_types_by_slot": discouraged_types_by_slot,
            "existing_types_by_slot": existing_types_by_slot,
            "notes": type_notes,
            "source": "personalization_engine",
        },
        "target_recommendation_context": {
            **target_recommendation_context,
            "source": "personalization_engine",
            "difficulty_by_slot": difficulty_by_slot,
            "target_candidates_by_slot": target_candidates_by_slot,
        },
    }
