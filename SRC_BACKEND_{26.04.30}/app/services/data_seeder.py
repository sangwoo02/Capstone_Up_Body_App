# 기존에 만든 PublicHealthService를 활용하여 루프를 돌며 데이터를 수집하는 로직

# app/services/data_seeder.py

import logging
from sqlalchemy.orm import Session
from app.services.public_api import PublicHealthService
from app.models.standard import HealthStandard

logger = logging.getLogger(__name__)

class DataSeeder:
    @staticmethod
    async def seed_health_standards(db: Session):
        """
        10대부터 60대까지 남녀 표준 데이터를 공공데이터 API에서 가져와 DB에 저장합니다.
        """
        genders = ["male", "female"]
        age_groups = [10, 20, 30, 40, 50, 60]
        
        # 기존 데이터 삭제 (중복 방지 및 최신화)
        db.query(HealthStandard).delete()
        db.commit()

        success_count = 0

        for gender in genders:
            for age in age_groups:
                logger.info(f"{age}대 {gender} 데이터 수집 중...")
                
                # PublicHealthService의 로직을 이용해 50명 평균 데이터 추출
                avg_metrics = await PublicHealthService.get_average_metrics(age, gender)
                
                if avg_metrics:
                    new_standard = HealthStandard(
                        gender=gender,
                        age_group=age,
                        avg_height=avg_metrics['avg_height'],
                        avg_weight=avg_metrics['avg_weight'],
                        avg_body_fat=avg_metrics['avg_body_fat'],
                        avg_muscle_mass=35.0, # 공공데이터 API에 따라 근육량 항목이 없을 경우 기본값 세팅
                        avg_bmr=1500.0 if gender == "male" else 1300.0 # 기본 BMR 세팅
                    )
                    db.add(new_standard)
                    success_count += 1
                else:
                    logger.warning(f"{age}대 {gender} 데이터를 가져오지 못했습니다.")

        db.commit()
        return success_count