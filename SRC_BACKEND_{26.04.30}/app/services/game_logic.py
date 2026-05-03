# app/services/game_logic.py

# 협동전(포인트 누적)과 경쟁전(티어 및 대량 EXP)의 핵심 로직을 처리하는 함수들

# 미션 성공 여부에 따른 경험치 계산 로직 (활동 기록과 미션 목표 비교).
# 레벨업 필요 경험치 테이블 정의.
# 팀 미션 기여도에 따른 차등 보상 계산 로직.

class GameService:
    @staticmethod
    def calculate_character_growth(current_level: int, added_exp: int):
        """레벨별 단계 성장 로직 (예: 식물 1~4단계)"""
        # 레벨 10 만렙 제한 및 단계별 외형 변경 데이터 반환
        pass

    @staticmethod
    def process_team_point(personal_point: int):
        """개인 미션 성공 시 팀 포인트 동기화 (+25포인트)"""
        point_gain = 25
        # 72시간 종료 전까지 포인트 누적 및 수령 시간 체크
        return point_gain

    @staticmethod
    def get_tier_update(rank: int, current_tier: str, current_points: int):
        """72시간 종료 후 순위별 티어 결정 로직"""
        # 1등: 티어 상승 (+20점 if 챌린저)
        # 5등: 티어 강등 (-10점 if 챌린저)
        # 챌린저 0점 이하 시 그랜드마스터 I 강등
        pass

    @staticmethod
    def calculate_rank_rewards(rank: int, is_max_level: bool):
        """순위별 대량 EXP 지급 (1등: 300, 2등: 200, 3등: 100)"""
        # 캐릭터 만렙 시 경쟁 시스템 누적 EXP로 전환 로직 포함
        rewards = {1: 300, 2: 200, 3: 100, 4: 0, 5: 0}
        return rewards.get(rank, 0)