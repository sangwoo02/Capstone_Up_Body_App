# app/services/medal_service.py

# 사용자의 활동 데이터가 업데이트될 때마다 메달 달성 여부를 체크하는 엔진

class MedalService:
    @staticmethod
    def check_medal_conditions(user_data: dict, action_type: str):
        """특정 액션 발생 시 메달 획득 가능 여부 검증"""
        new_medals = []
        
        # 1. 꾸준함 메달 (7일 연속 접속)
        if action_type == "login" and user_data['consecutive_days'] >= 7:
            new_medals.append("꾸준함 달성 메달")
            
        # 2. 만렙 달성 메달 (캐릭터 레벨 10)
        if action_type == "level_up" and user_data['character_level'] == 10:
            new_medals.append("캐릭터 만렙 달성 메달")
            
        # 3. 초고속 팀 미션 메달 (24시간 내 1000포인트 달성)
        if action_type == "team_goal" and user_data['completion_time'] <= 24:
            new_medals.append("24시간 내 팀 미션 달성 메달")
            
        # 4. 티어 메달 (그랜드 마스터 달성)
        if action_type == "tier_up" and "GrandMaster" in user_data['tier_name']:
            new_medals.append("그랜드 마스터 달성 메달")
            
        return new_medals