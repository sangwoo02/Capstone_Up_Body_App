#프론트에서 데이터를 보낼 때(예: 키 180, 몸무게 70), 이 데이터가 숫자인지, 빈 값은 아닌지 검사하는 '규격'

# app/schemas/user_schema.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

# 1. 공통 Enum 정의
class GoalEnum(str, Enum):
    LOSS = "체중 감량"
    GAIN = "근육 증가"
    MAINTAIN = "건강 유지"

# 2. [신규] 헬스케어 통합 데이터 동기화 규격
# 프론트엔드가 삼성 헬스/애플 건강에서 긁어온 모든 정보를 한 번에 보낼 때 사용합니다.
class HealthcareSyncRequest(BaseModel):
    weight: float                           # 현재 체중
    body_fat: float                         # 체지방률
    age: int                                # 나이
    gender: str                             # 성별
    muscle_mass: Optional[float] = 0.0      # 골격근량
    height: Optional[float] = None          # 앱 설정에서 가져오거나 기기에서 가져온 키
    steps: Optional[int] = 0                # 걸음 수 추가(오늘 하루 총 걸음 수)
    calories: Optional[float] = 0.0         # 소모 칼로리 추가 (웨어러블 기기에서 계산된 오늘 활동 소모 칼로리)
    source: str                             # "SamsungHealth" 또는 "AppleHealth"

# 3. 데이터 응답 규격 (분석 결과 포함)
class HealthcareResponse(BaseModel):
    bmi: float
    muscle_ratio: float
    status_message: Optional[str] = None
    bmi_result: str
    fat_status: str
    muscle_status: str

    class Config:
        from_attributes = True

# 4. 사용자 데이터 조회 응답
class UserCheckResponse(BaseModel):
    exists: bool
    data: Optional[HealthcareResponse] = None
    message: str

    class Config:
        from_attributes = True

# 5. 회원 정보 관리 (기존 유지)
class UserUpdate(BaseModel):
    """회원 정보 변경을 위한 스키마"""
    nickname: Optional[str] = Field(None, min_length=2, max_length=10)
    password: Optional[str] = Field(None, min_length=8)

# 6. 미션 상태 (기존 유지)
class MissionStatus(BaseModel):
    """미션 수행 상태 확인을 위한 스키마"""
    mission_id: int
    is_completed: bool
    earned_xp: int

# 7. 미션 응답 규격
class MissionResponse(BaseModel):
    id: int
    title: str
    content: str
    reason: Optional[str] = None
    category: str
    difficulty: str
    is_completed: bool

    class Config:
        from_attributes = True