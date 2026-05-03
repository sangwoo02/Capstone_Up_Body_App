# app/services/gpt_service.py

import json
import re
from typing import Any, Dict, List, Optional

import openai

from app.core.config import settings


ALLOWED_TYPES_BY_SLOT = {
    "A": ["A1_STEP_TARGET", "A2_ACTIVE_KCAL_TARGET"],
    "B": ["B1_TIMER_STRETCH", "B2_SLEEP_PREP", "B3_ROUTINE_CHECK"],
    "C": ["C1_HEALTH_CHECKIN"],
}

BEHAVIOR_HISTORY_WINDOW = 12
STEP_TARGET_MASTER = [2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 7000, 8000, 9000]
KCAL_TARGET_MASTER = [80, 100, 120, 150, 180, 220, 250, 300]
STRETCH_DURATION_MASTER = [5, 10, 15, 20, 25, 30]
SLEEP_PREP_DURATION_MASTER = [10, 15, 20, 25, 30]
CHECKIN_MIN_LENGTH_MASTER = [15, 20, 25]


class GPTMissionFormatError(ValueError):
    """
    GPT 응답 파싱/형식 오류 전용 예외.
    missions.py에서 raw_response_text를 로그 테이블에 저장하기 위해 사용한다.
    """

    def __init__(self, message: str, raw_response_text: Optional[str] = None):
        super().__init__(message)
        self.raw_response_text = raw_response_text


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _get_behavior_slot_summary(
    behavior_summary: Optional[Dict[str, Any]],
    slot_code: str,
) -> Dict[str, Any]:
    if not behavior_summary:
        return {}
    return (behavior_summary.get("slots") or {}).get(slot_code, {}) or {}


def shift_numeric_candidates_by_bias(
    candidates: List[int],
    allowed_values: List[int],
    difficulty_bias: str,
) -> List[int]:
    if not candidates:
        return candidates

    if difficulty_bias not in {"up", "down"}:
        return candidates

    shifted: List[int] = []
    step = 1 if difficulty_bias == "up" else -1

    for value in candidates:
        if value in allowed_values:
            idx = allowed_values.index(value)
        else:
            idx = min(range(len(allowed_values)), key=lambda i: abs(allowed_values[i] - value))
        next_idx = max(0, min(len(allowed_values) - 1, idx + step))
        shifted.append(allowed_values[next_idx])

    return sorted(set(shifted), key=lambda value: allowed_values.index(value))


def adjust_routine_candidates_by_bias(
    candidates: List[Dict[str, Any]],
    difficulty_bias: str,
) -> List[Dict[str, Any]]:
    if difficulty_bias not in {"up", "down"}:
        return candidates

    adjusted: List[Dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for candidate in candidates:
        routine_name = str(candidate.get("routine_name") or "물 마시기").strip() or "물 마시기"
        repeat_count = int(candidate.get("repeat_count", 3) or 3)
        interval_min = int(candidate.get("interval_min", 10) or 10)

        if difficulty_bias == "up":
            repeat_count = min(repeat_count + 1, 5)
            interval_min = max(interval_min - 5, 5)
        else:
            repeat_count = max(repeat_count - 1, 2)
            interval_min = min(interval_min + 5, 15)

        normalized = (routine_name, repeat_count, interval_min)
        if normalized in seen:
            continue
        seen.add(normalized)
        adjusted.append(
            {
                "routine_name": routine_name,
                "repeat_count": repeat_count,
                "interval_min": interval_min,
            }
        )

    return adjusted or candidates


def build_behavior_adaptation_summary_from_history(
    resolved_history: Optional[List[Dict[str, Any]]],
    *,
    history_window_size: int = BEHAVIOR_HISTORY_WINDOW,
) -> Dict[str, Any]:
    history = list(resolved_history or [])[: max(history_window_size, 1)]
    slots: Dict[str, Dict[str, Any]] = {}

    for slot_code, allowed_types in ALLOWED_TYPES_BY_SLOT.items():
        slot_items = [
            mission
            for mission in history
            if str(mission.get("slot_code") or "").strip() == slot_code
            and str(mission.get("status") or "").strip() in {"completed", "refreshed"}
        ]

        type_metrics: Dict[str, Dict[str, Any]] = {}
        preferred_candidates: List[tuple[str, float]] = []
        discouraged_candidates: List[tuple[str, float]] = []

        slot_generated_count = len(slot_items)
        slot_started_count = sum(1 for mission in slot_items if mission.get("started_at"))
        slot_completed_count = sum(1 for mission in slot_items if mission.get("status") == "completed")
        slot_refreshed_count = sum(1 for mission in slot_items if mission.get("status") == "refreshed")
        slot_completion_rate = _safe_ratio(slot_completed_count, slot_generated_count)
        slot_refresh_rate = _safe_ratio(slot_refreshed_count, slot_generated_count)
        has_enough_data = slot_generated_count >= 3

        for mission_type in allowed_types:
            typed_items = [
                mission
                for mission in slot_items
                if str(mission.get("mission_type") or "").strip() == mission_type
            ]
            generated_count = len(typed_items)
            started_count = sum(1 for mission in typed_items if mission.get("started_at"))
            completed_count = sum(1 for mission in typed_items if mission.get("status") == "completed")
            refreshed_count = sum(1 for mission in typed_items if mission.get("status") == "refreshed")
            completion_rate = _safe_ratio(completed_count, generated_count)
            refresh_rate = _safe_ratio(refreshed_count, generated_count)

            type_metrics[mission_type] = {
                "generated_count": generated_count,
                "started_count": started_count,
                "completed_count": completed_count,
                "refreshed_count": refreshed_count,
                "completion_rate": completion_rate,
                "refresh_rate": refresh_rate,
            }

            if generated_count >= 2 and completed_count >= 2 and completion_rate >= 0.67:
                preferred_candidates.append((mission_type, completed_count * 2 + completion_rate))

            if generated_count >= 2 and refreshed_count >= 2 and refresh_rate >= 0.5:
                discouraged_candidates.append((mission_type, refreshed_count * 2 + refresh_rate))

        preferred_types = [
            mission_type
            for mission_type, _ in sorted(preferred_candidates, key=lambda item: (-item[1], item[0]))
        ]
        discouraged_types = [
            mission_type
            for mission_type, _ in sorted(discouraged_candidates, key=lambda item: (-item[1], item[0]))
        ]

        overlap = set(preferred_types) & set(discouraged_types)
        if overlap:
            cleaned_discouraged: List[str] = []
            for mission_type in discouraged_types:
                if (
                    mission_type in overlap
                    and type_metrics[mission_type]["completion_rate"] >= type_metrics[mission_type]["refresh_rate"]
                ):
                    continue
                cleaned_discouraged.append(mission_type)
            discouraged_types = cleaned_discouraged

        preferred_types = _dedupe_preserve_order(preferred_types)
        discouraged_types = _dedupe_preserve_order(
            [
                mission_type
                for mission_type in discouraged_types
                if mission_type not in preferred_types
            ]
        )

        if not has_enough_data:
            difficulty_bias = "neutral"
        elif slot_completion_rate >= 0.72 and slot_refresh_rate <= 0.28:
            difficulty_bias = "up"
        elif slot_refresh_rate >= 0.5 or slot_completion_rate <= 0.4:
            difficulty_bias = "down"
        else:
            difficulty_bias = "neutral"

        notes: List[str] = []
        if preferred_types:
            notes.append(f"최근 {slot_code} 슬롯에서 완료율이 높은 타입: {', '.join(preferred_types)}")
        if discouraged_types:
            notes.append(f"최근 {slot_code} 슬롯에서 새로고침 비율이 높은 타입: {', '.join(discouraged_types)}")
        if difficulty_bias == "up":
            notes.append(f"최근 {slot_code} 슬롯은 비교적 안정적으로 완료되어 난이도를 한 단계 높여도 됩니다.")
        elif difficulty_bias == "down":
            notes.append(f"최근 {slot_code} 슬롯은 새로고침 비율이 높아 난이도를 한 단계 낮추는 편이 좋습니다.")
        elif not has_enough_data:
            notes.append(f"최근 {slot_code} 슬롯 해결 이력이 부족해 난이도는 중립으로 유지합니다.")

        slots[slot_code] = {
            "generated_count": slot_generated_count,
            "started_count": slot_started_count,
            "completed_count": slot_completed_count,
            "refreshed_count": slot_refreshed_count,
            "completion_rate": slot_completion_rate,
            "refresh_rate": slot_refresh_rate,
            "preferred_types": preferred_types,
            "discouraged_types": discouraged_types,
            "difficulty_bias": difficulty_bias,
            "has_enough_data": has_enough_data,
            "types": type_metrics,
            "notes": notes,
        }

    return {
        "history_window_size": max(history_window_size, 1),
        "resolved_count": len(history),
        "slots": slots,
    }


class GPTService:
    @staticmethod
    def _extract_json_payload(raw_text: Any) -> Any:
        """
        GPT 응답에서 JSON payload만 안전하게 추출한다.

        허용:
        - dict/list 객체
        - 순수 JSON 문자열
        - ```json ... ``` 코드블록
        - 앞뒤 설명이 붙은 JSON
        """
        if isinstance(raw_text, (dict, list)):
            return raw_text

        if raw_text is None:
            raise GPTMissionFormatError("GPT 응답이 비어 있습니다.", raw_response_text=None)

        text = str(raw_text).strip()

        if not text:
            raise GPTMissionFormatError("GPT 응답이 비어 있습니다.", raw_response_text=text)

        # ```json ... ``` 또는 ``` ... ``` 제거
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()

        # 1차: 그대로 JSON 파싱
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2차: 본문 중 JSON 객체/배열만 추출
        object_start = text.find("{")
        array_start = text.find("[")

        candidates = [idx for idx in [object_start, array_start] if idx != -1]
        if not candidates:
            raise GPTMissionFormatError(
                f"GPT 응답에서 JSON 시작 지점을 찾지 못했습니다: {text[:200]}",
                raw_response_text=text,
            )

        start = min(candidates)

        object_end = text.rfind("}")
        array_end = text.rfind("]")

        end = max(object_end, array_end)
        if end == -1 or end <= start:
            raise GPTMissionFormatError(
                f"GPT 응답에서 JSON 종료 지점을 찾지 못했습니다: {text[:200]}",
                raw_response_text=text,
            )

        json_text = text[start:end + 1]

        try:
            return json.loads(json_text)
        except json.JSONDecodeError as e:
            raise GPTMissionFormatError(
                f"GPT 응답 JSON 파싱 실패: {str(e)}",
                raw_response_text=text,
            )

    @staticmethod
    def _normalize_missions_payload(payload: Any, mission_count: int) -> List[Dict[str, Any]]:
        """
        GPT 응답을 missions 리스트로 통일한다.

        허용:
        1) {"missions": [...]}
        2) [...]
        3) {"mission": {...}}
        4) {"slot_code": "...", "title": "...", ...}
        5) {"data": {"missions": [...]}}
        6) {"result": {"missions": [...]}}
        """
        missions = None

        if isinstance(payload, list):
            missions = payload

        elif isinstance(payload, dict):
            if isinstance(payload.get("missions"), list):
                missions = payload["missions"]

            elif isinstance(payload.get("mission"), dict):
                missions = [payload["mission"]]

            elif isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("missions"), list):
                missions = payload["data"]["missions"]

            elif isinstance(payload.get("result"), dict) and isinstance(payload["result"].get("missions"), list):
                missions = payload["result"]["missions"]

            elif all(
                key in payload
                for key in ["slot_code", "title", "description", "suggested_type", "params"]
            ):
                missions = [payload]

        if not isinstance(missions, list):
            keys = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
            raise GPTMissionFormatError(
                f"GPT 응답 형식이 올바르지 않습니다. missions 리스트를 만들 수 없습니다. payload_keys={keys}"
            )

        missions = [mission for mission in missions if isinstance(mission, dict)]

        if len(missions) != mission_count:
            raise GPTMissionFormatError(
                f"GPT 미션 개수가 요청과 다릅니다. expected={mission_count}, actual={len(missions)}"
            )

        return missions

    @staticmethod
    def _extract_mission_type(mission: Optional[Dict[str, Any]]) -> Optional[str]:
        if not mission:
            return None

        mission_type = str(
            mission.get("mission_type")
            or mission.get("suggested_type")
            or ""
        ).strip()

        return mission_type or None

    @staticmethod
    def _build_type_preference_context(
        *,
        mode: str,
        slot_codes: List[str],
        activity_summary: Dict[str, Any],
        existing_missions: Optional[List[Dict[str, Any]]] = None,
        previous_mission: Optional[Dict[str, Any]] = None,
        retry_attempt: int = 1,
        behavior_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        preferred_types_by_slot: Dict[str, List[str]] = {}
        discouraged_types_by_slot: Dict[str, List[str]] = {}
        notes: List[str] = []

        prev_type = GPTService._extract_mission_type(previous_mission)

        existing_types_by_slot: Dict[str, List[str]] = {}
        for mission in existing_missions or []:
            slot = str(mission.get("slot_code") or "").strip()
            m_type = GPTService._extract_mission_type(mission)
            if slot and m_type:
                existing_types_by_slot.setdefault(slot, []).append(m_type)

        avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
        avg_sleep_minutes_7d = int(activity_summary.get("avg_sleep_minutes_7d", 0) or 0)

        if mode == "initial":
            if "A" in slot_codes:
                if avg_active_kcal_7d <= 180:
                    preferred_types_by_slot["A"] = [
                        "A2_ACTIVE_KCAL_TARGET",
                        "A1_STEP_TARGET",
                    ]
                    notes.append(
                        "초기 A 슬롯은 최근 활동칼로리가 낮거나 보통이면 A2_ACTIVE_KCAL_TARGET을 우선 검토하세요."
                    )
                else:
                    preferred_types_by_slot["A"] = [
                        "A1_STEP_TARGET",
                        "A2_ACTIVE_KCAL_TARGET",
                    ]

            if "B" in slot_codes:
                if avg_sleep_minutes_7d == 0:
                    preferred_types_by_slot["B"] = [
                        "B3_ROUTINE_CHECK",
                        "B1_TIMER_STRETCH",
                        "B2_SLEEP_PREP",
                    ]
                    notes.append(
                        "초기 B 슬롯은 수면 데이터가 없으면 B3_ROUTINE_CHECK를 먼저 검토하세요."
                    )
                elif avg_sleep_minutes_7d < 420:
                    preferred_types_by_slot["B"] = [
                        "B2_SLEEP_PREP",
                        "B3_ROUTINE_CHECK",
                        "B1_TIMER_STRETCH",
                    ]
                    notes.append(
                        "초기 B 슬롯은 최근 수면 시간이 부족하면 B2_SLEEP_PREP을 우선 검토하세요."
                    )
                else:
                    preferred_types_by_slot["B"] = [
                        "B3_ROUTINE_CHECK",
                        "B1_TIMER_STRETCH",
                        "B2_SLEEP_PREP",
                    ]
                    notes.append(
                        "초기 B 슬롯은 B1만 반복하지 말고 B3_ROUTINE_CHECK도 적극 사용하세요."
                    )

        if len(slot_codes) == 1 and prev_type:
            slot_code = slot_codes[0]

            if slot_code == "A":
                if prev_type == "A1_STEP_TARGET":
                    preferred_types_by_slot["A"] = ["A2_ACTIVE_KCAL_TARGET"]
                    discouraged_types_by_slot["A"] = ["A1_STEP_TARGET"]
                    notes.append("A 슬롯 재생성에서는 직전이 A1이면 이번에는 A2를 우선 생성하세요.")
                elif prev_type == "A2_ACTIVE_KCAL_TARGET":
                    preferred_types_by_slot["A"] = ["A1_STEP_TARGET"]
                    discouraged_types_by_slot["A"] = ["A2_ACTIVE_KCAL_TARGET"]
                    notes.append("A 슬롯 재생성에서는 직전이 A2이면 이번에는 A1을 우선 생성하세요.")

            elif slot_code == "B":
                if prev_type == "B1_TIMER_STRETCH":
                    preferred_types_by_slot["B"] = ["B2_SLEEP_PREP", "B3_ROUTINE_CHECK"]
                    discouraged_types_by_slot["B"] = ["B1_TIMER_STRETCH"]
                    notes.append("B 슬롯 재생성에서는 직전이 B1이면 이번에는 B2 또는 B3를 우선 생성하세요.")
                elif prev_type == "B2_SLEEP_PREP":
                    preferred_types_by_slot["B"] = ["B3_ROUTINE_CHECK", "B1_TIMER_STRETCH"]
                    discouraged_types_by_slot["B"] = ["B2_SLEEP_PREP"]
                    notes.append("B 슬롯 재생성에서는 직전이 B2이면 이번에는 B3 또는 B1을 우선 생성하세요.")
                elif prev_type == "B3_ROUTINE_CHECK":
                    preferred_types_by_slot["B"] = ["B2_SLEEP_PREP", "B1_TIMER_STRETCH"]
                    discouraged_types_by_slot["B"] = ["B3_ROUTINE_CHECK"]
                    notes.append("B 슬롯 재생성에서는 직전이 B3이면 이번에는 B2 또는 B1을 우선 생성하세요.")

        for slot_code in slot_codes:
            slot_behavior = _get_behavior_slot_summary(behavior_summary, slot_code)
            if not slot_behavior:
                continue

            behavior_preferred = list(slot_behavior.get("preferred_types") or [])
            behavior_discouraged = list(slot_behavior.get("discouraged_types") or [])
            difficulty_bias = str(slot_behavior.get("difficulty_bias") or "neutral")

            base_preferred = preferred_types_by_slot.get(slot_code, [])
            if len(slot_codes) == 1 and prev_type:
                merged_preferred = _dedupe_preserve_order(base_preferred + behavior_preferred)
            else:
                merged_preferred = _dedupe_preserve_order(behavior_preferred + base_preferred)
            if merged_preferred:
                preferred_types_by_slot[slot_code] = merged_preferred

            merged_discouraged = _dedupe_preserve_order(
                discouraged_types_by_slot.get(slot_code, []) + behavior_discouraged
            )
            if merged_discouraged:
                discouraged_types_by_slot[slot_code] = [
                    mission_type
                    for mission_type in merged_discouraged
                    if mission_type not in preferred_types_by_slot.get(slot_code, [])
                ]

            if behavior_preferred:
                notes.append(
                    f"최근 {slot_code} 슬롯에서 완료율이 높은 타입 {', '.join(behavior_preferred)} 는 가중치를 높여 참고하세요."
                )
            if behavior_discouraged:
                notes.append(
                    f"최근 {slot_code} 슬롯에서 새로고침이 잦은 타입 {', '.join(behavior_discouraged)} 는 가능한 피하세요."
                )
            if difficulty_bias == "up":
                notes.append(f"최근 {slot_code} 슬롯은 안정적으로 완료되어 난이도를 한 단계 높여도 됩니다.")
            elif difficulty_bias == "down":
                notes.append(f"최근 {slot_code} 슬롯은 새로고침 비율이 높아 난이도를 한 단계 낮추세요.")

        if retry_attempt >= 2:
            notes.append(
                "retry_attempt가 2 이상이면 직전 미션과 같은 타입을 피하고, preferred_types_by_slot을 더 강하게 따르세요."
            )

        return {
            "preferred_types_by_slot": preferred_types_by_slot,
            "discouraged_types_by_slot": discouraged_types_by_slot,
            "existing_types_by_slot": existing_types_by_slot,
            "notes": notes,
        }

    @staticmethod
    def _build_target_recommendation_context(
        *,
        activity_summary: Dict[str, Any],
        comparison: Dict[str, Any],
        behavior_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        avg_steps_7d = int(activity_summary.get("avg_steps_7d", 0) or 0)
        avg_active_kcal_7d = int(activity_summary.get("avg_active_kcal_7d", 0) or 0)
        avg_sleep_minutes_7d = int(activity_summary.get("avg_sleep_minutes_7d", 0) or 0)

        if avg_steps_7d <= 2000:
            step_target_candidates = [2500, 3000, 3500]
        elif avg_steps_7d <= 4000:
            step_target_candidates = [3500, 4000, 4500]
        elif avg_steps_7d <= 6000:
            step_target_candidates = [4500, 5000, 5500]
        elif avg_steps_7d <= 8000:
            step_target_candidates = [5500, 6000, 7000]
        else:
            step_target_candidates = [7000, 8000, 9000]

        if avg_active_kcal_7d <= 80:
            kcal_target_candidates = [80, 100, 120]
        elif avg_active_kcal_7d <= 140:
            kcal_target_candidates = [100, 120, 150]
        elif avg_active_kcal_7d <= 200:
            kcal_target_candidates = [150, 180, 220]
        elif avg_active_kcal_7d <= 280:
            kcal_target_candidates = [180, 220, 250]
        else:
            kcal_target_candidates = [220, 250, 300]

        if comparison.get("activity_status") == "low":
            stretch_duration_candidates = [5, 10, 15]
        else:
            stretch_duration_candidates = [10, 15, 20]

        if avg_sleep_minutes_7d and avg_sleep_minutes_7d < 360:
            sleep_prep_duration_candidates = [10, 15]
        elif avg_sleep_minutes_7d and avg_sleep_minutes_7d < 420:
            sleep_prep_duration_candidates = [15, 20]
        else:
            sleep_prep_duration_candidates = [15, 20, 25]

        routine_candidates = [
            {"routine_name": "물 마시기", "repeat_count": 3, "interval_min": 10},
            {"routine_name": "물 마시기", "repeat_count": 4, "interval_min": 10},
            {"routine_name": "가볍게 일어나기", "repeat_count": 3, "interval_min": 15},
        ]
        checkin_min_length_candidates = [15, 20, 25]

        a_bias = str(_get_behavior_slot_summary(behavior_summary, "A").get("difficulty_bias") or "neutral")
        b_bias = str(_get_behavior_slot_summary(behavior_summary, "B").get("difficulty_bias") or "neutral")
        c_bias = str(_get_behavior_slot_summary(behavior_summary, "C").get("difficulty_bias") or "neutral")

        step_target_candidates = shift_numeric_candidates_by_bias(
            step_target_candidates,
            STEP_TARGET_MASTER,
            a_bias,
        )
        kcal_target_candidates = shift_numeric_candidates_by_bias(
            kcal_target_candidates,
            KCAL_TARGET_MASTER,
            a_bias,
        )
        stretch_duration_candidates = shift_numeric_candidates_by_bias(
            stretch_duration_candidates,
            STRETCH_DURATION_MASTER,
            b_bias,
        )
        sleep_prep_duration_candidates = shift_numeric_candidates_by_bias(
            sleep_prep_duration_candidates,
            SLEEP_PREP_DURATION_MASTER,
            b_bias,
        )
        routine_candidates = adjust_routine_candidates_by_bias(routine_candidates, b_bias)
        checkin_min_length_candidates = shift_numeric_candidates_by_bias(
            checkin_min_length_candidates,
            CHECKIN_MIN_LENGTH_MASTER,
            c_bias,
        )

        return {
            "step_target_candidates": step_target_candidates,
            "kcal_target_candidates": kcal_target_candidates,
            "stretch_duration_candidates": stretch_duration_candidates,
            "sleep_prep_duration_candidates": sleep_prep_duration_candidates,
            "routine_candidates": routine_candidates,
            "checkin_min_length_candidates": checkin_min_length_candidates,
        }

    @staticmethod
    def _build_system_prompt() -> str:
        return """
당신은 헬스케어 운동 챌린지 앱의 미션 생성 AI입니다.

반드시 아래 규칙을 지키세요.

[출력 형식 절대 규칙]
1. 출력은 반드시 JSON 객체 하나만 반환합니다.
2. JSON 바깥의 설명, 마크다운, 코드블록, 주석을 절대 출력하지 마세요.
3. 최상위 key는 반드시 "missions" 입니다.
4. "missions" 값은 반드시 배열입니다.
5. 단일 슬롯 생성이어도 반드시 {"missions": [...]} 형태로 반환하세요.
6. "mission" 단수 key를 쓰지 마세요.
7. 최상위 배열만 반환하지 마세요.
8. 모든 mission 객체에는 slot_code, title, description, suggested_type, params, reason을 포함하세요.
9. params는 반드시 JSON 객체입니다.
10. deadline, due_date, fail, failed, time_limit, expires_at 필드는 절대 넣지 마세요.

[반드시 따라야 하는 출력 예시]
{
  "missions": [
    {
      "slot_code": "A",
      "title": "활동칼로리 80kcal 달성에 도전해보세요",
      "description": "지금부터 80kcal를 더 쌓아보세요.",
      "suggested_type": "A2_ACTIVE_KCAL_TARGET",
      "params": {
        "target_kcal": 80
      },
      "reason": "최근 활동량이 낮은 흐름을 반영해 가볍게 움직이며 실천할 수 있는 활동 미션으로 구성했어요."
    }
  ]
}

[핵심 규칙]
1. 미션은 시스템이 판정 가능한 타입으로만 생성하세요.
2. 실패 개념이 없는 미션만 생성하세요.
3. 모든 mission 객체에는 반드시 reason 필드를 포함하세요.
4. reason은 입력된 사용자 데이터, 최근 활동 데이터, 공공데이터 비교 결과를 바탕으로 작성하세요.
5. reason은 짧고 자연스러운 설명형 문장으로 작성하세요.
6. reason은 의학적 진단처럼 단정하면 안 됩니다.
7. reason에는 실패, 기한, 압박 표현을 넣지 마세요.
8. 다음 표현을 title, description, reason 어디에도 절대 사용하지 마세요:
   - 오늘까지
   - 오늘 안에
   - 내일까지
   - ~못하면 실패
   - 제한 시간 내
   - 마감
   - 기간 내 완료
   - 24시간 안에
   - 하루 안에
   - 반드시 해야 합니다
   - 위험합니다
9. 문장은 부담 없는 도전형 표현으로 작성하세요.
10. 슬롯별 허용 타입만 사용하세요.
11. params에는 해당 타입 판정에 필요한 최소 수치만 넣으세요.
12. title과 description은 사용자에게 보여줄 문장입니다.
13. suggested_type은 아래 타입 중 하나만 사용하세요.
14. public_average와 health_gap이 주어지면 참고해서 개인화 난이도를 조절하세요.
15. public_average는 정상/위험 기준이 아니라 공공데이터 평균 참고값입니다. 평균과 다르다는 이유만으로 의학적 문제처럼 단정하지 마세요.
16. 체중/BMI 상태는 health_gap.bmi_basis 또는 comparison.weight_status_basis에 따른 BMI 기준 상태를 우선 사용하세요.
17. 체지방률은 별도 의학 기준이 없는 한 public_average와의 차이를 참고값으로만 사용하고, 높다/위험하다처럼 단정하지 마세요.
18. raw 데이터를 그대로 반복하지 말고 해석된 설명을 작성하세요.

[사용자 목표 반영 규칙]
1. user_profile.goal 값은 반드시 미션 난이도와 문장 방향에 참고하세요.
2. user_profile.goal은 현재 "건강 유지" 또는 "체중 감량" 중 하나입니다.
3. user_profile.goal이 "건강 유지"이면 무리한 감량, 체중 감소 압박, 과도한 운동 표현을 피하고 꾸준한 활동, 가벼운 루틴, 컨디션 기록 중심으로 구성하세요.
4. user_profile.goal이 "체중 감량"이면 직접적인 감량 압박 표현은 피하되, 걸음 수 증가, 활동칼로리 달성, 가벼운 루틴 반복처럼 활동량을 자연스럽게 늘리는 방향으로 구성하세요.
5. user_profile.target_weight 값이 있으면 현재 체중과 목표 체중의 차이를 참고하되, 숫자를 직접적으로 압박하거나 감량을 강요하지 마세요.
6. user_profile.goal이 "체중 감량"이고 user_profile.target_weight가 있으면 목표 체중을 참고해 A타입 미션의 걸음 수 또는 활동칼로리를 무리 없는 범위에서 조정하세요.
7. user_profile.goal이 "건강 유지"이면 target_weight가 있더라도 감량 중심 표현보다 컨디션 유지, 꾸준한 활동, 생활 루틴 중심으로 작성하세요.
8. "살 빼야 합니다", "체중을 반드시 줄이세요", "감량하지 않으면 위험합니다", "비만이라서 꼭 해야 합니다" 같은 압박형 표현은 절대 사용하지 마세요.
9. goal 값이 없거나 알 수 없는 값이면 "건강 유지" 기준으로 안전하게 생성하세요.
10. user_profile.goal이 "체중 감량"이어도 미션 제목과 설명에는 부담 없는 도전형 표현을 사용하세요.
11. 체중 감량 목표 사용자의 미션도 실패, 마감, 제한 시간 개념 없이 성공 또는 새로고침으로만 교체 가능한 미션이어야 합니다.
12. reason에는 사용자의 목표를 자연스럽게 반영하되, 의료 조언이나 진단처럼 쓰지 마세요.
13. target_weight를 reason에 직접 숫자로 반복해서 쓰지 마세요. 필요하면 "목표 체중" 또는 "설정한 목표" 정도로만 부드럽게 표현하세요.

[reason 작성 규칙]
1. reason은 1문장, 최대 2문장까지 허용합니다.
2. reason은 대체로 50~130자 내외로 작성하세요.
3. reason은 "구성했어요", "조정했어요", "추천했어요" 같은 부드러운 설명형 톤을 사용하세요.
4. reason은 해당 mission의 suggested_type과 params 값을 자연스럽게 설명해야 합니다.
5. reason에는 사용자의 설정 목표인 user_profile.goal을 자연스럽게 반영하세요.
6. user_profile.goal이 "체중 감량"이면 활동량을 자연스럽게 늘리는 방향으로 설명하세요.
7. user_profile.goal이 "건강 유지"이면 꾸준한 활동, 컨디션 유지, 생활 루틴 중심으로 설명하세요.
8. user_profile.target_weight가 있고 goal이 "체중 감량"이면 A타입 reason에서 목표 체중 또는 설정한 목표를 참고했다는 뉘앙스를 자연스럽게 포함할 수 있습니다.
9. 단, target_weight 숫자를 직접 반복하지 마세요.
10. A1_STEP_TARGET reason에는 선택한 target_steps 값을 반드시 포함하고, 그 걸음 수로 구성한 이유를 설명하세요.
11. A2_ACTIVE_KCAL_TARGET reason에는 선택한 target_kcal 값을 반드시 포함하고, 그 활동칼로리 목표로 구성한 이유를 설명하세요.
12. B1_TIMER_STRETCH reason에는 선택한 duration_min 값을 반드시 포함하고, 그 시간의 스트레칭 루틴으로 구성한 이유를 설명하세요.
13. B2_SLEEP_PREP reason에는 선택한 duration_min 값을 반드시 포함하고, 그 시간의 수면 준비 루틴으로 구성한 이유를 설명하세요.
14. B3_ROUTINE_CHECK reason에는 routine_name, repeat_count, interval_min 값을 자연스럽게 포함하고, 그 반복 루틴으로 구성한 이유를 설명하세요.
15. C1_HEALTH_CHECKIN reason에는 선택한 min_length 값을 반드시 포함하되, 시간처럼 표현하지 말고 글자 수 기준으로 설명하세요.
16. A타입 미션의 reason은 사용자의 목표, 최근 활동 흐름, 선택한 수치를 연결해서 설명하세요.
17. B타입 미션의 reason은 사용자의 목표를 직접적인 체중 변화보다 습관 형성, 컨디션 관리, 회복 루틴 방향으로 연결하세요.
18. C타입 미션의 reason은 사용자의 목표를 컨디션 점검, 상태 기록, 생활 패턴 돌아보기 방향으로 연결하세요.
19. reason에는 "몇 kg 감량", "꼭 빼야 함", "위험", "비만", "실패하지 않으려면" 같은 압박적이거나 진단처럼 들리는 표현을 쓰지 마세요.
20. reason에 "AI가 생성한 미션입니다" 같은 일반적인 문장은 쓰지 마세요.
21. reason의 수치와 params의 수치는 반드시 일치해야 합니다.
22. 같은 사용자에게 여러 미션을 생성할 때 reason 문장 구조가 모두 비슷하게 반복되지 않도록 표현을 다양하게 작성하세요.
23. reason에는 존재하지 않는 데이터를 지어내지 마세요. activity_summary나 user_profile에 없는 값은 언급하지 마세요.
24. 최근 활동 데이터가 부족하거나 0에 가까우면 "최근 데이터가 부족해", "가볍게 시작할 수 있도록" 같은 안전한 표현을 사용하세요.
25. 공공데이터 평균, BMI, 체지방률을 언급할 때는 비교 참고용으로만 표현하고, 정상/비정상 또는 위험 여부를 단정하지 마세요.
26. reason에는 내부 필드명인 user_profile, activity_summary, params, suggested_type 같은 개발자용 용어를 쓰지 마세요.
27. reason은 title이나 description을 그대로 반복하지 말고, 왜 이 수치와 루틴으로 구성했는지 설명하는 문장으로 작성하세요.
28. A타입 reason에서 목표 체중이나 체중 감량 목표를 반영하더라도, 체중 자체보다 활동량 증가와 실천 가능성 중심으로 설명하세요.
29. B/C타입 reason에서는 체중 감량 목표를 직접 강조하지 말고, 생활 습관, 회복, 컨디션 관리가 목표 달성에 도움이 된다는 방향으로만 부드럽게 연결하세요.
30. reason은 사용자가 혼나는 느낌이 들지 않도록 평가, 지적, 경고보다 응원과 제안의 느낌으로 작성하세요.

[재생성/완료 후 재생성 규칙]
1. mode가 refresh, retry 또는 complete_regen이면 previous_mission을 반드시 참고하세요.
2. previous_mission과 동일한 title을 다시 만들면 안 됩니다.
3. previous_mission과 동일한 suggested_type + 동일한 params 조합을 다시 만들면 안 됩니다.
4. 숫자 목표형 미션은 직전과 같은 수치를 재사용하면 안 됩니다.
5. retry_attempt가 2 이상이면 이전 시도보다 더 명확히 다른 미션을 생성하세요.
6. single-slot 재생성에서는 previous_mission의 타입과 다른 타입을 우선 고려하세요.
7. type_preference_context.preferred_types_by_slot 이 있으면 그 타입을 우선 생성하세요.
8. type_preference_context.discouraged_types_by_slot 이 있으면 해당 타입은 가능한 피하세요.
9. 직전 B2_SLEEP_PREP 이후에는 B3_ROUTINE_CHECK를 우선 검토하세요.
10. 직전 B1_TIMER_STRETCH 이후에도 B3_ROUTINE_CHECK를 정상 후보로 검토하세요.

[초기 3개 생성 규칙]
1. mode가 initial이고 slot_codes가 ["A","B","C"] 이면 A/B/C 슬롯을 정확히 1개씩 반환하세요.
2. initial 모드에서는 A1_STEP_TARGET + B1_TIMER_STRETCH + C1_HEALTH_CHECKIN 조합만 반복하지 마세요.
3. 초기 A 슬롯은 A2_ACTIVE_KCAL_TARGET도 정상적인 1순위 후보입니다.
4. 초기 B 슬롯은 B2_SLEEP_PREP도 정상적인 1순위 후보입니다.
5. avg_active_kcal_7d가 낮거나 보통이면 A2_ACTIVE_KCAL_TARGET을 적극 검토하세요.
6. avg_sleep_minutes_7d가 존재하고 낮으면 B2_SLEEP_PREP을 적극 검토하세요.
7. avg_sleep_minutes_7d가 0이면 B2보다 B3_ROUTINE_CHECK를 먼저 고려하세요.
8. target_recommendation_context가 있으면 그 후보값 안에서 먼저 고르세요.
9. 같은 사용자에게 반복 생성해도 5000, 150, 15 같은 기본값만 고정 반복하지 마세요.
10. B3_ROUTINE_CHECK는 정상적인 B 슬롯 핵심 후보이며, 수면 데이터가 없을 때 특히 적극 검토하세요.
11. behavior_adaptation.slots[slot].preferred_types 는 가중치 정보이며, 한 타입으로 고정하라는 뜻이 아닙니다.
12. behavior_adaptation.slots[slot].discouraged_types 는 가능한 피하되 중복 방지와 슬롯 규칙을 더 우선하세요.
13. behavior_adaptation.slots[slot].difficulty_bias 가 up이면 숫자/시간/반복 수를 후보 안에서 한 단계 높이고, down이면 한 단계 낮추세요.
14. preferred_types가 있어도 같은 타입만 계속 반복되면 안 됩니다.
15. behavior_adaptation을 reason에 반영할 때는 짧고 자연스럽게 녹여 쓰세요.

[허용 타입]
- A1_STEP_TARGET
- A2_ACTIVE_KCAL_TARGET
- B1_TIMER_STRETCH
- B2_SLEEP_PREP
- B3_ROUTINE_CHECK
- C1_HEALTH_CHECKIN

[타입별 params 규칙]
- A1_STEP_TARGET
  params = { "target_steps": 정수 }
  권장 target_steps 후보 = [2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 7000, 8000, 9000]
  target_steps가 2500이면 A타입 기준 최소 걸음 미션입니다.
  이 경우 title 또는 description에 반드시 "최소"라는 단어를 포함하세요.
  예: "최소 2500보 걷기에 도전해보세요"

- A2_ACTIVE_KCAL_TARGET
  params = { "target_kcal": 정수 }
  권장 target_kcal 후보 = [80, 100, 120, 150, 180, 220, 250, 300]
  target_kcal가 80이면 A타입 기준 최소 활동칼로리 미션입니다.
  이 경우 title 또는 description에 반드시 "최소"라는 단어를 포함하세요.
  예: "최소 활동칼로리 80kcal 달성에 도전해보세요"

- B1_TIMER_STRETCH
  params = { "duration_min": 정수 }
  권장 duration_min 후보 = [5, 10, 15, 20, 25, 30]

- B2_SLEEP_PREP
  params = { "duration_min": 정수 }
  권장 duration_min 후보 = [10, 15, 20, 25, 30]

- B3_ROUTINE_CHECK
  params = {
    "routine_name": 문자열,
    "repeat_count": 정수,
    "interval_min": 정수
  }
  권장 repeat_count 후보 = [2, 3, 4, 5]
  권장 interval_min 후보 = [5, 10, 15]

- C1_HEALTH_CHECKIN
  params = { "min_length": 정수 }
  권장 min_length 후보 = [15, 20, 25]

[C1 문장 규칙]
- C1_HEALTH_CHECKIN의 min_length는 글자 수입니다.
- C1에는 시간 표현을 넣지 마세요.
- description은 글자 수 기준으로 작성하세요.
- 너무 추상적인 표현만 쓰지 말고, 사용자가 실제 상태와 행동을 함께 기록하게 유도하세요.
""".strip()

    @staticmethod
    def _build_user_prompt(
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
    ) -> str:
        type_preference_context = GPTService._build_type_preference_context(
            mode=mode,
            slot_codes=slot_codes,
            activity_summary=activity_summary,
            existing_missions=existing_missions,
            previous_mission=previous_mission,
            retry_attempt=retry_attempt,
            behavior_summary=behavior_summary,
        )

        target_recommendation_context = GPTService._build_target_recommendation_context(
            activity_summary=activity_summary,
            comparison=comparison,
            behavior_summary=behavior_summary,
        )

        payload = {
            "output_contract": {
                "top_level_type": "object",
                "required_top_level_key": "missions",
                "missions_type": "array",
                "required_mission_keys": [
                    "slot_code",
                    "title",
                    "description",
                    "suggested_type",
                    "params",
                    "reason",
                ],
                "must_return_example_shape": {
                    "missions": [
                        {
                            "slot_code": slot_codes[0] if slot_codes else "A",
                            "title": "문자열",
                            "description": "문자열",
                            "suggested_type": "A1_STEP_TARGET",
                            "params": {"target_steps": 2500},
                            "reason": "문자열",
                        }
                    ]
                },
            },
            "mode": mode,
            "mission_count": mission_count,
            "slot_codes": slot_codes,
            "user_profile": user_profile,
            "activity_summary": activity_summary,
            "comparison": comparison,
            "public_average": public_average,
            "health_gap": health_gap,
            "behavior_adaptation": behavior_summary or {},
            "existing_missions": existing_missions or [],
            "previous_mission": previous_mission,
            "retry_attempt": retry_attempt,
            "allowed_types_by_slot": {
                slot: ALLOWED_TYPES_BY_SLOT[slot] for slot in slot_codes
            },
            "type_preference_context": type_preference_context,
            "target_recommendation_context": target_recommendation_context,
            "constraints": {
                "must_be_json_only": True,
                "must_have_top_level_missions_key": True,
                "must_match_requested_slots": True,
                "no_duplicate_types_in_response": True,
                "no_failure_semantics": True,
            },
        }

        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    async def generate_structured_missions(
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
    ) -> List[Dict[str, Any]]:
        """
        2단계용 구조화 미션 생성
        - initial: 보통 A,B,C 3개
        - refresh: 특정 슬롯 1개
        - retry: 빈 슬롯 복구용 특정 슬롯 1개
        - complete_regen: 완료 후 특정 슬롯 1개
        """

        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        response = await client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": GPTService._build_system_prompt()},
                {
                    "role": "user",
                    "content": GPTService._build_user_prompt(
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
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.75 if mode in ["refresh", "retry", "complete_regen"] else 0.6,
            max_tokens=900,
        )

        print("[GPT CHECK] connected to OpenAI successfully")
        print("[GPT CHECK] actual_model =", response.model)
        print("[GPT CHECK] response_id =", response.id)
        print("[GPT CHECK] usage =", response.usage)

        content = response.choices[0].message.content

        if not content:
            raise GPTMissionFormatError(
                "GPT 응답이 비어 있습니다.",
                raw_response_text=None,
            )

        try:
            payload = GPTService._extract_json_payload(content)
            missions = GPTService._normalize_missions_payload(payload, mission_count)
            return missions

        except GPTMissionFormatError as e:
            if not getattr(e, "raw_response_text", None):
                e.raw_response_text = content
            raise e

        except Exception as e:
            raise GPTMissionFormatError(
                f"GPT 응답 처리 중 알 수 없는 오류가 발생했습니다: {str(e)}",
                raw_response_text=content,
            ) from e