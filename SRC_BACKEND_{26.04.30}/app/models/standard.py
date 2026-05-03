# 조건에 맞는 평균값을 찾기 위해 성별, 연령대별 표준 데이터를 저장할 테이블을 만듭니다.

# app/models/standard.py

from sqlalchemy import Column, Integer, String, Float
from app.core.database import Base

class HealthStandard(Base):
    """국민체력100 및 통계청 데이터를 기반으로 한 표준 지표 테이블"""
    __tablename__ = "health_standards"

    id = Column(Integer, primary_key=True, index=True)
    gender = Column(String)       # male / female
    age_group = Column(Integer)   # 20, 30 등 연령대
    avg_height = Column(Float)    # 평균 신장
    avg_weight = Column(Float)    # 평균 체중
    avg_body_fat = Column(Float)  # 평균 체지방률
    avg_muscle_mass = Column(Float) # 평균 근육량
    avg_bmr = Column(Float)       # 평균 기초대사량