# app/api/payments.py

import base64
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.game import UserGameProfile, PaymentOrder
from app.services.achievement_service import evaluate_and_grant_achievements
from app.api.game import build_profile_response, get_existing_game_profile

router = APIRouter(prefix="/payments", tags=["Payments"])


MISSION_COIN_PACKAGES = {
    "pack-1": {"coupon_amount": 1, "price": 500, "order_name": "미션 쿠폰 1개"},
    "pack-5": {"coupon_amount": 5, "price": 2000, "order_name": "미션 쿠폰 5개"},
    "pack-10": {"coupon_amount": 10, "price": 3800, "order_name": "미션 쿠폰 10개"},
    "pack-20": {"coupon_amount": 20, "price": 7200, "order_name": "미션 쿠폰 20개"},
    "pack-30": {"coupon_amount": 30, "price": 10200, "order_name": "미션 쿠폰 30개"},
    "pack-50": {"coupon_amount": 50, "price": 16000, "order_name": "미션 쿠폰 50개"},
    "pack-100": {"coupon_amount": 100, "price": 30000, "order_name": "미션 쿠폰 100개"},
}


class CreateMissionCouponOrderRequest(BaseModel):
    package_id: str


class TossConfirmRequest(BaseModel):
    paymentKey: str
    orderId: str
    amount: int


@router.post("/mission-coupons/orders")
def create_mission_coupon_order(
    req: CreateMissionCouponOrderRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    package = MISSION_COIN_PACKAGES.get(req.package_id)

    if not package:
        raise HTTPException(status_code=400, detail="유효하지 않은 미션 쿠폰 상품입니다.")

    order_id = f"mission_{user.id}_{uuid.uuid4().hex[:24]}"

    order = PaymentOrder(
        user_id=user.id,
        order_id=order_id,
        package_id=req.package_id,
        order_name=package["order_name"],
        amount=package["price"],
        coupon_amount=package["coupon_amount"],
        status="READY",
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "order_id": order.order_id,
        "order_name": order.order_name,
        "amount": order.amount,
        "coupon_amount": order.coupon_amount,
        "package_id": order.package_id,
        "customer_key": f"upbody_{uuid.uuid4().hex[:30]}",
    }


@router.post("/toss/confirm")
def confirm_toss_payment(
    req: TossConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not settings.TOSS_SECRET_KEY:
        raise HTTPException(status_code=500, detail="TOSS_SECRET_KEY가 설정되지 않았습니다.")

    order = (
        db.query(PaymentOrder)
        .filter(
            PaymentOrder.order_id == req.orderId,
            PaymentOrder.user_id == user.id,
        )
        .first()
    )

    if not order:
        raise HTTPException(status_code=404, detail="주문 정보를 찾을 수 없습니다.")

    if order.status == "PAID":
        profile = get_existing_game_profile(db, user.id)
        return {
            "ok": True,
            "message": "이미 처리된 결제입니다.",
            "profile": build_profile_response(profile, db, user.id),
            "new_achievements": [],
        }

    if order.amount != req.amount:
        order.status = "FAILED"
        db.add(order)
        db.commit()
        raise HTTPException(status_code=400, detail="결제 금액이 주문 금액과 다릅니다.")

    encoded_secret = base64.b64encode(
        f"{settings.TOSS_SECRET_KEY}:".encode("utf-8")
    ).decode("utf-8")

    headers = {
        "Authorization": f"Basic {encoded_secret}",
        "Content-Type": "application/json",
        "Idempotency-Key": f"confirm-{order.order_id}",
    }

    payload = {
        "paymentKey": req.paymentKey,
        "orderId": req.orderId,
        "amount": req.amount,
    }

    try:
        response = httpx.post(
            "https://api.tosspayments.com/v1/payments/confirm",
            json=payload,
            headers=headers,
            timeout=15,
        )
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="토스 결제 승인 요청에 실패했습니다.")

    data = response.json()

    if response.status_code >= 400:
        order.status = "FAILED"
        order.raw_response_json = data
        db.add(order)
        db.commit()

        message = data.get("message") or "토스 결제 승인에 실패했습니다."
        raise HTTPException(status_code=400, detail=message)

    if data.get("status") != "DONE":
        order.status = "FAILED"
        order.raw_response_json = data
        db.add(order)
        db.commit()
        raise HTTPException(status_code=400, detail="결제가 완료 상태가 아닙니다.")

    toss_total_amount = int(data.get("totalAmount", 0))

    if toss_total_amount != order.amount:
        order.status = "FAILED"
        order.raw_response_json = data
        db.add(order)
        db.commit()
        raise HTTPException(status_code=400, detail="토스 승인 금액이 주문 금액과 다릅니다.")

    profile: UserGameProfile = get_existing_game_profile(db, user.id)

    if profile.mission_coins is None:
        profile.mission_coins = 0

    if profile.total_purchases is None:
        profile.total_purchases = 0

    profile.mission_coins += order.coupon_amount
    profile.total_purchases += 1

    order.status = "PAID"
    order.payment_key = req.paymentKey
    order.payment_method = data.get("method")
    order.raw_response_json = data
    order.approved_at = datetime.now(ZoneInfo("Asia/Seoul"))

    new_achievements = evaluate_and_grant_achievements(db, profile)

    db.add(order)
    db.add(profile)
    db.commit()
    db.refresh(profile)

    return {
        "ok": True,
        "message": f"{order.order_name} 구매가 완료되었습니다.",
        "order_id": order.order_id,
        "package_id": order.package_id,
        "purchased_amount": order.coupon_amount,
        "mission_coins": profile.mission_coins,
        "profile": build_profile_response(profile, db, user.id),
        "new_achievements": new_achievements,
    }