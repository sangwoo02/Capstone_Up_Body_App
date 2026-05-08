"""
Shared activity summary service.

History screen and AI mission generation must calculate weekly averages with the same rule.
Activity records are daily snapshots, so if multiple rows exist for the same KST date, the latest row wins.
Missing days are filled with zero and the average denominator is always the number of calendar days in the selected range.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.user import UserActivity

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
ACTIVITY_SUMMARY_VERSION = "activity_summary_kst_calendar_v1_2026_05_06"


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_kst(dt: datetime) -> datetime:
    return to_utc(dt).astimezone(KST)


def kst_date_range_to_utc_bounds(start_date: date, end_date: date) -> Tuple[datetime, datetime]:
    start_local = datetime.combine(start_date, time.min, tzinfo=KST)
    end_local = datetime.combine(end_date, time.max, tzinfo=KST)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def get_current_kst_week_range(base: Optional[datetime] = None) -> Tuple[date, date]:
    """Return Monday~Sunday of the current KST week, matching HistoryPage default range."""
    now_kst = to_kst(base or datetime.now(UTC))
    start = now_kst.date() - timedelta(days=now_kst.weekday())
    return start, start + timedelta(days=6)


def iter_dates(start_date: date, end_date: date) -> Iterable[date]:
    cur = start_date
    while cur <= end_date:
        yield cur
        cur += timedelta(days=1)


def get_activity_records_for_range(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date,
) -> List[UserActivity]:
    start_dt, end_dt = kst_date_range_to_utc_bounds(start_date, end_date)
    return (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user_id)
        .filter(UserActivity.recorded_at >= start_dt)
        .filter(UserActivity.recorded_at <= end_dt)
        .order_by(UserActivity.recorded_at.desc(), UserActivity.id.desc())
        .all()
    )


def pick_latest_record_by_kst_date(records: Iterable[UserActivity]) -> Dict[str, UserActivity]:
    """For daily total snapshots, choose the latest DB row per KST date."""
    latest_by_date: Dict[str, UserActivity] = {}

    def _sort_key(r: UserActivity):
        rec_dt = r.recorded_at or datetime.min.replace(tzinfo=UTC)
        try:
            ts = to_utc(rec_dt).timestamp()
        except Exception:
            ts = 0
        return (ts, int(getattr(r, "id", 0) or 0))

    for rec in sorted(records or [], key=_sort_key, reverse=True):
        rec_dt = rec.recorded_at or datetime.now(UTC)
        date_key = to_kst(rec_dt).date().isoformat()
        if date_key not in latest_by_date:
            latest_by_date[date_key] = rec
    return latest_by_date


def build_activity_window_payload(
    records: Iterable[UserActivity],
    start_date: date,
    end_date: date,
) -> Dict[str, Any]:
    latest_by_date = pick_latest_record_by_kst_date(records)
    today_key = datetime.now(KST).date().isoformat()

    activity_history: List[Dict[str, Any]] = []
    actual_record_days = 0

    for day in iter_dates(start_date, end_date):
        key = day.isoformat()
        rec = latest_by_date.get(key)
        if rec is not None:
            actual_record_days += 1
        activity_history.append(
            {
                "date": key,
                "steps": int((rec.steps if rec is not None else 0) or 0),
                "calories": float((rec.calories if rec is not None else 0) or 0),
                "sleep_minutes": int((rec.sleep_minutes if rec is not None and rec.sleep_minutes is not None else 0) or 0),
            }
        )

    denominator = max(len(activity_history), 1)
    total_steps = sum(int(item["steps"] or 0) for item in activity_history)
    total_kcal = sum(float(item["calories"] or 0) for item in activity_history)
    sleep_values = [int(item["sleep_minutes"] or 0) for item in activity_history]

    today_item = next((item for item in activity_history if item["date"] == today_key), None)
    latest_record = next(iter(latest_by_date.values()), None) if latest_by_date else None

    summary = {
        "summary_version": ACTIVITY_SUMMARY_VERSION,
        "average_basis": "kst_calendar_week_7_days",
        "average_basis_label": "선택된 주(월~일) 7일 고정 평균",
        "range_start": start_date.isoformat(),
        "range_end": end_date.isoformat(),
        "average_denominator_days": denominator,
        "actual_record_days": actual_record_days,
        "avg_steps_7d": round(total_steps / denominator),
        "avg_active_kcal_7d": round(total_kcal / denominator),
        "today_steps": int((today_item or {}).get("steps", 0) or 0),
        "today_active_kcal": int(round(float((today_item or {}).get("calories", 0) or 0))),
        "sleep_minutes_latest": int(getattr(latest_record, "sleep_minutes", 0) or 0) if latest_record is not None else 0,
        "avg_sleep_minutes_7d": round(sum(sleep_values) / denominator) if sleep_values else 0,
    }

    public_history = [
        {"date": item["date"], "steps": item["steps"], "calories": item["calories"]}
        for item in activity_history
    ]

    return {
        "activity_history": public_history,
        "activity_summary": summary,
        "latest_activity": latest_record,
        "latest_by_date": latest_by_date,
    }


def build_current_week_activity_window(db: Session, user_id: int) -> Dict[str, Any]:
    start_date, end_date = get_current_kst_week_range()
    records = get_activity_records_for_range(db, user_id, start_date, end_date)
    return build_activity_window_payload(records, start_date, end_date)


def build_activity_summary_from_records(
    records: Iterable[UserActivity],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    if not start_date or not end_date:
        start_date, end_date = get_current_kst_week_range()
    return build_activity_window_payload(records, start_date, end_date)["activity_summary"]
