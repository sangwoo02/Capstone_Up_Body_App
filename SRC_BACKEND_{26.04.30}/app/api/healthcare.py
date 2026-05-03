from fastapi import APIRouter, Depends, HTTPException, Query
import logging
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime, date, timezone, time
from zoneinfo import ZoneInfo
from typing import Optional, Any, Dict, Tuple

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User, UserInbody, UserActivity, UserMission, UserWeightHistory
from app.models.standard import HealthStandard
from app.services.kosis_api import KosisHealthStatsService

router = APIRouter(prefix="/healthcare", tags=["Healthcare"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc


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


# ---------- helpers ----------

def calc_age(birth_date: Optional[date]) -> int:
    if not birth_date:
        return 25
    today = date.today()
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return max(age, 0)


def age_to_band(age: int) -> int:
    if age < 10:
        return 10
    return (age // 10) * 10

def normalize_age_group(age: Optional[int]) -> Optional[int]:
    if age is None:
        return None

    try:
        age = int(age)
    except (TypeError, ValueError):
        return None

    age_group = (age // 10) * 10

    if age_group < 10:
        age_group = 10
    if age_group > 60:
        age_group = 60

    return age_group

def bmi(height_cm: float, weight_kg: float) -> float:
    h_m = height_cm / 100.0
    if h_m <= 0:
        return 0.0
    return round(weight_kg / (h_m * h_m), 1)


def normal_weight_range_by_bmi(height_cm: Optional[float]) -> Optional[Dict[str, Any]]:
    """
    사용자 키 기준 한국 성인 BMI 18.5~22.9 참고 체중 범위.

    공공데이터의 avg_weight는 평균 참고값일 뿐 정상 체중 범위가 아니다.
    프론트가 두 값을 혼동하지 않도록 /healthcare/average 응답에 별도 필드로 내려준다.
    """

    try:
        height = float(height_cm or 0)
    except (TypeError, ValueError):
        return None

    if height <= 0:
        return None

    h_m = height / 100.0

    return {
        "min": round(18.5 * h_m * h_m, 1),
        "max": round(22.9 * h_m * h_m, 1),
        "avg": round(20.7 * h_m * h_m, 1),
        "basis": "korean_adult_bmi_18.5_22.9",
    }


def bmr(height_cm: float, weight_kg: float, age: int, gender: str) -> float:
    g = (gender or "").lower()
    if g == "female":
        val = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    else:
        val = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    return round(val, 0)


def body_fat_percent(height_cm: float, weight_kg: float, age: int, gender: str) -> float:
    b = bmi(height_cm, weight_kg)
    sex = 0 if (gender or "").lower() == "female" else 1
    bf = 1.20 * b + 0.23 * age - 10.8 * sex - 5.4
    return round(max(bf, 0.0), 1)


def calories_from_steps(steps: int) -> float:
    return round(max(steps, 0) * 0.04, 1)


def upsert_latest_inbody(
    db: Session,
    user: User,
    *,
    height_cm: float,
    weight_kg: float,
    gender: str,
    goal: str,
    source: str,
) -> UserInbody:
    age = calc_age(user.birth_date)
    bmi_val = bmi(height_cm, weight_kg)
    bmr_val = bmr(height_cm, weight_kg, age, gender)
    bf_val = body_fat_percent(height_cm, weight_kg, age, gender)

    rec = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )

    if rec:
        rec.name = user.nickname or "사용자"
        rec.age = age
        rec.gender = gender
        rec.height = float(height_cm)
        rec.weight = float(weight_kg)
        rec.goal = goal
        rec.bmi = float(bmi_val)
        rec.bmr = float(bmr_val)
        rec.body_fat = float(bf_val)
        rec.updated_at = datetime.now(UTC)
        rec.source = source
        if rec.muscle_mass is None:
            rec.muscle_mass = 0.0
        db.add(rec)
        return rec

    rec = UserInbody(
        user_id=user.id,
        name=user.nickname or "사용자",
        age=age,
        gender=gender,
        height=float(height_cm),
        weight=float(weight_kg),
        body_fat=float(bf_val),
        muscle_mass=0.0,
        goal=goal,
        bmi=float(bmi_val),
        bmr=float(bmr_val),
        source=source,
    )
    db.add(rec)
    return rec


def upsert_latest_activity(
    db: Session,
    user: User,
    *,
    steps: int,
    source: Optional[str] = None,
) -> UserActivity:
    cal = calories_from_steps(steps)

    rec = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.recorded_at.desc())
        .first()
    )

    if rec:
        rec.steps = int(steps)
        rec.calories = float(cal)
        rec.source = source
        rec.recorded_at = datetime.now(UTC)
        db.add(rec)
        return rec

    rec = UserActivity(
        user_id=user.id,
        steps=int(steps),
        calories=float(cal),
        source=source,
        recorded_at=datetime.now(UTC),
    )
    db.add(rec)
    return rec


def log_weight_history(
    db: Session,
    user: User,
    *,
    weight_kg: float,
    source: str,
) -> UserWeightHistory:
    latest = (
        db.query(UserWeightHistory)
        .filter(UserWeightHistory.user_id == user.id)
        .order_by(UserWeightHistory.recorded_at.desc())
        .first()
    )

    if latest and float(latest.weight) == float(weight_kg):
        return latest

    rec = UserWeightHistory(
        user_id=user.id,
        weight=float(weight_kg),
        source=source,
        recorded_at=datetime.now(UTC),
    )
    db.add(rec)
    return rec


def upsert_today_activity(
    db: Session,
    user: User,
    *,
    steps: int,
    active_kcal: Optional[float] = None,
    source: Optional[str] = None,
) -> UserActivity:
    """
    오늘 활동도 KST 하루 기준으로 upsert.

    Health Connect/Samsung Health의 일일 데이터는 자정 이후 0부터 다시
    누적되므로, 앱과 백그라운드 워커는 항상 "오늘 00:00:00 ~ 현재" 범위의
    steps/active_kcal 값을 보내야 한다.
    """
    today_kst = datetime.now(KST).date()
    return upsert_activity_by_date(
        db,
        user,
        target_date=today_kst,
        steps=steps,
        active_kcal=active_kcal,
        source=source,
    )


def upsert_activity_by_date(
    db: Session,
    user: User,
    *,
    target_date: date,
    steps: int,
    active_kcal: Optional[float] = None,
    source: Optional[str] = None,
) -> UserActivity:
    # active_kcal이 들어오면 Health Connect/Samsung Health의 실제 활동 칼로리를 우선 저장한다.
    # 없는 경우에는 기존 로직처럼 걸음수 기반 추정값을 저장한다.
    cal = float(active_kcal) if active_kcal is not None else calories_from_steps(steps)

    start_dt, end_dt = kst_date_range_to_utc_bounds(target_date, target_date)
    target_recorded_at = datetime.combine(target_date, time.min, tzinfo=KST).astimezone(UTC)

    rec = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .filter(UserActivity.recorded_at >= start_dt)
        .filter(UserActivity.recorded_at <= end_dt)
        .order_by(UserActivity.recorded_at.desc())
        .first()
    )

    if rec:
        rec.steps = int(steps)
        rec.calories = float(cal)
        rec.source = source
        rec.recorded_at = target_recorded_at
        db.add(rec)
        return rec

    rec = UserActivity(
        user_id=user.id,
        steps=int(steps),
        calories=float(cal),
        source=source,
        recorded_at=target_recorded_at,
    )
    db.add(rec)
    return rec


# ---------- request/response models ----------

class ManualSaveRequest(BaseModel):
    height: float = Field(..., gt=0)
    weight: float = Field(..., gt=0)
    gender: str = Field(..., pattern="^(male|female)$")
    goal: str


class SyncSaveRequest(BaseModel):
    height_cm: float = Field(..., gt=0)
    weight_kg: float = Field(..., gt=0)
    steps_today: int = Field(0, ge=0)
    active_kcal_today: Optional[float] = Field(None, ge=0)
    gender: str = Field(..., pattern="^(male|female)$")
    goal: str
    source: str = "HealthConnect"


class ActivitySyncRequest(BaseModel):
    steps_today: int = Field(0, ge=0)
    active_kcal_today: Optional[float] = Field(None, ge=0)
    source: str = "HealthConnect"


class DailyStepsItem(BaseModel):
    date: str
    steps: int = Field(0, ge=0)


class SyncHistoryRequest(BaseModel):
    source: str = "HealthConnect"
    daily_steps: list[DailyStepsItem]


class LatestResponse(BaseModel):
    inbody: Optional[Dict[str, Any]] = None
    activity: Optional[Dict[str, Any]] = None
    average: Optional[Dict[str, Any]] = None


class ActivityHistoryItem(BaseModel):
    date: str
    steps: int
    calories: float


class WeightHistoryItem(BaseModel):
    weight: float
    recordedAt: str


class HistoryResponse(BaseModel):
    activity_history: list[ActivityHistoryItem]
    weight_history: list[WeightHistoryItem]


# ---------- endpoints ----------

@router.post("/manual")
async def save_manual(
    req: ManualSaveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inbody_rec = upsert_latest_inbody(
        db, user,
        height_cm=req.height,
        weight_kg=req.weight,
        gender=req.gender,
        goal=req.goal,
        source="manual",
    )

    log_weight_history(
        db, user,
        weight_kg=req.weight,
        source="manual",
    )

    db.commit()
    db.refresh(inbody_rec)

    return {"ok": True, "inbody_id": inbody_rec.id}


@router.post("/sync")
async def sync_from_healthconnect(
    req: SyncSaveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inbody_rec = upsert_latest_inbody(
        db, user,
        height_cm=req.height_cm,
        weight_kg=req.weight_kg,
        gender=req.gender,
        goal=req.goal,
        source=req.source,
    )

    activity_rec = upsert_today_activity(
        db, user,
        steps=req.steps_today,
        active_kcal=req.active_kcal_today,
        source=req.source,
    )

    log_weight_history(
        db, user,
        weight_kg=req.weight_kg,
        source=req.source,
    )

    db.commit()
    db.refresh(inbody_rec)
    db.refresh(activity_rec)

    return {
        "ok": True,
        "saved": {
            "inbody_id": inbody_rec.id,
            "activity_id": activity_rec.id,
        },
    }


@router.post("/sync-activity")
async def sync_today_activity_from_healthconnect(
    req: ActivitySyncRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    00:01 이후 자동/백그라운드 보정 동기화용 엔드포인트.

    React Native 앱 또는 Android WorkManager가 Health Connect에서
    오늘 00:00:00부터 현재 시각까지의 누적 걸음수/활동칼로리만 읽어 보내면,
    서버는 KST 오늘 날짜의 UserActivity를 덮어쓴다.

    이 엔드포인트는 height/weight 없이도 동작하므로, 앱이 꺼져 있을 때의
    백그라운드 동기화가 신체정보 누락 때문에 실패하지 않는다.
    """
    activity_rec = upsert_today_activity(
        db,
        user,
        steps=req.steps_today,
        active_kcal=req.active_kcal_today,
        source=req.source,
    )

    db.commit()
    db.refresh(activity_rec)

    return {
        "ok": True,
        "saved": {
            "activity_id": activity_rec.id,
            "steps_today": activity_rec.steps,
            "active_kcal_today": activity_rec.calories,
            "recorded_at": activity_rec.recorded_at.isoformat()
            if activity_rec.recorded_at
            else None,
        },
    }


@router.post("/sync-history")
async def sync_history_from_healthconnect(
    req: SyncHistoryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    saved_count = 0

    for item in req.daily_steps:
        try:
            target_date = datetime.strptime(item.date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"잘못된 날짜 형식입니다: {item.date}. YYYY-MM-DD 형식을 사용하세요."
            )

        upsert_activity_by_date(
            db,
            user,
            target_date=target_date,
            steps=item.steps,
            source=req.source,
        )
        saved_count += 1

    db.commit()

    return {
        "ok": True,
        "saved_count": saved_count,
    }


@router.get("/latest", response_model=LatestResponse)
async def get_latest(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inbody_rec = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )
    activity_rec = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.recorded_at.desc())
        .first()
    )

    # /healthcare/latest는 프로필/로그인/동기화 직후 최신 사용자 데이터만 가져오는 용도입니다.
    # 공공 평균은 /healthcare/average에서 KOSIS 기준으로 별도 조회하므로,
    # 여기서는 국민체력100 PublicHealthService를 호출하지 않습니다.

    def inbody_dict(r: UserInbody):
        return {
            "id": r.id,
            "user_id": r.user_id,
            "name": r.name,
            "age": r.age,
            "gender": r.gender,
            "height": r.height,
            "weight": r.weight,
            "body_fat": r.body_fat,
            "muscle_mass": r.muscle_mass,
            "goal": r.goal,
            "bmi": r.bmi,
            "bmr": r.bmr,
            "source": r.source,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }

    def act_dict(r: UserActivity):
        return {
            "id": r.id,
            "user_id": r.user_id,
            "steps": r.steps,
            "calories": r.calories,
            "source": r.source,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        }

    return {
        "inbody": inbody_dict(inbody_rec) if inbody_rec else None,
        "activity": act_dict(activity_rec) if activity_rec else None,
        "average": None,
    }


@router.get("/latest-fast")
async def get_latest_fast(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inbody_rec = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )
    activity_rec = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.recorded_at.desc())
        .first()
    )

    def inbody_dict(r: UserInbody):
        return {
            "id": r.id,
            "user_id": r.user_id,
            "name": r.name,
            "age": r.age,
            "gender": r.gender,
            "height": r.height,
            "weight": r.weight,
            "target_weight": r.target_weight,
            "body_fat": r.body_fat,
            "muscle_mass": r.muscle_mass,
            "goal": r.goal,
            "bmi": r.bmi,
            "bmr": r.bmr,
            "source": r.source,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }

    def act_dict(r: UserActivity):
        return {
            "id": r.id,
            "user_id": r.user_id,
            "steps": r.steps,
            "calories": r.calories,
            "source": r.source,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        }

    return {
        "inbody": inbody_dict(inbody_rec) if inbody_rec else None,
        "activity": act_dict(activity_rec) if activity_rec else None,
    }


@router.get("/average")
async def get_average(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inbody_rec = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )

    user_age = calc_age(user.birth_date)

    age_source = (
        user_age
        if user.birth_date
        else inbody_rec.age if inbody_rec and inbody_rec.age is not None else user_age
    )

    band = normalize_age_group(age_source)
    gender = ((inbody_rec.gender if inbody_rec and inbody_rec.gender else "male") or "male").strip().lower()
    normal_weight_range = normal_weight_range_by_bmi(inbody_rec.height if inbody_rec else None)

    logger.info(
        "[HEALTHCARE_AVERAGE] request_start user_id=%s exact_age=%s age_group=%s gender=%s height=%s",
        user.id,
        age_source,
        band,
        gender,
        inbody_rec.height if inbody_rec else None,
    )

    # 1) KOSIS 건강검진통계 우선 사용
    # 평균 신장/체중은 국민체력100 참여자 표본보다 KOSIS 국민건강보험공단 건강검진통계가
    # "국민 통계 평균" 목적에 더 적합하므로, KOSIS 키가 있으면 이 값을 먼저 사용한다.
    kosis_avg = await KosisHealthStatsService.get_average_metrics(
        user_age=age_source,
        user_gender=gender,
    )

    if kosis_avg:
        kosis_meta = kosis_avg.get("_meta") if isinstance(kosis_avg, dict) else None
        average_meta = {
            **(kosis_meta or {}),
            "data_origin": "kosis_health_checkup_live",
            "public_api_called": True,
            "public_api_success": True,
            "is_fallback_value": False,
            "fallback_reason": None,
            "note": "KOSIS 국민건강보험공단 건강검진통계의 성별·연령별 평균 신장/체중을 사용했습니다. BMI는 평균 신장과 평균 체중으로 계산한 참고값이며, 체지방률은 BMI·나이·성별 기반 추정값입니다.",
        }

        logger.info(
            "[HEALTHCARE_AVERAGE] result data_origin=kosis_health_checkup_live public_api_called=true public_api_success=true is_fallback_value=false age_group=%s exact_age=%s gender=%s avg_height=%s avg_weight=%s avg_body_fat=%s avg_bmi=%s",
            band,
            age_source,
            gender,
            kosis_avg.get("avg_height"),
            kosis_avg.get("avg_weight"),
            kosis_avg.get("avg_body_fat"),
            kosis_avg.get("avg_bmi"),
        )

        return {
            "average": {
                "age_group": band,
                "requested_test_age": age_source,
                "gender": gender,
                "avg_height": kosis_avg.get("avg_height"),
                "avg_weight": kosis_avg.get("avg_weight"),
                "avg_body_fat": kosis_avg.get("avg_body_fat"),
                "avg_body_fat_basis": kosis_avg.get("avg_body_fat_basis"),
                "is_body_fat_estimated": kosis_avg.get("is_body_fat_estimated"),
                "avg_bmi": kosis_avg.get("avg_bmi"),
                "sample_count": kosis_avg.get("sample_count"),
                "prescription": kosis_avg.get("prescription"),
                "source": "kosis_health_checkup",
                "data_origin": average_meta["data_origin"],
                "public_api_called": average_meta["public_api_called"],
                "public_api_success": average_meta["public_api_success"],
                "is_fallback_value": average_meta["is_fallback_value"],
                "fallback_reason": average_meta["fallback_reason"],
            },
            "average_meta": average_meta,
            "normal_weight_range": normal_weight_range,
        }

    standard = None
    if band is not None and gender:
        standard = (
            db.query(HealthStandard)
            .filter(HealthStandard.gender == gender)
            .filter(HealthStandard.age_group == band)
            .first()
        )

    # 2) KOSIS가 실패하거나 KOSIS 키가 없으면 health_standards 테이블 사용
    # 이 경로는 공공 API를 실시간 호출하지 않는다. DB에 저장된 기준값을 사용한다.
    if standard:
        avg_height = float(standard.avg_height) if standard.avg_height is not None else None
        avg_weight = float(standard.avg_weight) if standard.avg_weight is not None else None
        avg_body_fat = float(standard.avg_body_fat) if standard.avg_body_fat is not None else None

        avg_bmi = None
        if avg_height is not None and avg_weight is not None and avg_height > 0:
            avg_bmi = round(avg_weight / ((avg_height / 100) ** 2), 1)

        average_meta = {
            "data_origin": "health_standards_db",
            "public_api_called": False,
            "public_api_success": None,
            "is_fallback_value": False,
            "fallback_reason": None,
            "note": "health_standards 테이블에 저장된 평균값을 사용했습니다. 이 요청에서는 공공데이터 API를 실시간 호출하지 않았습니다.",
        }

        logger.info(
            "[HEALTHCARE_AVERAGE] result data_origin=health_standards_db public_api_called=false is_fallback_value=false age_group=%s gender=%s avg_height=%s avg_weight=%s avg_body_fat=%s avg_bmi=%s",
            band,
            gender,
            avg_height,
            avg_weight,
            avg_body_fat,
            avg_bmi,
        )

        return {
            "average": {
                "age_group": band,
                "requested_test_age": age_source,
                "gender": gender,
                "avg_height": avg_height,
                "avg_weight": avg_weight,
                "avg_body_fat": avg_body_fat,
                "avg_bmi": avg_bmi,
                "sample_count": None,
                "prescription": None,
                "source": "health_standards",
                "data_origin": average_meta["data_origin"],
                "public_api_called": average_meta["public_api_called"],
                "is_fallback_value": average_meta["is_fallback_value"],
                "fallback_reason": average_meta["fallback_reason"],
            },
            "average_meta": average_meta,
            "normal_weight_range": normal_weight_range,
        }

    # 3) KOSIS/DB가 없으면 더 이상 국민체력100 공공 API를 fallback으로 호출하지 않습니다.
    # 평균 신장/체중은 KOSIS 기준으로 통일하고, 체지방률은 KOSIS 평균 신장/체중 기반 추정값만 사용합니다.
    average_meta = {
        "data_origin": "unavailable",
        "public_api_called": False,
        "public_api_success": False,
        "is_fallback_value": True,
        "fallback_reason": "kosis_and_health_standards_unavailable",
        "note": "KOSIS 평균값과 health_standards DB 값이 없어 평균값을 제공하지 않았습니다. 국민체력100 공공 API fallback은 사용하지 않습니다.",
    }

    logger.warning(
        "[HEALTHCARE_AVERAGE] result data_origin=unavailable public_api_called=false public_api_success=false is_fallback_value=true fallback_reason=kosis_and_health_standards_unavailable age_group=%s gender=%s",
        band,
        gender,
    )

    return {
        "average": {
            "age_group": band,
            "requested_test_age": age_source,
            "gender": gender,
            "avg_height": None,
            "avg_weight": None,
            "avg_body_fat": None,
            "avg_bmi": None,
            "sample_count": None,
            "prescription": None,
            "source": "unavailable",
            "data_origin": average_meta["data_origin"],
            "public_api_called": average_meta["public_api_called"],
            "public_api_success": average_meta["public_api_success"],
            "is_fallback_value": average_meta["is_fallback_value"],
            "fallback_reason": average_meta["fallback_reason"],
        },
        "average_meta": average_meta,
        "normal_weight_range": normal_weight_range,
    }

class TargetWeightRequest(BaseModel):
    target_weight: float = Field(..., gt=0)


@router.patch("/target-weight")
async def update_target_weight(
    req: TargetWeightRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rec = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .order_by(UserInbody.created_at.desc())
        .first()
    )

    if not rec:
        raise HTTPException(status_code=404, detail="인바디 데이터가 먼저 필요합니다.")

    rec.target_weight = float(req.target_weight)
    db.add(rec)
    db.commit()
    db.refresh(rec)

    return {
        "ok": True,
        "target_weight": rec.target_weight,
        "inbody_id": rec.id,
    }


@router.delete("/unlink")
async def unlink_health_data(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deleted_missions = (
        db.query(UserMission)
        .filter(UserMission.user_id == user.id)
        .delete(synchronize_session=False)
    )

    deleted_activities = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .delete(synchronize_session=False)
    )

    deleted_inbody = (
        db.query(UserInbody)
        .filter(UserInbody.user_id == user.id)
        .delete(synchronize_session=False)
    )

    deleted_weight_history = (
        db.query(UserWeightHistory)
        .filter(UserWeightHistory.user_id == user.id)
        .delete(synchronize_session=False)
    )

    db.commit()

    return {
        "ok": True,
        "message": "Samsung Health 연동 데이터가 삭제되었습니다.",
        "deleted": {
            "missions": deleted_missions,
            "activities": deleted_activities,
            "inbody": deleted_inbody,
            "weight_history": deleted_weight_history,
        },
    }


@router.get("/history", response_model=HistoryResponse)
async def get_history(
    week_start: Optional[str] = Query(None),
    week_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    activity_query = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
    )

    if week_start and week_end:
        try:
            start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
            end_date = datetime.strptime(week_end, "%Y-%m-%d").date()

            start_dt, end_dt = kst_date_range_to_utc_bounds(start_date, end_date)

            activity_query = (
                activity_query
                .filter(UserActivity.recorded_at >= start_dt)
                .filter(UserActivity.recorded_at <= end_dt)
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요."
            )
    else:
        activity_query = activity_query.order_by(UserActivity.recorded_at.desc()).limit(7)

    activities = activity_query.order_by(UserActivity.recorded_at.asc()).all()

    weights = (
        db.query(UserWeightHistory)
        .filter(UserWeightHistory.user_id == user.id)
        .order_by(UserWeightHistory.recorded_at.desc())
        .limit(10)
        .all()
    )

    activity_history = [
        {
            "date": to_kst(a.recorded_at).date().isoformat() if a.recorded_at else date.today().isoformat(),
            "steps": int(a.steps or 0),
            "calories": float(a.calories or 0),
        }
        for a in activities
    ]

    weight_history = [
        {
            "weight": float(w.weight),
            "recordedAt": w.recorded_at.isoformat() if w.recorded_at else datetime.now(UTC).isoformat(),
        }
        for w in reversed(weights)
    ]

    return {
        "activity_history": activity_history,
        "weight_history": weight_history,
    }