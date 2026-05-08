"""B3_ROUTINE_CHECK 루틴 카탈로그.

B3는 사용자가 체감하는 개인화 다양성이 가장 크게 보이는 슬롯이다.
이 파일은 GPT가 임의의 루틴명을 만들지 않도록 FastAPI 서버가 허용 루틴과
프론트 연결용 payload를 표준화하는 정책 카탈로그다.

주의:
- repeat_count / interval_min은 의학 기준이 아니라 앱 UX 기준이다.
- 물 섭취량(L) 같은 의학/영양 목표를 직접 만들지 않는다.
- 실패/마감/기한 개념이 없는 체크형 루틴만 허용한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

ROUTINE_CATALOG_VERSION = "b3_routine_catalog_2026_05_06"

ALLOWED_REPEAT_COUNTS = [2, 3, 4, 5]
ALLOWED_INTERVAL_MINUTES = [5, 10, 15]

# 프론트에서 바로 사용할 수 있도록 label/category/icon/action_label을 함께 둔다.
# icon_key는 현재 프론트가 바로 쓰지 않아도 나중에 routine_key별 아이콘 분기에 사용할 수 있다.
ROUTINE_CATALOG: Dict[str, Dict[str, Any]] = {
    "hydration": {
        "routine_key": "hydration",
        "routine_name": "물 마시기",
        "routine_label": "물 마시기",
        "routine_category": "hydration",
        "icon_key": "droplets",
        "action_label": "물 한 컵 마시기",
        "title_template": "물 마시기 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 물 마시기 루틴을 체크해보세요.",
        "reason_hint": "부담 없는 수분 섭취 습관을 만들기 쉬운 루틴입니다.",
    },
    "posture_reset": {
        "routine_key": "posture_reset",
        "routine_name": "자세 펴기",
        "routine_label": "자세 펴기",
        "routine_category": "posture",
        "icon_key": "posture",
        "action_label": "어깨와 허리 펴기",
        "title_template": "자세 펴기 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 어깨와 허리를 가볍게 펴보세요.",
        "reason_hint": "오래 앉아 있는 흐름에서도 짧게 실천하기 쉬운 자세 리셋 루틴입니다.",
    },
    "light_standup": {
        "routine_key": "light_standup",
        "routine_name": "가볍게 일어나기",
        "routine_label": "가볍게 일어나기",
        "routine_category": "light_activity",
        "icon_key": "standup",
        "action_label": "자리에서 일어나기",
        "title_template": "가볍게 일어나기 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 자리에서 일어나 몸을 가볍게 움직여보세요.",
        "reason_hint": "활동량이 낮은 날에도 부담 없이 움직임을 늘리기 좋은 루틴입니다.",
    },
    "breathing": {
        "routine_key": "breathing",
        "routine_name": "심호흡 하기",
        "routine_label": "심호흡",
        "routine_category": "breathing",
        "icon_key": "wind",
        "action_label": "천천히 심호흡하기",
        "title_template": "심호흡 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 천천히 숨을 고르는 루틴을 체크해보세요.",
        "reason_hint": "회복과 컨디션 점검을 부담 없이 연결하기 좋은 루틴입니다.",
    },
    "eye_rest": {
        "routine_key": "eye_rest",
        "routine_name": "눈 휴식하기",
        "routine_label": "눈 휴식",
        "routine_category": "eye_rest",
        "icon_key": "eye",
        "action_label": "잠시 먼 곳 바라보기",
        "title_template": "눈 휴식 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 화면에서 시선을 떼고 눈을 쉬게 해보세요.",
        "reason_hint": "일상 중 짧게 실천하기 쉬운 회복형 루틴입니다.",
    },
    "neck_shoulder": {
        "routine_key": "neck_shoulder",
        "routine_name": "목·어깨 풀기",
        "routine_label": "목·어깨 풀기",
        "routine_category": "mobility",
        "icon_key": "activity",
        "action_label": "목과 어깨 가볍게 풀기",
        "title_template": "목·어깨 풀기 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 목과 어깨를 가볍게 풀어보세요.",
        "reason_hint": "짧은 움직임으로 몸을 풀며 루틴을 이어가기 좋습니다.",
    },
    "light_walk_check": {
        "routine_key": "light_walk_check",
        "routine_name": "짧게 걷기",
        "routine_label": "짧게 걷기",
        "routine_category": "light_activity",
        "icon_key": "footprints",
        "action_label": "제자리 걷기 또는 짧게 걷기",
        "title_template": "짧게 걷기 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 제자리 걷기나 짧은 움직임을 체크해보세요.",
        "reason_hint": "활동량을 자연스럽게 늘리는 데 연결하기 쉬운 루틴입니다.",
    },
    "sleep_ready": {
        "routine_key": "sleep_ready",
        "routine_name": "휴식 준비하기",
        "routine_label": "휴식 준비",
        "routine_category": "sleep_prep",
        "icon_key": "moon",
        "action_label": "화면에서 잠시 멀어지기",
        "title_template": "휴식 준비 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 화면에서 잠시 멀어지고 휴식 준비를 체크해보세요.",
        "reason_hint": "수면 시간이 짧은 흐름이 있을 때 부담 없이 회복 루틴을 만들기 좋습니다.",
    },
    "condition_reset": {
        "routine_key": "condition_reset",
        "routine_name": "컨디션 점검하기",
        "routine_label": "컨디션 점검",
        "routine_category": "condition_check",
        "icon_key": "heart_pulse",
        "action_label": "몸 상태 가볍게 확인하기",
        "title_template": "컨디션 점검 루틴 {repeat_count}회 체크해보세요",
        "description_template": "{interval_min}분 간격으로 몸 상태와 기분을 가볍게 확인해보세요.",
        "reason_hint": "활동보다 상태 확인이 더 필요한 날에 부담 없이 이어가기 좋은 루틴입니다.",
    },
}

ROUTINE_NAME_TO_KEY: Dict[str, str] = {}
for _key, _item in ROUTINE_CATALOG.items():
    for _name in {
        _item["routine_name"],
        _item["routine_label"],
        _item["action_label"],
    }:
        ROUTINE_NAME_TO_KEY[str(_name).strip()] = _key

# 자주 나올 수 있는 별칭을 허용한다.
ROUTINE_NAME_TO_KEY.update(
    {
        "물마시기": "hydration",
        "가볍게 일어나기": "light_standup",
        "일어나기": "light_standup",
        "자세 펴기": "posture_reset",
        "자세 리셋": "posture_reset",
        "심호흡": "breathing",
        "눈 휴식": "eye_rest",
        "목 어깨 풀기": "neck_shoulder",
        "목·어깨 풀기": "neck_shoulder",
        "짧게 걷기": "light_walk_check",
        "제자리 걷기": "light_walk_check",
        "휴식 준비": "sleep_ready",
        "컨디션 점검": "condition_reset",
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


def normalize_routine_key(value: Any) -> str:
    key = str(value or "").strip()
    if key in ROUTINE_CATALOG:
        return key
    return ROUTINE_NAME_TO_KEY.get(key, "")


def get_routine_by_key(routine_key: Any) -> Optional[Dict[str, Any]]:
    key = normalize_routine_key(routine_key)
    if not key:
        return None
    item = ROUTINE_CATALOG.get(key)
    return dict(item) if item else None


def get_routine_by_name(routine_name: Any) -> Optional[Dict[str, Any]]:
    key = ROUTINE_NAME_TO_KEY.get(str(routine_name or "").strip())
    return get_routine_by_key(key) if key else None


def get_allowed_routine_keys() -> List[str]:
    return list(ROUTINE_CATALOG.keys())


def get_allowed_routine_names() -> List[str]:
    return [item["routine_name"] for item in ROUTINE_CATALOG.values()]


def dedupe_routine_keys(values: Optional[List[Any]]) -> List[str]:
    """routine_key/routine_name 혼합 입력을 허용하고 순서를 보존해 중복 제거한다."""

    result: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        key = normalize_routine_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def is_allowed_routine_name_for_key(routine_key: str, routine_name: Any) -> bool:
    routine = get_routine_by_key(routine_key)
    if not routine:
        return False
    name = str(routine_name or "").strip()
    return name in {
        routine["routine_name"],
        routine["routine_label"],
        routine["action_label"],
    }


def normalize_routine_params(
    params: Optional[Dict[str, Any]],
    *,
    default_key: str = "hydration",
    allow_name_fallback: bool = True,
) -> Dict[str, Any]:
    """B3 params를 프론트 호환 표준 payload로 정리한다."""

    params = params or {}
    routine_key = normalize_routine_key(params.get("routine_key"))

    if not routine_key and allow_name_fallback:
        routine_from_name = get_routine_by_name(params.get("routine_name"))
        if routine_from_name:
            routine_key = str(routine_from_name["routine_key"])

    if not routine_key:
        routine_key = normalize_routine_key(default_key) or "hydration"

    routine = get_routine_by_key(routine_key) or get_routine_by_key("hydration")
    assert routine is not None

    repeat_count = clamp_to_allowed(
        params.get("repeat_count"),
        ALLOWED_REPEAT_COUNTS,
        3,
    )
    interval_min = clamp_to_allowed(
        params.get("interval_min"),
        ALLOWED_INTERVAL_MINUTES,
        10,
    )

    return {
        "routine_key": routine["routine_key"],
        "routine_name": routine["routine_name"],
        "routine_label": routine["routine_label"],
        "routine_category": routine["routine_category"],
        "icon_key": routine["icon_key"],
        "action_label": routine["action_label"],
        "repeat_count": repeat_count,
        "interval_min": interval_min,
        "catalog_version": ROUTINE_CATALOG_VERSION,
    }


def build_routine_mission_payload(
    *,
    routine_key: Any,
    repeat_count: Any,
    interval_min: Any,
) -> Dict[str, Any]:
    """서버 fallback에서 바로 사용할 B3 mission_data를 만든다."""

    params = normalize_routine_params(
        {
            "routine_key": routine_key,
            "repeat_count": repeat_count,
            "interval_min": interval_min,
        }
    )
    routine = get_routine_by_key(params["routine_key"]) or ROUTINE_CATALOG["hydration"]

    return {
        "slot_code": "B",
        "title": routine["title_template"].format(**params),
        "description": routine["description_template"].format(**params),
        "mission_type": "B3_ROUTINE_CHECK",
        "suggested_type": "B3_ROUTINE_CHECK",
        "params": params,
        "reason": f"{routine['reason_hint']} {params['repeat_count']}회 체크로 부담 없이 이어갈 수 있게 구성했어요.",
    }


def _shift_int(value: int, allowed_values: List[int], bias: str) -> int:
    if value not in allowed_values:
        value = clamp_to_allowed(value, allowed_values, allowed_values[0])
    idx = allowed_values.index(value)
    if bias == "up":
        idx = min(len(allowed_values) - 1, idx + 1)
    elif bias == "down":
        idx = max(0, idx - 1)
    return allowed_values[idx]


def adjust_routine_candidates_by_bias(
    candidates: List[Dict[str, Any]],
    difficulty_bias: str,
) -> List[Dict[str, Any]]:
    """기존 gpt_service 호환 함수. routine_key 등 부가 필드를 보존한다."""

    if difficulty_bias not in {"up", "down"}:
        return [normalize_routine_params(candidate) for candidate in candidates]

    adjusted: List[Dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for candidate in candidates:
        normalized = normalize_routine_params(candidate)
        normalized["repeat_count"] = _shift_int(
            int(normalized["repeat_count"]),
            ALLOWED_REPEAT_COUNTS,
            difficulty_bias,
        )
        # interval은 짧을수록 자주 체크해야 하므로 up이면 한 단계 짧게, down이면 길게 둔다.
        interval_bias = "down" if difficulty_bias == "up" else "up"
        normalized["interval_min"] = _shift_int(
            int(normalized["interval_min"]),
            ALLOWED_INTERVAL_MINUTES,
            interval_bias,
        )
        signature = (
            normalized["routine_key"],
            normalized["repeat_count"],
            normalized["interval_min"],
        )
        if signature in seen:
            continue
        seen.add(signature)
        adjusted.append(normalized)

    return adjusted or [normalize_routine_params({})]


def build_routine_candidates(
    *,
    difficulty: str = "easy",
    goal_direction: str = "health_maintenance",
    activity_status: str = "low",
    sleep_status: str = "unknown",
    data_confidence: str = "medium",
    difficulty_bias: str = "neutral",
    previous_routine_key: Optional[str] = None,
    recent_routine_keys: Optional[List[Any]] = None,
    blocked_routine_keys: Optional[List[Any]] = None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """개인화 정책 엔진에서 사용할 B3 후보 목록 생성."""

    if difficulty == "easy":
        repeat_count = 2
        interval_min = 15
    else:
        repeat_count = 3
        interval_min = 10

    priority_keys: List[str] = []

    if activity_status == "low":
        priority_keys.extend(["light_standup", "posture_reset", "breathing", "hydration"])
    elif goal_direction == "weight_loss_support":
        priority_keys.extend(["light_walk_check", "light_standup", "posture_reset", "hydration"])
    else:
        priority_keys.extend(["posture_reset", "hydration", "breathing", "eye_rest"])

    if sleep_status == "short":
        priority_keys.extend(["sleep_ready", "breathing", "eye_rest"])

    if data_confidence == "low":
        priority_keys.extend(["condition_reset", "hydration", "breathing"])

    priority_keys.extend(
        [
            "neck_shoulder",
            "eye_rest",
            "condition_reset",
            "hydration",
            "light_standup",
            "posture_reset",
            "breathing",
            "light_walk_check",
            "sleep_ready",
        ]
    )

    previous_key = normalize_routine_key(previous_routine_key)
    recent_keys = dedupe_routine_keys(recent_routine_keys)
    blocked_keys = dedupe_routine_keys(blocked_routine_keys)

    # 직전 B3 루틴도 반복 방지 대상에 포함한다.
    if previous_key and previous_key not in blocked_keys:
        blocked_keys.append(previous_key)

    ordered_keys: List[str] = []
    for key in priority_keys:
        normalized_key = normalize_routine_key(key)
        if not normalized_key or normalized_key in ordered_keys:
            continue
        ordered_keys.append(normalized_key)

    for key in recent_keys:
        if key not in ordered_keys:
            ordered_keys.append(key)

    # 최근 루틴 반복을 실제로 줄이기 위해 blocked routine은 후보 뒤쪽으로 보낸다.
    # 단, 카탈로그 후보가 너무 적어지는 경우에는 서비스 안정성을 위해 뒤쪽 fallback 후보로만 남긴다.
    non_blocked_keys = [key for key in ordered_keys if key not in set(blocked_keys)]
    blocked_tail = [key for key in ordered_keys if key in set(blocked_keys)]
    if non_blocked_keys:
        ordered_keys = non_blocked_keys + blocked_tail

    candidates = [
        normalize_routine_params(
            {
                "routine_key": key,
                "repeat_count": repeat_count,
                "interval_min": interval_min,
            }
        )
        for key in ordered_keys
    ]

    candidates = adjust_routine_candidates_by_bias(candidates, difficulty_bias)

    # 차단 루틴은 원칙적으로 반환 후보에서 제외한다. 전체 후보가 비는 경우에만 뒤쪽 후보를 살린다.
    blocked_set = set(blocked_keys)
    filtered_candidates = [c for c in candidates if c.get("routine_key") not in blocked_set]
    if filtered_candidates:
        candidates = filtered_candidates

    return candidates[: max(1, limit)]


def summarize_routine_catalog_for_prompt() -> Dict[str, Any]:
    """GPT prompt에 넣기 좋은 짧은 카탈로그 요약."""

    return {
        "catalog_version": ROUTINE_CATALOG_VERSION,
        "allowed_repeat_counts": ALLOWED_REPEAT_COUNTS,
        "allowed_interval_minutes": ALLOWED_INTERVAL_MINUTES,
        "allowed_routines": [
            {
                "routine_key": item["routine_key"],
                "routine_name": item["routine_name"],
                "routine_label": item["routine_label"],
                "routine_category": item["routine_category"],
                "icon_key": item["icon_key"],
                "action_label": item["action_label"],
            }
            for item in ROUTINE_CATALOG.values()
        ],
    }
