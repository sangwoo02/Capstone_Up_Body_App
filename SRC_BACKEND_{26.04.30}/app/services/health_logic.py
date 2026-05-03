#GPT 쿼리 생성 로직 및 분석 로직
# BMI 계산 및 표준 데이터와 사용자의 격차를 수학적으로 분석하는 엔진.

# app/services/health_logic.py

from sqlalchemy.orm import Session
from app.models.standard import HealthStandard

class HealthAnalyzer:
    @staticmethod
    def get_comparison(db: Session, user_data: dict):
        """
        사용자 데이터와 DB의 표준 데이터를 비교하여 
        비율 기반의 정밀 분석 리포트를 생성합니다.
        """
        # 1. 연령대 및 표준 데이터 조회
        age_group = (user_data['age'] // 10) * 10
        standard = db.query(HealthStandard).filter(
            HealthStandard.gender == user_data['gender'],
            HealthStandard.age_group == age_group
        ).first()

        if not standard:
            return {
                "bmi_result": "데이터 없음",
                "summary": "해당 연령대의 표준 데이터를 찾을 수 없습니다."
            }

        # 2. 정밀 수치 계산
        user_weight = user_data['weight']
        user_height_m = user_data['height'] / 100
        user_bmi = round(user_weight / (user_height_m ** 2), 1)
        
        # [핵심] 근육량 비율 계산: 체중 대비 근육이 몇 %인가?
        muscle_ratio = round((user_data['muscle_mass'] / user_weight) * 100, 1)
        # [핵심] 체지방 격차 계산
        fat_gap = round(user_data['body_fat'] - standard.avg_body_fat, 1)
        bmr_gap = round(user_data['bmr'] - standard.avg_bmr, 1)

        # 3. 상태 판정 로직
        # BMI 판정
        if user_bmi < 18.5: bmi_status = "저체중"
        elif user_bmi < 23: bmi_status = "정상"
        elif user_bmi < 25: bmi_status = "과체중"
        else: bmi_status = "비만"

        # 근육 상태 판정 (비율 기준: 여성 40%, 남성 45% 이상 양호)
        muscle_threshold = 40 if user_data['gender'] == 'female' else 45
        muscle_status = "양호" if muscle_ratio >= muscle_threshold else "부족"
        
        # 체지방 상태 판정 (격차 기준)
        fat_status = "높음" if fat_gap > 3 else "낮음" if fat_gap < -3 else "표준"

        # 4. 출력 문구 정리 (절대값 기호 제거 및 자연스러운 서술)
        abs_fat_gap = abs(fat_gap)
        fat_txt = "높은" if fat_gap > 0 else "낮은"
        warning_msg = " [경고: 기초대사량이 표준보다 낮습니다!]" if bmr_gap < -100 else ""

        # 5. 최종 결과 반환
        return {
            "bmi_value": user_bmi,
            "bmi_result": bmi_status,
            "muscle_ratio": muscle_ratio,
            "interpretation": {
                "fat": fat_status,
                "muscle": muscle_status,
                "bmr": "대사량 낮음" if bmr_gap < -100 else "정상"
            },
            "summary": (
                f"현재 {bmi_status} 체형이며, 체지방률은 표준 대비 {abs_fat_gap}% {fat_txt} 편입니다. "
                f"체중 대비 근육량 비율({muscle_ratio}%)은 {muscle_status} 상태입니다.{warning_msg}"
            )
        }