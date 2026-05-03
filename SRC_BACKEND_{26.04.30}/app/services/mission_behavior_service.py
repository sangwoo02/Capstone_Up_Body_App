# app/services/mission_behavior_service.py

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.game import UserMissionBehaviorProfile
from app.models.user import UserMission
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
        "slot_code": mission.slot_code,
        "mission_type": mission.mission_type,
        "status": mission.status,
        "started_at": mission.started_at.isoformat() if mission.started_at else None,
        "generation_source": mission.generation_source,
        "updated_at": mission.updated_at.isoformat() if mission.updated_at else None,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
    }


def get_resolved_mission_history(
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
    row = (
        db.query(UserMission)
        .filter(UserMission.user_id == user_id)
        .filter(UserMission.status.in_(["completed", "refreshed"]))
        .order_by(UserMission.updated_at.desc(), UserMission.id.desc())
        .first()
    )
    return row.updated_at if row and row.updated_at else None


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
