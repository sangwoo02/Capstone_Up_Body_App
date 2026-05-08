"""C1_HEALTH_CHECKIN 체크인 카탈로그.

C 슬롯은 허용 mission_type이 C1_HEALTH_CHECKIN 하나뿐이므로,
단순히 min_length만 바꾸면 재생성 시 직전 미션과 같은 type+params로 판단되어
fallback이 자주 발생할 수 있다.

이 파일은 B3의 routine_key와 같은 역할을 하는 checkin_key를 도입해,
같은 C1 타입 안에서도 기록 주제와 프론트 표시 payload를 표준화한다.

주의:
- min_length는 글자 수 기준이며 시간/기한이 아니다.
- 의료 진단이나 위험 판정 대신 사용자가 직접 상태와 행동을 돌아보게 하는 기록형 주제만 허용한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

CHECKIN_CATALOG_VERSION = "c1_checkin_catalog_2026_05_06"
ALLOWED_CHECKIN_MIN_LENGTHS = [15, 20, 25]

CHECKIN_CATALOG: Dict[str, Dict[str, Any]] = {
    "condition_today": {
        "checkin_key": "condition_today",
        "checkin_label": "오늘 컨디션",
        "checkin_category": "condition",
        "icon_key": "heart_pulse",
        "prompt_label": "오늘 몸 상태와 기분",
        "title_template": "오늘 컨디션을 기록해보세요",
        "description_template": "오늘 몸 상태와 기분을 최소 {min_length}자 이상 적어보세요.",
        "reason_hint": "현재 컨디션을 직접 확인하며 건강 습관을 이어가기 좋은 기록 주제입니다.",
    },
    "activity_reflection": {
        "checkin_key": "activity_reflection",
        "checkin_label": "활동 돌아보기",
        "checkin_category": "activity",
        "icon_key": "activity",
        "prompt_label": "최근 움직임과 활동 느낌",
        "title_template": "오늘 움직임을 돌아보세요",
        "description_template": "오늘 또는 최근 움직임에서 느낀 점을 최소 {min_length}자 이상 적어보세요.",
        "reason_hint": "활동량 흐름을 부담 없이 돌아보며 다음 실천으로 연결하기 좋은 기록 주제입니다.",
    },
    "sleep_reflection": {
        "checkin_key": "sleep_reflection",
        "checkin_label": "수면 느낌",
        "checkin_category": "sleep",
        "icon_key": "moon",
        "prompt_label": "수면 후 회복감과 피로감",
        "title_template": "수면 느낌을 기록해보세요",
        "description_template": "최근 수면 후 회복감이나 피로감을 최소 {min_length}자 이상 적어보세요.",
        "reason_hint": "사용자가 직접 느낀 수면감이나 회복 느낌을 기록하고 싶을 때 쓰기 좋은 주제입니다.",
    },
    "mood_energy": {
        "checkin_key": "mood_energy",
        "checkin_label": "기분과 에너지",
        "checkin_category": "mood",
        "icon_key": "sparkles",
        "prompt_label": "현재 기분과 에너지 수준",
        "title_template": "기분과 에너지를 남겨보세요",
        "description_template": "지금 기분과 에너지 상태를 최소 {min_length}자 이상 적어보세요.",
        "reason_hint": "운동량보다 현재 상태를 먼저 확인해야 할 때 부담 없이 쓰기 좋은 기록 주제입니다.",
    },
    "habit_review": {
        "checkin_key": "habit_review",
        "checkin_label": "건강 습관 회고",
        "checkin_category": "habit",
        "icon_key": "check_circle",
        "prompt_label": "최근 건강 습관과 작게 해낸 일",
        "title_template": "최근 건강 습관을 되짚어보세요",
        "description_template": "최근 건강을 위해 시도한 작은 행동을 최소 {min_length}자 이상 적어보세요.",
        "reason_hint": "건강 유지 목표에서 작은 실천을 이어가기 쉽게 만드는 기록 주제입니다.",
    },
    "body_signal": {
        "checkin_key": "body_signal",
        "checkin_label": "몸의 신호",
        "checkin_category": "body_signal",
        "icon_key": "body",
        "prompt_label": "몸에서 느껴지는 신호와 변화",
        "title_template": "몸의 신호를 기록해보세요",
        "description_template": "오늘 몸에서 느껴지는 변화나 신호를 최소 {min_length}자 이상 적어보세요.",
        "reason_hint": "수치만으로 보이지 않는 몸 상태를 직접 확인하기 좋은 기록 주제입니다.",
    },
}

CHECKIN_LABEL_TO_KEY: Dict[str, str] = {}
for _key, _item in CHECKIN_CATALOG.items():
    for _name in {
        _item["checkin_label"],
        _item["prompt_label"],
        _item["title_template"],
    }:
        CHECKIN_LABEL_TO_KEY[str(_name).strip()] = _key

CHECKIN_LABEL_TO_KEY.update(
    {
        "컨디션": "condition_today",
        "오늘 컨디션": "condition_today",
        "활동 기록": "activity_reflection",
        "활동 돌아보기": "activity_reflection",
        "수면 기록": "sleep_reflection",
        "수면 느낌": "sleep_reflection",
        "기분": "mood_energy",
        "기분과 에너지": "mood_energy",
        "습관 회고": "habit_review",
        "건강 습관 회고": "habit_review",
        "몸 상태": "body_signal",
        "몸의 신호": "body_signal",
    }
)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp_to_allowed(value: Any, allowed_values: List[int], default: int) -> int:
    raw = _safe_int(value, default)
    if raw in allowed_values:
        return raw
    return min(allowed_values, key=lambda item: abs(item - raw))


def normalize_checkin_key(value: Any) -> str:
    key = str(value or "").strip()
    if key in CHECKIN_CATALOG:
        return key
    return CHECKIN_LABEL_TO_KEY.get(key, "")


def get_checkin_by_key(checkin_key: Any) -> Optional[Dict[str, Any]]:
    key = normalize_checkin_key(checkin_key)
    if not key:
        return None
    item = CHECKIN_CATALOG.get(key)
    return dict(item) if item else None


def get_checkin_by_label(checkin_label: Any) -> Optional[Dict[str, Any]]:
    key = CHECKIN_LABEL_TO_KEY.get(str(checkin_label or "").strip())
    return get_checkin_by_key(key) if key else None


def get_allowed_checkin_keys() -> List[str]:
    return list(CHECKIN_CATALOG.keys())


def get_allowed_checkin_labels() -> List[str]:
    return [item["checkin_label"] for item in CHECKIN_CATALOG.values()]


def is_allowed_checkin_label_for_key(checkin_key: str, checkin_label: Any) -> bool:
    item = get_checkin_by_key(checkin_key)
    if not item:
        return False
    label = str(checkin_label or "").strip()
    return label in {
        item["checkin_label"],
        item["prompt_label"],
        item["title_template"],
    }


def normalize_checkin_params(
    params: Optional[Dict[str, Any]],
    *,
    default_key: str = "condition_today",
    allow_label_fallback: bool = True,
) -> Dict[str, Any]:
    """C1 params를 프론트 호환 표준 payload로 정리한다."""

    params = params or {}
    checkin_key = normalize_checkin_key(params.get("checkin_key"))

    if not checkin_key and allow_label_fallback:
        from_label = get_checkin_by_label(params.get("checkin_label")) or get_checkin_by_label(params.get("prompt_label"))
        if from_label:
            checkin_key = str(from_label["checkin_key"])

    if not checkin_key:
        checkin_key = normalize_checkin_key(default_key) or "condition_today"

    item = get_checkin_by_key(checkin_key) or get_checkin_by_key("condition_today")
    assert item is not None

    min_length = clamp_to_allowed(
        params.get("min_length"),
        ALLOWED_CHECKIN_MIN_LENGTHS,
        15,
    )

    return {
        "checkin_key": item["checkin_key"],
        "checkin_label": item["checkin_label"],
        "checkin_category": item["checkin_category"],
        "icon_key": item["icon_key"],
        "prompt_label": item["prompt_label"],
        "min_length": min_length,
        "catalog_version": CHECKIN_CATALOG_VERSION,
    }


def build_checkin_mission_payload(
    *,
    checkin_key: Any,
    min_length: Any,
) -> Dict[str, Any]:
    params = normalize_checkin_params({"checkin_key": checkin_key, "min_length": min_length})
    item = get_checkin_by_key(params["checkin_key"])
    assert item is not None

    return {
        "slot_code": "C",
        "title": item["title_template"],
        "description": item["description_template"].format(min_length=params["min_length"]),
        "mission_type": "C1_HEALTH_CHECKIN",
        "suggested_type": "C1_HEALTH_CHECKIN",
        "params": params,
        "reason": (
            f"{item['checkin_label']} 주제로 현재 상태를 "
            f"{params['min_length']}자 이상 기록하며 건강 패턴을 돌아볼 수 있도록 추천했어요."
        ),
    }


def _dedupe_preserve_order(keys: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for key in keys:
        normalized = normalize_checkin_key(key)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def build_checkin_candidates(
    *,
    goal_direction: str = "health_maintenance",
    activity_status: str = "unknown",
    sleep_status: str = "unknown",
    data_confidence: str = "medium",
    difficulty: str = "easy",
    difficulty_bias: str = "neutral",
    previous_checkin_key: str = "",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """개인화 정책 엔진이 GPT에 넘길 C1 주제 후보를 만든다."""

    ordered_keys: List[str] = []

    if sleep_status in {"short", "low", "insufficient"}:
        ordered_keys.extend(["sleep_reflection", "mood_energy", "condition_today"])

    if activity_status in {"low", "below_average"}:
        ordered_keys.extend(["activity_reflection", "condition_today", "habit_review"])

    if data_confidence in {"low", "medium"}:
        ordered_keys.extend(["condition_today", "body_signal", "mood_energy"])

    if goal_direction == "weight_loss_support":
        ordered_keys.extend(["activity_reflection", "habit_review", "body_signal"])
    else:
        ordered_keys.extend(["habit_review", "condition_today", "mood_energy"])

    ordered_keys.extend(list(CHECKIN_CATALOG.keys()))
    ordered_keys = _dedupe_preserve_order(ordered_keys)

    previous_key = normalize_checkin_key(previous_checkin_key)
    if previous_key and len(ordered_keys) > 1:
        ordered_keys = [key for key in ordered_keys if key != previous_key] + [previous_key]

    if difficulty == "easy" or difficulty_bias == "down":
        min_lengths = [15, 20]
    elif difficulty_bias == "up":
        min_lengths = [20, 25]
    else:
        min_lengths = [15, 20, 25]

    candidates: List[Dict[str, Any]] = []
    for key in ordered_keys:
        item = CHECKIN_CATALOG[key]
        for min_length in min_lengths:
            candidates.append(
                {
                    "checkin_key": item["checkin_key"],
                    "checkin_label": item["checkin_label"],
                    "checkin_category": item["checkin_category"],
                    "icon_key": item["icon_key"],
                    "prompt_label": item["prompt_label"],
                    "min_length": min_length,
                }
            )
            break

    return candidates[: max(1, limit)]


def summarize_checkin_catalog_for_prompt() -> Dict[str, Any]:
    return {
        "catalog_version": CHECKIN_CATALOG_VERSION,
        "allowed_min_lengths": ALLOWED_CHECKIN_MIN_LENGTHS,
        "allowed_checkins": [
            {
                "checkin_key": item["checkin_key"],
                "checkin_label": item["checkin_label"],
                "checkin_category": item["checkin_category"],
                "icon_key": item["icon_key"],
                "prompt_label": item["prompt_label"],
            }
            for item in CHECKIN_CATALOG.values()
        ],
    }
