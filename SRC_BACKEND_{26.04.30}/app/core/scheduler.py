#app/core/scheduler.py

#실제 서버에서는 APScheduler 라이브러리를 사용하여 72시간 뒤에 위 함수가 실행되도록 예약
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.services.rank_service import RankSettlementService

scheduler = BackgroundScheduler()
scheduler.start()

def schedule_mission_settlement(team_id: int):
    # 미션 매칭 시점으로부터 72시간 뒤 실행 예약
    run_date = datetime.now() + timedelta(hours=72)
    scheduler.add_job(
        RankSettlementService.settle_team_mission, 
        'date', 
        run_date=run_date, 
        args=[team_id]
    )