#사용자가 데이터를 잘못 입력하거나 시스템 오류가 발생했을 때, 
#프론트엔드(Flutter)에 일관된 형식으로 에러를 전달

# app/core/exceptions.py
from fastapi import HTTPException, status

class CustomException(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: str = None):
        super().__init__(status_code=status_code, detail={
            "status": "error",
            "error_code": error_code,
            "message": detail
        })

# 구체적인 에러 상황 정의
class InbodyDataNotFoundException(CustomException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자의 인바디 데이터가 존재하지 않습니다.",
            error_code="INBODY_001"
        )

class DeviceConnectionException(CustomException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="웨어러블 기기 연동 중 오류가 발생했습니다.",
            error_code="DEVICE_001"
        )