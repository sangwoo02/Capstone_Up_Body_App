# app/services/rank_service.py

# 72시간 자동 정산 백그라운드 로직

from datetime import datetime, timedelta
from app.services.game_logic import GameService

class RankSettlementService:
    @staticmethod
    def settle_team_mission(team_id: int, participants: list):
        """72시간 종료 시점의 순위 정산 및 티어 업데이트"""
        
        # 1. 유효 참여자 필터링 (탈퇴자 제외 로직)
        active_members = [p for p in participants if not p.is_withdrawn]
        
        # 2. 포인트 기준 내림차순 정렬 (경쟁전 순위 산정)
        ranked_list = sorted(active_members, key=lambda x: x.personal_points, reverse=True)
        
        for index, member in enumerate(ranked_list):
            rank = index + 1
            # 3. 순위별 보상 지급 (1등: 300XP, 2등: 200XP, 3등: 100XP) 
            reward_exp = GameService.calculate_rank_rewards(rank, member.is_max_level)
            
            # 4. 티어 업데이트 로직 (1등 승급 / 5등 강등)
            GameService.get_tier_update(rank, member.current_tier, member.tier_point)
            
            # DB 저장 로직 호출 (생략)