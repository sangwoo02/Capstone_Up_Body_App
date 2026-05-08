# app/services/mission_behavior_service.py

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.game import UserMissionBehaviorProfile
from app.models.user import UserMission, UserMissionEvent
from app.services.mission_policy.routine_catalog import (
    get_allowed_routine_keys,
    normalize_routine_key,
)
from app.services.gpt_service import (
    ALLOWED_TYPES_BY_SLOT,
    BEHAVIOR_HISTORY_WINDOW,
    build_behavior_adaptation_summary_from_history,
)


MISSION_TYPE_LABELS = {
    "A1_STEP_TARGET": "걸음형",
    "A2_ACTIVE_KCAL_TARGET": "활동칼로리형",
    "B1_TIMER_STRETCH": "스트레칭형",
    "B2_SLEEP_PREP": "휴식준비형",
    "B3_ROUTINE_CHECK": "체크형 루틴",
    "C1_HEALTH_CHECKIN": "기록형",
}

MISSION_EVENT_STARTED = "started"
MISSION_EVENT_COMPLETED = "completed"
MISSION_EVENT_REFRESHED = "refreshed"
MISSION_EVENT_RESOLVED_TYPES = {MISSION_EVENT_COMPLETED, MISSION_EVENT_REFRESHED}
MISSION_EVENT_ALLOWED_TYPES = {
    MISSION_EVENT_STARTED,
    MISSION_EVENT_COMPLETED,
    MISSION_EVENT_REFRESHED,
}


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _empty_type_metrics() -> Dict[str, Any]:
    return {
        "generated_count": 0,
        "started_count": 0,
        "completed_count": 0,
        "refreshed_count": 0,
        "completion_rate": 0.0,
        "refresh_rate": 0.0,
    }


def serialize_resolved_mission_history_item(mission: UserMission) -> Dict[str, Any]:
    return {
        "mission_id": mission.id,
        "slot_code": mission.slot_code,
        "mission_type": mission.mission_type,
        "status": mission.status,
        "started_at": mission.started_at.isoformat() if mission.started_at else None,
        "generation_source": mission.generation_source,
        "updated_at": mission.updated_at.isoformat() if mission.updated_at else None,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "source": "user_missions_legacy",
    }


def serialize_resolved_event_history_item(event: UserMissionEvent) -> Dict[str, Any]:
    meta = event.event_meta_json or {}
    started_at = meta.get("started_at")
    return {
        "mission_id": event.mission_id,
        "event_id": event.id,
        "slot_code": event.slot_code,
        "mission_type": event.mission_type,
        "status": event.event_type,
        "started_at": started_at,
        "generation_source": event.generation_source,
        "updated_at": event.created_at.isoformat() if event.created_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "params": event.params_json or {},
        "progress": event.progress_json or {},
        "fallback_used": bool(event.fallback_used),
        "consecutive_same_type_count": int(event.consecutive_same_type_count or 1),
        "source": "user_mission_events",
    }


def build_pending_event_history_item(
    mission: UserMission,
    event_type: str,
    *,
    event_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta = dict(event_meta or {})
    if mission.started_at and not meta.get("started_at"):
        meta["started_at"] = mission.started_at.isoformat()

    return {
        "mission_id": mission.id,
        "event_id": None,
        "slot_code": mission.slot_code,
        "mission_type": mission.mission_type,
        "status": event_type,
        "started_at": meta.get("started_at"),
        "generation_source": mission.generation_source,
        "updated_at": datetime.utcnow().isoformat(),
        "created_at": datetime.utcnow().isoformat(),
        "params": mission.params_json or {},
        "progress": mission.progress_json or {},
        "fallback_used": bool(mission.fallback_reason or mission.generation_provider == "server_fallback"),
        "consecutive_same_type_count": 1,
        "source": "pending_event",
    }


def _dedupe_history_by_mission_and_status(
    history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for item in history:
        mission_id = item.get("mission_id")
        if mission_id is not None:
            key = ("mission", mission_id, item.get("status"))
        else:
            key = ("event", item.get("event_id"), item.get("status"), item.get("created_at"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def get_resolved_mission_event_history(
    db: Session,
    user_id: int,
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    query = (
        db.query(UserMissionEvent)
        .filter(UserMissionEvent.user_id == user_id)
        .filter(UserMissionEvent.event_type.in_(list(MISSION_EVENT_RESOLVED_TYPES)))
        .order_by(UserMissionEvent.created_at.desc(), UserMissionEvent.id.desc())
    )

    if limit:
        query = query.limit(limit)

    return [serialize_resolved_event_history_item(row) for row in query.all()]


def _get_legacy_resolved_mission_history(
    db: Session,
    user_id: int,
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    query = (
        db.query(UserMission)
        .filter(UserMission.user_id == user_id)
        .filter(UserMission.status.in_(["completed", "refreshed"]))
        .order_by(UserMission.updated_at.desc(), UserMission.id.desc())
    )

    if limit:
        query = query.limit(limit)

    return [serialize_resolved_mission_history_item(row) for row in query.all()]


def get_resolved_mission_history(
    db: Session,
    user_id: int,
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    개인화 행동 분석용 resolved history를 반환한다.

    4차 작업 이후에는 user_mission_events를 우선 반영하되,
    이벤트 로그가 생기기 전 완료/새로고침된 기존 미션도 함께 사용한다.
    """
    event_history = get_resolved_mission_event_history(db, user_id, limit=limit)
    event_mission_ids = {
        item.get("mission_id")
        for item in event_history
        if item.get("mission_id") is not None
    }

    legacy_limit = None if limit is None else max(limit * 2, limit)
    legacy_history = _get_legacy_resolved_mission_history(
        db,
        user_id,
        limit=legacy_limit,
    )
    legacy_history = [
        item
        for item in legacy_history
        if item.get("mission_id") not in event_mission_ids
    ]

    combined = _dedupe_history_by_mission_and_status(event_history + legacy_history)
    if limit:
        return combined[:limit]
    return combined


def get_behavior_summary_with_pending_event(
    db: Session,
    user_id: int,
    *,
    pending_event: Optional[Dict[str, Any]] = None,
    recent_window_size: int = BEHAVIOR_HISTORY_WINDOW,
) -> Dict[str, Any]:
    """
    아직 DB에 확정 저장하지 않은 completed/refreshed 이벤트까지 임시 반영한 행동 요약.

    refresh/complete 직후 새 미션을 만들 때 현재 행동을 바로 반영하기 위해 사용한다.
    """
    recent_history = get_resolved_mission_history(db, user_id, limit=recent_window_size)
    cumulative_history = get_resolved_mission_history(db, user_id, limit=None)

    if pending_event and pending_event.get("status") in MISSION_EVENT_RESOLVED_TYPES:
        recent_history = _dedupe_history_by_mission_and_status([pending_event] + recent_history)
        cumulative_history = _dedupe_history_by_mission_and_status([pending_event] + cumulative_history)

    payload = build_behavior_profile_payload(
        recent_history=recent_history[: max(recent_window_size, 1)],
        cumulative_history=cumulative_history,
        recent_window_size=recent_window_size,
    )
    summary = payload["effective_behavior_json"]
    summary["event_profile_preview"] = {
        "has_pending_event": bool(pending_event),
        "pending_event_type": pending_event.get("status") if pending_event else None,
        "source": "user_mission_events_with_pending" if pending_event else "user_mission_events",
    }
    return summary


def calculate_consecutive_same_type_count(
    db: Session,
    user_id: int,
    mission_type: Optional[str],
    *,
    limit: int = 20,
) -> int:
    if not mission_type:
        return 1

    rows = (
        db.query(UserMission)
        .filter(UserMission.user_id == user_id)
        .order_by(UserMission.created_at.desc(), UserMission.id.desc())
        .limit(max(limit, 1))
        .all()
    )

    count = 0
    for row in rows:
        if row.mission_type == mission_type:
            count += 1
            continue
        break

    return max(count, 1)


def log_mission_event(
    db: Session,
    *,
    user_id: int,
    mission: UserMission,
    event_type: str,
    event_meta: Optional[Dict[str, Any]] = None,
) -> UserMissionEvent:
    """started/completed/refreshed 사용자 행동 이벤트를 저장한다."""
    normalized_event_type = str(event_type or "").strip().lower()
    if normalized_event_type not in MISSION_EVENT_ALLOWED_TYPES:
        raise ValueError(f"지원하지 않는 미션 이벤트 타입입니다: {event_type}")

    # 같은 미션의 같은 이벤트를 중복 저장하지 않는다.
    existing = (
        db.query(UserMissionEvent)
        .filter(UserMissionEvent.user_id == user_id)
        .filter(UserMissionEvent.mission_id == mission.id)
        .filter(UserMissionEvent.event_type == normalized_event_type)
        .order_by(UserMissionEvent.created_at.desc(), UserMissionEvent.id.desc())
        .first()
    )
    if existing:
        return existing

    meta = dict(event_meta or {})
    if mission.started_at and not meta.get("started_at"):
        meta["started_at"] = mission.started_at.isoformat()
    if mission.completed_at and not meta.get("completed_at"):
        meta["completed_at"] = mission.completed_at.isoformat()

    fallback_used = bool(
        mission.fallback_reason
        or mission.generation_provider == "server_fallback"
        or (mission.generation_meta_json or {}).get("provider") == "server_fallback"
    )

    event = UserMissionEvent(
        user_id=user_id,
        mission_id=mission.id,
        event_type=normalized_event_type,
        slot_code=mission.slot_code,
        mission_type=mission.mission_type,
        mission_status_after=mission.status,
        params_json=mission.params_json or {},
        progress_json=mission.progress_json or {},
        event_meta_json=meta,
        reason=mission.reason,
        generation_source=mission.generation_source,
        generation_provider=mission.generation_provider,
        fallback_used=fallback_used,
        consecutive_same_type_count=calculate_consecutive_same_type_count(
            db,
            user_id,
            mission.mission_type,
        ),
    )
    db.add(event)
    return event


def _build_type_score_entry(
    mission_type: str,
    recent_metrics: Dict[str, Any],
    cumulative_metrics: Dict[str, Any],
    *,
    overall_confidence: str,
) -> Dict[str, Any]:
    recent_completion_rate = float(recent_metrics.get("completion_rate", 0.0) or 0.0)
    recent_refresh_rate = float(recent_metrics.get("refresh_rate", 0.0) or 0.0)
    cumulative_completion_rate = float(cumulative_metrics.get("completion_rate", 0.0) or 0.0)
    cumulative_refresh_rate = float(cumulative_metrics.get("refresh_rate", 0.0) or 0.0)

    recent_completed = int(recent_metrics.get("completed_count", 0) or 0)
    recent_refreshed = int(recent_metrics.get("refreshed_count", 0) or 0)
    cumulative_completed = int(cumulative_metrics.get("completed_count", 0) or 0)
    cumulative_refreshed = int(cumulative_metrics.get("refreshed_count", 0) or 0)

    recent_score = (
        (recent_completion_rate * 100.0)
        - (recent_refresh_rate * 95.0)
        + min(recent_completed * 6, 18)
        - min(recent_refreshed * 6, 18)
    )
    cumulative_score = (
        (cumulative_completion_rate * 70.0)
        - (cumulative_refresh_rate * 55.0)
        + min(cumulative_completed * 2, 12)
        - min(cumulative_refreshed * 2, 12)
    )
    preference_score = int(round((recent_score * 0.7) + (cumulative_score * 0.3)))
    preference_score = _clamp(preference_score, -100, 100)

    balance = (
        (recent_completion_rate - recent_refresh_rate) * 1.4
        + (cumulative_completion_rate - cumulative_refresh_rate) * 0.6
    )

    if recent_completed + recent_refreshed < 2:
        difficulty_signal = 0
    elif balance >= 0.95 and recent_completed >= 2:
        difficulty_signal = 2
    elif balance >= 0.35:
        difficulty_signal = 1
    elif balance <= -0.95 and recent_refreshed >= 2:
        difficulty_signal = -2
    elif balance <= -0.35:
        difficulty_signal = -1
    else:
        difficulty_signal = 0

    if overall_confidence == "low" and abs(difficulty_signal) > 1:
        difficulty_signal = 1 if difficulty_signal > 0 else -1

    return {
        "label": MISSION_TYPE_LABELS.get(mission_type, mission_type),
        "recent": recent_metrics,
        "cumulative": cumulative_metrics,
        "preference_score": preference_score,
        "difficulty_signal": difficulty_signal,
        "confidence": overall_confidence,
    }


def _build_confidence(
    recent_resolved_count: int,
    total_resolved_count: int,
) -> str:
    if total_resolved_count >= 18 and recent_resolved_count >= 6:
        return "high"
    if total_resolved_count >= 8 and recent_resolved_count >= 3:
        return "medium"
    return "low"


def _difficulty_signal_to_bias(signal: int) -> str:
    if signal >= 1:
        return "up"
    if signal <= -1:
        return "down"
    return "neutral"


def build_b3_routine_rotation_context(
    recent_history: List[Dict[str, Any]],
    *,
    block_unique_count: int = 2,
    recent_limit: int = 6,
) -> Dict[str, Any]:
    """최근 B3 루틴 반복을 줄이기 위한 routine_key 회전 컨텍스트를 만든다.

    recent_history는 최신순이라고 가정한다. completed/refreshed 이벤트의 params_json을
    기준으로 최근 나온 B3 routine_key를 수집하고, 가장 최근에 나온 고유 루틴 1~2개를
    다음 생성에서 blocked_routine_keys로 내려준다.
    """

    ordered_keys: List[str] = []
    counts: Dict[str, int] = {}

    for item in recent_history:
        if str(item.get("slot_code") or "") != "B":
            continue
        if str(item.get("mission_type") or "") != "B3_ROUTINE_CHECK":
            continue
        params = item.get("params") or {}
        routine_key = normalize_routine_key(params.get("routine_key") or params.get("routine_name"))
        if not routine_key:
            continue
        counts[routine_key] = counts.get(routine_key, 0) + 1
        if routine_key not in ordered_keys:
            ordered_keys.append(routine_key)
        if len(ordered_keys) >= max(recent_limit, 1):
            break

    blocked_keys = ordered_keys[: max(0, block_unique_count)]
    allowed_keys = get_allowed_routine_keys()
    preferred_keys = [key for key in allowed_keys if key not in set(blocked_keys)]

    return {
        "source": "user_mission_events_recent_b3",
        "recent_routine_keys": ordered_keys,
        "blocked_routine_keys": blocked_keys,
        "preferred_routine_keys": preferred_keys[:6],
        "recent_routine_counts": counts,
        "block_unique_count": block_unique_count,
        "rotation_rule": "다음 B3 루틴은 blocked_routine_keys와 다른 routine_key를 우선 사용합니다.",
        "has_recent_b3_history": bool(ordered_keys),
    }


def _build_slot_notes(
    *,
    slot_code: str,
    preferred_types: List[str],
    discouraged_types: List[str],
    difficulty_bias: str,
    confidence: str,
) -> List[str]:
    notes: List[str] = []
    if preferred_types:
        labels = [MISSION_TYPE_LABELS.get(item, item) for item in preferred_types]
        notes.append(f"최근 {slot_code} 슬롯에서 잘 이어진 유형: {', '.join(labels)}")
    if discouraged_types:
        labels = [MISSION_TYPE_LABELS.get(item, item) for item in discouraged_types]
        notes.append(f"최근 {slot_code} 슬롯에서 비중을 낮춘 유형: {', '.join(labels)}")
    if difficulty_bias == "up":
        notes.append("최근 달성 흐름을 반영해 난이도를 조금 높여도 괜찮아요.")
    elif difficulty_bias == "down":
        notes.append("부담 없이 이어가기 좋도록 난이도를 조금 낮춰 반영했어요.")
    elif confidence == "low":
        notes.append("아직 누적 데이터가 적어 난이도는 중립으로 유지하고 있어요.")
    return notes


def build_behavior_profile_payload(
    *,
    recent_history: List[Dict[str, Any]],
    cumulative_history: List[Dict[str, Any]],
    recent_window_size: int = BEHAVIOR_HISTORY_WINDOW,
) -> Dict[str, Any]:
    recent_summary = build_behavior_adaptation_summary_from_history(
        recent_history,
        history_window_size=recent_window_size,
    )
    cumulative_summary = build_behavior_adaptation_summary_from_history(
        cumulative_history,
        history_window_size=max(len(cumulative_history), 1),
    )

    recent_resolved_count = len(recent_history)
    total_resolved_count = len(cumulative_history)
    overall_confidence = _build_confidence(recent_resolved_count, total_resolved_count)

    type_scores: Dict[str, Dict[str, Any]] = {}
    effective_summary = deepcopy(recent_summary)
    effective_summary["history_window_size"] = recent_window_size
    effective_summary["resolved_count"] = recent_resolved_count
    effective_summary["total_resolved_count"] = total_resolved_count
    effective_summary["confidence"] = overall_confidence
    effective_summary["source"] = "behavior_profile_v2"

    difficulty_tendency: Dict[str, Any] = {}
    b3_rotation_context = build_b3_routine_rotation_context(recent_history)
    effective_summary["b3_routine_rotation"] = b3_rotation_context

    for slot_code, allowed_types in ALLOWED_TYPES_BY_SLOT.items():
        recent_slot = (recent_summary.get("slots") or {}).get(slot_code, {}) or {}
        cumulative_slot = (cumulative_summary.get("slots") or {}).get(slot_code, {}) or {}

        slot_type_scores: Dict[str, Any] = {}
        positive_candidates: List[tuple[str, int]] = []
        negative_candidates: List[tuple[str, int]] = []
        difficulty_bucket: List[int] = []

        for mission_type in allowed_types:
            recent_metrics = (recent_slot.get("types") or {}).get(mission_type) or _empty_type_metrics()
            cumulative_metrics = (cumulative_slot.get("types") or {}).get(mission_type) or _empty_type_metrics()
            score_entry = _build_type_score_entry(
                mission_type,
                recent_metrics,
                cumulative_metrics,
                overall_confidence=overall_confidence,
            )
            slot_type_scores[mission_type] = score_entry

            preference_score = int(score_entry["preference_score"])
            if preference_score >= 18:
                positive_candidates.append((mission_type, preference_score))
            if preference_score <= -18:
                negative_candidates.append((mission_type, preference_score))

            difficulty_bucket.append(int(score_entry["difficulty_signal"]))

        preferred_types = [mission_type for mission_type, _ in sorted(positive_candidates, key=lambda item: (-item[1], item[0]))[:2]]
        discouraged_types = [mission_type for mission_type, _ in sorted(negative_candidates, key=lambda item: (item[1], item[0]))[:2]]
        discouraged_types = [item for item in discouraged_types if item not in preferred_types]

        recent_slot_bias = str(recent_slot.get("difficulty_bias") or "neutral")
        score_signal = 0
        if difficulty_bucket:
            avg_signal = sum(difficulty_bucket) / len(difficulty_bucket)
            if avg_signal >= 0.75:
                score_signal = 2
            elif avg_signal >= 0.25:
                score_signal = 1
            elif avg_signal <= -0.75:
                score_signal = -2
            elif avg_signal <= -0.25:
                score_signal = -1

        if recent_slot_bias == "up":
            score_signal = max(score_signal, 1)
        elif recent_slot_bias == "down":
            score_signal = min(score_signal, -1)

        difficulty_bias = _difficulty_signal_to_bias(score_signal)
        difficulty_tendency[slot_code] = {
            "bias": difficulty_bias,
            "signal": score_signal,
        }

        slot_confidence = "low"
        slot_generated = int(cumulative_slot.get("generated_count", 0) or 0)
        if slot_generated >= 6 and recent_slot.get("generated_count", 0) >= 3:
            slot_confidence = "high"
        elif slot_generated >= 3:
            slot_confidence = "medium"

        current_slot = (effective_summary.get("slots") or {}).setdefault(slot_code, {})
        current_slot["preferred_types"] = preferred_types
        current_slot["discouraged_types"] = discouraged_types
        current_slot["difficulty_bias"] = difficulty_bias
        current_slot["difficulty_signal"] = score_signal
        current_slot["confidence"] = slot_confidence
        current_slot["preference_scores"] = {
            mission_type: entry["preference_score"] for mission_type, entry in slot_type_scores.items()
        }
        current_slot["cumulative"] = cumulative_slot
        if slot_code == "B":
            current_slot["routine_rotation"] = b3_rotation_context
        current_slot["notes"] = _build_slot_notes(
            slot_code=slot_code,
            preferred_types=preferred_types,
            discouraged_types=discouraged_types,
            difficulty_bias=difficulty_bias,
            confidence=slot_confidence,
        )

        type_scores[slot_code] = slot_type_scores

    top_positive: List[tuple[str, int]] = []
    top_negative: List[tuple[str, int]] = []
    for slot_scores in type_scores.values():
        for mission_type, entry in slot_scores.items():
            score = int(entry.get("preference_score", 0) or 0)
            if score >= 18:
                top_positive.append((mission_type, score))
            elif score <= -18:
                top_negative.append((mission_type, score))

    top_preferred_types = [
        mission_type
        for mission_type, _ in sorted(top_positive, key=lambda item: (-item[1], item[0]))[:3]
    ]
    top_avoided_types = [
        mission_type
        for mission_type, _ in sorted(top_negative, key=lambda item: (item[1], item[0]))[:3]
    ]

    preferred_styles = [
        MISSION_TYPE_LABELS.get(mission_type, mission_type)
        for mission_type in top_preferred_types
    ]
    avoided_styles = [
        MISSION_TYPE_LABELS.get(mission_type, mission_type)
        for mission_type in top_avoided_types
    ]

    adaptation_summary = {
        "preferred_styles": preferred_styles,
        "avoided_styles": avoided_styles,
        "difficulty_tendency": {
            slot_code: info["bias"] for slot_code, info in difficulty_tendency.items()
        },
        "confidence": overall_confidence,
        "top_preferred_types": top_preferred_types,
        "top_avoided_types": top_avoided_types,
        "top_preferred_styles": preferred_styles,
        "top_avoided_styles": avoided_styles,
        "recent_resolved_count": recent_resolved_count,
        "total_resolved_count": total_resolved_count,
    }

    return {
        "behavior_version": 2,
        "recent_window_size": recent_window_size,
        "recent_resolved_count": recent_resolved_count,
        "total_resolved_count": total_resolved_count,
        "adaptation_confidence": overall_confidence,
        "recent_summary_json": recent_summary,
        "cumulative_summary_json": cumulative_summary,
        "type_scores_json": type_scores,
        "effective_behavior_json": effective_summary,
        "adaptation_summary_json": adaptation_summary,
        "preferred_slot_a_types": ((effective_summary.get("slots") or {}).get("A", {}) or {}).get("preferred_types", []),
        "preferred_slot_b_types": ((effective_summary.get("slots") or {}).get("B", {}) or {}).get("preferred_types", []),
        "preferred_slot_c_types": ((effective_summary.get("slots") or {}).get("C", {}) or {}).get("preferred_types", []),
        "discouraged_slot_a_types": ((effective_summary.get("slots") or {}).get("A", {}) or {}).get("discouraged_types", []),
        "discouraged_slot_b_types": ((effective_summary.get("slots") or {}).get("B", {}) or {}).get("discouraged_types", []),
        "discouraged_slot_c_types": ((effective_summary.get("slots") or {}).get("C", {}) or {}).get("discouraged_types", []),
        "slot_a_difficulty_bias": ((effective_summary.get("slots") or {}).get("A", {}) or {}).get("difficulty_bias", "neutral"),
        "slot_b_difficulty_bias": ((effective_summary.get("slots") or {}).get("B", {}) or {}).get("difficulty_bias", "neutral"),
        "slot_c_difficulty_bias": ((effective_summary.get("slots") or {}).get("C", {}) or {}).get("difficulty_bias", "neutral"),
    }


def upsert_user_behavior_profile(
    db: Session,
    user_id: int,
    *,
    recent_window_size: int = BEHAVIOR_HISTORY_WINDOW,
) -> UserMissionBehaviorProfile:
    recent_history = get_resolved_mission_history(
        db,
        user_id,
        limit=recent_window_size,
    )
    cumulative_history = get_resolved_mission_history(db, user_id, limit=None)

    payload = build_behavior_profile_payload(
        recent_history=recent_history,
        cumulative_history=cumulative_history,
        recent_window_size=recent_window_size,
    )

    profile = (
        db.query(UserMissionBehaviorProfile)
        .filter(UserMissionBehaviorProfile.user_id == user_id)
        .first()
    )
    if not profile:
        profile = UserMissionBehaviorProfile(user_id=user_id)

    profile.behavior_version = payload["behavior_version"]
    profile.recent_window_size = payload["recent_window_size"]
    profile.recent_resolved_count = payload["recent_resolved_count"]
    profile.total_resolved_count = payload["total_resolved_count"]
    profile.adaptation_confidence = payload["adaptation_confidence"]

    profile.preferred_slot_a_types = payload["preferred_slot_a_types"]
    profile.preferred_slot_b_types = payload["preferred_slot_b_types"]
    profile.preferred_slot_c_types = payload["preferred_slot_c_types"]
    profile.discouraged_slot_a_types = payload["discouraged_slot_a_types"]
    profile.discouraged_slot_b_types = payload["discouraged_slot_b_types"]
    profile.discouraged_slot_c_types = payload["discouraged_slot_c_types"]
    profile.slot_a_difficulty_bias = payload["slot_a_difficulty_bias"]
    profile.slot_b_difficulty_bias = payload["slot_b_difficulty_bias"]
    profile.slot_c_difficulty_bias = payload["slot_c_difficulty_bias"]

    profile.recent_summary_json = payload["recent_summary_json"]
    profile.cumulative_summary_json = payload["cumulative_summary_json"]
    profile.type_scores_json = payload["type_scores_json"]
    profile.effective_behavior_json = payload["effective_behavior_json"]
    profile.adaptation_summary_json = payload["adaptation_summary_json"]

    db.add(profile)
    return profile


def get_latest_resolved_mission_timestamp(
    db: Session,
    user_id: int,
) -> Optional[datetime]:
    latest_event = (
        db.query(UserMissionEvent)
        .filter(UserMissionEvent.user_id == user_id)
        .filter(UserMissionEvent.event_type.in_(list(MISSION_EVENT_RESOLVED_TYPES)))
        .order_by(UserMissionEvent.created_at.desc(), UserMissionEvent.id.desc())
        .first()
    )
    event_at = latest_event.created_at if latest_event and latest_event.created_at else None

    latest_mission = (
        db.query(UserMission)
        .filter(UserMission.user_id == user_id)
        .filter(UserMission.status.in_(["completed", "refreshed"]))
        .order_by(UserMission.updated_at.desc(), UserMission.id.desc())
        .first()
    )
    mission_at = latest_mission.updated_at if latest_mission and latest_mission.updated_at else None

    if event_at and mission_at:
        return max(event_at, mission_at)
    return event_at or mission_at


def ensure_user_behavior_profile(
    db: Session,
    user_id: int,
    *,
    lazy_refresh: bool = True,
) -> UserMissionBehaviorProfile:
    profile = (
        db.query(UserMissionBehaviorProfile)
        .filter(UserMissionBehaviorProfile.user_id == user_id)
        .first()
    )

    if not profile:
        return upsert_user_behavior_profile(db, user_id)

    if profile.behavior_version != 2:
        return upsert_user_behavior_profile(db, user_id)

    if not profile.effective_behavior_json or not profile.adaptation_summary_json:
        return upsert_user_behavior_profile(db, user_id)

    if lazy_refresh:
        latest_resolved_at = get_latest_resolved_mission_timestamp(db, user_id)
        if latest_resolved_at and (
            profile.updated_at is None or latest_resolved_at >= profile.updated_at
        ):
            return upsert_user_behavior_profile(db, user_id)

    return profile


def get_effective_behavior_summary(
    db: Session,
    user_id: int,
    *,
    lazy_refresh: bool = True,
) -> Dict[str, Any]:
    profile = ensure_user_behavior_profile(
        db,
        user_id,
        lazy_refresh=lazy_refresh,
    )
    return profile.effective_behavior_json or build_behavior_adaptation_summary_from_history([])


def get_public_behavior_summary(
    db: Session,
    user_id: int,
    *,
    lazy_refresh: bool = True,
) -> Dict[str, Any]:
    profile = ensure_user_behavior_profile(
        db,
        user_id,
        lazy_refresh=lazy_refresh,
    )
    summary = dict(profile.adaptation_summary_json or {})
    summary["updated_at"] = profile.updated_at.isoformat() if profile.updated_at else None
    return summary
