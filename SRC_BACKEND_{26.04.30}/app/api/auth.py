import base64
import re
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth_utils import create_access_token, hash_password, verify_password
from app.core.config import settings
from app.core.database import get_db
from app.models.game import PaymentOrder, UserAchievement, UserGameProfile, UserOwnedBackground, UserOwnedCharacter
from app.models.user import User, UserActivity, UserInbody, UserMission, UserWeightHistory

router = APIRouter(prefix="/auth", tags=["Authentication"])


class SignUpRequest(BaseModel):
    username: str
    password: str

    # ✅ 실명/프로필명
    name: Optional[str] = None

    # ✅ 구버전 프론트 호환용 (점진 제거 예정)
    nickname: Optional[str] = None

    birth_date: Optional[date] = None
    image_permission_granted: bool = False
    image_permission_status: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str

MIN_USER_AGE = 14


def calculate_age_from_birth_date(birth_date: date) -> int:
    today = date.today()
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def validate_birth_date_age(birth_date: Optional[date]) -> Optional[date]:
    if birth_date is None:
        return None

    if birth_date > date.today():
        raise HTTPException(status_code=400, detail="미래 날짜는 생년월일로 설정할 수 없습니다.")

    if calculate_age_from_birth_date(birth_date) < MIN_USER_AGE:
        raise HTTPException(status_code=400, detail="만 14세 이상만 이용할 수 있습니다.")

    return birth_date


def normalize_profile_name(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None

    cleaned = name.strip()

    if cleaned == "":
        return None

    if len(cleaned) < 2:
        raise HTTPException(status_code=400, detail="이름은 2자 이상이어야 합니다.")

    if len(cleaned) > 20:
        raise HTTPException(status_code=400, detail="이름은 20자 이하여야 합니다.")

    return cleaned


def normalize_nickname(nickname: Optional[str]) -> Optional[str]:
    if nickname is None:
        return None

    cleaned = nickname.strip()

    if cleaned == "":
        return None

    if len(cleaned) < 2:
        raise HTTPException(status_code=400, detail="닉네임은 2자 이상이어야 합니다.")

    if len(cleaned) > 10:
        raise HTTPException(status_code=400, detail="닉네임은 10자 이하여야 합니다.")

    return cleaned


MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024
PROFILE_IMAGE_DATA_URL_RE = re.compile(r"^data:(image/(png|jpeg|jpg|webp|gif));base64,(.+)$", re.IGNORECASE)


class ProfileDetailsUpdateRequest(BaseModel):
    name: Optional[str] = None
    birth_date: Optional[date] = None
    profile_image_data_url: Optional[str] = None


class ImagePermissionRequest(BaseModel):
    granted: bool
    status: Optional[str] = None


def estimate_base64_size(base64_text: str) -> int:
    padding = 0
    if base64_text.endswith("=="):
        padding = 2
    elif base64_text.endswith("="):
        padding = 1
    return max(0, (len(base64_text) * 3) // 4 - padding)


def validate_profile_image_data_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    cleaned = value.strip()
    if cleaned == "":
        return None

    match = PROFILE_IMAGE_DATA_URL_RE.match(cleaned)
    if not match:
        raise HTTPException(
            status_code=400,
            detail="프로필 이미지는 data:image/*;base64 형식이어야 합니다.",
        )

    base64_text = match.group(3)
    estimated_size = estimate_base64_size(base64_text)
    if estimated_size > MAX_PROFILE_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="프로필 이미지는 5MB 이하만 등록할 수 있습니다.")

    try:
        # validate=True로 손상된 base64를 미리 차단한다.
        decoded = base64.b64decode(base64_text, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="프로필 이미지 데이터가 올바르지 않습니다.")

    if len(decoded) > MAX_PROFILE_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="프로필 이미지는 5MB 이하만 등록할 수 있습니다.")

    return cleaned


def iso_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def mission_detail(mission: UserMission) -> Optional[str]:
    params = mission.params_json or {}
    progress = mission.progress_json or {}
    mission_type = mission.mission_type or ""

    if mission_type == "A1_STEP_TARGET":
        target = params.get("target_steps")
        current = progress.get("current_steps") or progress.get("steps")
        if target:
            return f"{int(current or 0):,}보 / {int(target):,}보"
    if mission_type == "A2_ACTIVE_KCAL_TARGET":
        target = params.get("target_kcal")
        current = progress.get("current_kcal") or progress.get("active_kcal")
        if target:
            return f"{int(current or 0):,}kcal / {int(target):,}kcal"
    if mission_type in {"B1_TIMER_STRETCH", "B2_SLEEP_PREP"}:
        duration = params.get("duration_min")
        if duration:
            return f"{int(duration)}분 완료"
    if mission_type == "B3_ROUTINE_CHECK":
        repeat = params.get("repeat_count")
        checked = progress.get("checked_count")
        if repeat:
            return f"루틴 {int(checked or repeat)}/{int(repeat)} 완료"
    if mission_type == "C1_HEALTH_CHECKIN":
        length = progress.get("text_length")
        if length:
            return f"기록 {int(length)}자"

    return None


def build_profile_details_response(user: User, db: Session) -> Dict[str, Any]:
    completed_filter = (
        (UserMission.user_id == user.id)
        & (
            (UserMission.status == "completed")
            | (UserMission.is_completed.is_(True))
        )
    )

    total_steps = (
        db.query(func.coalesce(func.sum(UserActivity.steps), 0))
        .filter(UserActivity.user_id == user.id)
        .scalar()
        or 0
    )

    mission_success_count = (
        db.query(func.count(UserMission.id))
        .filter(completed_filter)
        .scalar()
        or 0
    )

    total_mission_coins = (
        db.query(func.coalesce(func.sum(UserMission.reward_coins), 0))
        .filter(completed_filter)
        .scalar()
        or 0
    )

    completed_missions: List[UserMission] = (
        db.query(UserMission)
        .filter(completed_filter)
        .order_by(UserMission.completed_at.desc(), UserMission.updated_at.desc(), UserMission.id.desc())
        .limit(100)
        .all()
    )

    paid_orders: List[PaymentOrder] = (
        db.query(PaymentOrder)
        .filter(PaymentOrder.user_id == user.id, PaymentOrder.status == "PAID")
        .order_by(PaymentOrder.approved_at.desc(), PaymentOrder.created_at.desc(), PaymentOrder.id.desc())
        .limit(100)
        .all()
    )

    return {
        "ok": True,
        "profile": {
            "user_id": user.id,
            "username": user.username,
            "name": user.nickname,
            "birth_date": str(user.birth_date) if user.birth_date else None,
            "created_at": iso_or_none(getattr(user, "created_at", None)),
            "profile_image_data_url": user.profile_image_data_url,
            "image_permission_granted": bool(user.image_permission_granted),
            "image_permission_status": user.image_permission_status,
        },
        "stats": {
            "total_steps": int(total_steps),
            "mission_success_count": int(mission_success_count),
            "total_mission_coins": int(total_mission_coins),
        },
        "mission_history": [
            {
                "id": mission.id,
                "date": iso_or_none(mission.completed_at or mission.updated_at or mission.created_at),
                "mission_type": mission.mission_type,
                "title": mission.title or mission.content,
                "description": mission.content,
                "reward_coins": mission.reward_coins or 0,
                "reward_exp": mission.reward_exp or 0,
                "detail": mission_detail(mission),
            }
            for mission in completed_missions
        ],
        "routine_logs": [
            {
                "id": mission.id,
                "date": iso_or_none(mission.completed_at or mission.updated_at or mission.created_at),
                "title": mission.title or "컨디션 기록",
                "note": (
                    (mission.progress_json or {}).get("checkin_text")
                    or "작성한 기록 내용이 없습니다."
                ),
            }
            for mission in completed_missions
            if mission.mission_type == "C1_HEALTH_CHECKIN"
        ],
        "payments": [
            {
                "id": order.id,
                "date": iso_or_none(order.approved_at or order.created_at),
                "item": order.order_name,
                "amount": order.amount,
                "coupon_amount": order.coupon_amount,
                "status": order.status,
            }
            for order in paid_orders
        ],
    }


@router.post("/signup")
def signup(data: SignUpRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다.")

    hashed = hash_password(data.password)

    # ✅ name 우선, 없으면 구버전 nickname fallback
    normalized_profile_name = normalize_profile_name(
        data.name if data.name is not None else data.nickname
    )

    new_user = User(
        username=data.username,
        hashed_password=hashed,
        # ✅ users.nickname 은 게임 닉네임이 아니라 실명/프로필명 용도로 유지
        nickname=normalized_profile_name,
        birth_date=validate_birth_date_age(data.birth_date),
        image_permission_granted=bool(data.image_permission_granted),
        image_permission_status=data.image_permission_status,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "회원가입 성공",
        "username": new_user.username,
        "name": new_user.nickname,
    }


@router.get("/check-username")
def check_username(username: str, db: Session = Depends(get_db)):
    exists = db.query(User).filter(User.username == username).first() is not None
    return {"exists": exists}


@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 틀렸습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username, "user_id": user.id})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "nickname": user.nickname,
        "birth_date": str(user.birth_date) if user.birth_date else None,
        "created_at": iso_or_none(getattr(user, "created_at", None)),
        "profile_image_data_url": getattr(user, "profile_image_data_url", None),
        "image_permission_granted": bool(getattr(user, "image_permission_granted", False)),
        "image_permission_status": getattr(user, "image_permission_status", None),
        "exp": user.exp,
    }


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_user_id(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="자격 증명을 확인할 수 없습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
        return user_id
    except JWTError:
        raise credentials_exception


@router.patch("/update-profile")
def update_profile(
    nickname: str,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    normalized_nickname = normalize_profile_name(nickname)
    if normalized_nickname is None:
        raise HTTPException(status_code=400, detail="이름을 입력해주세요.")

    user.nickname = normalized_nickname
    db.commit()
    db.refresh(user)

    return {
        "message": "프로필 이름이 변경되었습니다.",
        "nickname": user.nickname,
    }


@router.get("/profile-details")
def get_profile_details(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    return build_profile_details_response(user, db)


@router.patch("/profile-details")
def update_profile_details(
    data: ProfileDetailsUpdateRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if data.name is not None:
        normalized_name = normalize_profile_name(data.name)
        if normalized_name is None:
            raise HTTPException(status_code=400, detail="이름을 입력해주세요.")
        user.nickname = normalized_name

    if data.birth_date is not None:
        user.birth_date = validate_birth_date_age(data.birth_date)

    # null 또는 빈 문자열이면 프로필 이미지를 제거한다.
    fields_set = getattr(data, "model_fields_set", getattr(data, "__fields_set__", set()))
    if "profile_image_data_url" in fields_set:
        user.profile_image_data_url = validate_profile_image_data_url(data.profile_image_data_url)

    db.add(user)
    db.commit()
    db.refresh(user)

    return build_profile_details_response(user, db)


@router.patch("/image-permission")
def update_image_permission(
    data: ImagePermissionRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    user.image_permission_granted = bool(data.granted)
    user.image_permission_status = data.status

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "image_permission_granted": bool(user.image_permission_granted),
        "image_permission_status": user.image_permission_status,
    }


@router.patch("/change-password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    # 1. 현재 비밀번호 검증
    if not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")

    # 2. 새 비밀번호 유효성 검사
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="새 비밀번호는 6자 이상이어야 합니다.")

    if data.current_password == data.new_password:
        raise HTTPException(status_code=400, detail="새 비밀번호는 현재 비밀번호와 달라야 합니다.")

    # 3. 새 비밀번호로 덮어쓰기
    user.hashed_password = hash_password(data.new_password)
    db.commit()

    return {"message": "비밀번호가 변경되었습니다."}

@router.post("/reset-password")
def reset_password(
    data: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="가입된 이메일을 찾을 수 없습니다.")

    new_password = data.new_password.strip()

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="새 비밀번호는 6자 이상이어야 합니다.")

    if verify_password(new_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="새 비밀번호는 현재 비밀번호와 달라야 합니다.")

    user.hashed_password = hash_password(new_password)
    db.commit()

    return {
        "message": "비밀번호가 재설정되었습니다. 다시 로그인해주세요.",
        "username": user.username,
    }


@router.post("/logout")
def logout(current_user_id: int = Depends(get_current_user_id)):
    return {
        "message": "로그아웃되었습니다.",
        "user_id": current_user_id,
    }


@router.delete("/delete-account")
def delete_account(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    try:
        # game profile id 먼저 확보
        game_profile = (
            db.query(UserGameProfile)
            .filter(UserGameProfile.user_id == current_user_id)
            .first()
        )

        deleted_owned_characters = 0
        deleted_owned_backgrounds = 0
        deleted_achievements = 0
        deleted_game_profile = 0

        if game_profile:
            deleted_owned_characters = (
                db.query(UserOwnedCharacter)
                .filter(UserOwnedCharacter.user_game_profile_id == game_profile.id)
                .delete(synchronize_session=False)
            )

            deleted_owned_backgrounds = (
                db.query(UserOwnedBackground)
                .filter(UserOwnedBackground.user_game_profile_id == game_profile.id)
                .delete(synchronize_session=False)
            )

            deleted_achievements = (
                db.query(UserAchievement)
                .filter(UserAchievement.user_game_profile_id == game_profile.id)
                .delete(synchronize_session=False)
            )

            deleted_game_profile = (
                db.query(UserGameProfile)
                .filter(UserGameProfile.id == game_profile.id)
                .delete(synchronize_session=False)
            )

        deleted_missions = (
            db.query(UserMission)
            .filter(UserMission.user_id == current_user_id)
            .delete(synchronize_session=False)
        )

        deleted_activities = (
            db.query(UserActivity)
            .filter(UserActivity.user_id == current_user_id)
            .delete(synchronize_session=False)
        )

        deleted_inbody = (
            db.query(UserInbody)
            .filter(UserInbody.user_id == current_user_id)
            .delete(synchronize_session=False)
        )

        deleted_weight_history = (
            db.query(UserWeightHistory)
            .filter(UserWeightHistory.user_id == current_user_id)
            .delete(synchronize_session=False)
        )

        deleted_users = (
            db.query(User)
            .filter(User.id == current_user_id)
            .delete(synchronize_session=False)
        )

        db.commit()

        return {
            "message": "회원탈퇴가 완료되었습니다.",
            "deleted": {
                "missions": deleted_missions,
                "activities": deleted_activities,
                "inbody": deleted_inbody,
                "weight_history": deleted_weight_history,
                "game_profile": deleted_game_profile,
                "owned_characters": deleted_owned_characters,
                "owned_backgrounds": deleted_owned_backgrounds,
                "achievements": deleted_achievements,
                "users": deleted_users,
                "user_id": current_user_id,
            },
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"회원탈퇴 처리 중 오류가 발생했습니다: {str(e)}")