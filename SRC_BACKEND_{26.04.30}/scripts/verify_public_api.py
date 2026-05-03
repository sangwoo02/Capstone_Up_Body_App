# scripts/verify_public_api.py

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

load_dotenv(ROOT_DIR / ".env")

# app.core.config.Settings에서 OPENAI_API_KEY가 필수라서
# 공공데이터 검증만 할 때 OpenAI 키가 없어도 import가 깨지지 않게 방어
os.environ.setdefault("OPENAI_API_KEY", "dummy-for-public-api-verification")

from app.core.config import settings
from app.services.public_api import PublicHealthService


PUBLIC_DATA_URL = "https://apis.data.go.kr/B551014/SRVC_NFA_TEST_RESULT/TODZ_NFA_TEST_RESULT_NEW"

REQUIRED_FIELDS = {
    "item_f001": "height",
    "item_f002": "weight",
    "item_f003": "body_fat",
    "item_f018": "bmi",
}


def assert_public_data_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise RuntimeError(f"공공데이터 URL 검증 실패: https가 아닙니다. url={url}")

    if parsed.netloc != "apis.data.go.kr":
        raise RuntimeError(f"공공데이터 URL 검증 실패: apis.data.go.kr 도메인이 아닙니다. url={url}")

    if parsed.path != "/B551014/SRVC_NFA_TEST_RESULT/TODZ_NFA_TEST_RESULT_NEW":
        raise RuntimeError(f"공공데이터 URL 검증 실패: 예상 API 경로가 아닙니다. path={parsed.path}")


def normalize_items(items):
    if items is None:
        return []

    if isinstance(items, list):
        return items

    if isinstance(items, dict):
        return [items]

    return []


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def average(items, field_name):
    values = []

    for item in items:
        value = safe_float(item.get(field_name))
        if value is not None and value > 0:
            values.append(value)

    if not values:
        return None

    return round(sum(values) / len(values), 1)


async def verify_raw_public_api(age: int, gender: str) -> dict:
    assert_public_data_url(PUBLIC_DATA_URL)

    api_key = unquote(settings.PUBLIC_DATA_API_KEY or "")

    if not api_key:
        raise RuntimeError("PUBLIC_DATA_API_KEY가 비어 있습니다.")

    if api_key == "default_key":
        raise RuntimeError("PUBLIC_DATA_API_KEY가 default_key입니다. .env에 실제 공공데이터 서비스키를 넣어야 합니다.")

    gender_code = "M" if gender == "male" else "F"

    params = {
        "serviceKey": api_key,
        "pageNo": "1",
        "numOfRows": "5",
        "resultType": "json",
        "age_degree": str(age),
        "test_sex": gender_code,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(PUBLIC_DATA_URL, params=params)

    print("[RAW] HTTP status:", response.status_code)
    print("[RAW] Request URL host:", response.url.host)
    print("[RAW] Request URL path:", response.url.path)

    if response.status_code != 200:
        print("[RAW] Response preview:")
        print(response.text[:1000])
        raise RuntimeError("공공데이터 API HTTP 호출 실패")

    try:
        data = response.json()
    except Exception as exc:
        print(response.text[:1000])
        raise RuntimeError("공공데이터 API 응답이 JSON이 아닙니다.") from exc

    response_obj = data.get("response", {})
    header = response_obj.get("header", {})
    body = response_obj.get("body", {})
    items_container = body.get("items", {})
    items = normalize_items(items_container.get("item") if isinstance(items_container, dict) else None)

    result_code = header.get("resultCode")
    result_msg = header.get("resultMsg")

    print("[RAW] resultCode:", result_code)
    print("[RAW] resultMsg:", result_msg)
    print("[RAW] item count:", len(items))

    if not items:
        raise RuntimeError("공공데이터 응답에 items.item 데이터가 없습니다.")

    first_item = items[0]
    missing_fields = [field for field in REQUIRED_FIELDS if field not in first_item]

    if missing_fields:
        print("[RAW] first item keys:", list(first_item.keys())[:50])
        raise RuntimeError(f"필수 측정 필드가 없습니다: {missing_fields}")

    calculated = {
        "avg_height": average(items, "item_f001"),
        "avg_weight": average(items, "item_f002"),
        "avg_body_fat": average(items, "item_f003"),
        "avg_bmi": average(items, "item_f018"),
        "sample_count": len(items),
    }

    print("[RAW] calculated average:", calculated)

    return calculated


async def verify_existing_service(age: int, gender: str) -> dict:
    service_file = Path(PublicHealthService.__module__.replace(".", "/") + ".py")
    actual_service_path = ROOT_DIR / service_file

    source = actual_service_path.read_text(encoding="utf-8")

    if "apis.data.go.kr" not in source:
        raise RuntimeError("app/services/public_api.py 안에 apis.data.go.kr 호출 코드가 없습니다.")

    if "serviceKey" not in source:
        raise RuntimeError("app/services/public_api.py 안에 serviceKey 파라미터가 없습니다.")

    if "httpx.AsyncClient" not in source:
        raise RuntimeError("app/services/public_api.py 안에 실제 HTTP 호출 코드가 없습니다.")

    url_match = re.search(r'https://apis\.data\.go\.kr/[^"\']+', source)

    if not url_match:
        raise RuntimeError("app/services/public_api.py에서 공공데이터 URL을 찾지 못했습니다.")

    detected_url = url_match.group(0)
    assert_public_data_url(detected_url)

    print("[SERVICE] detected file:", actual_service_path)
    print("[SERVICE] detected url:", detected_url)

    result = await PublicHealthService.get_average_metrics(
        user_age=age,
        user_gender=gender,
    )

    print("[SERVICE] result:", result)

    if not result:
        raise RuntimeError("PublicHealthService.get_average_metrics() 결과가 없습니다.")

    required_result_keys = ["avg_height", "avg_weight", "avg_body_fat", "avg_bmi", "sample_count"]
    missing_result_keys = [key for key in required_result_keys if key not in result]

    if missing_result_keys:
        raise RuntimeError(f"서비스 결과에 필수 키가 없습니다: {missing_result_keys}")

    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--age", type=int, default=20)
    parser.add_argument("--gender", choices=["male", "female"], default="male")
    args = parser.parse_args()

    print("=== 공공데이터 API 검증 시작 ===")
    print("project root:", ROOT_DIR)
    print("age:", args.age)
    print("gender:", args.gender)
    print()

    raw_result = await verify_raw_public_api(args.age, args.gender)

    print()
    service_result = await verify_existing_service(args.age, args.gender)

    print()
    print("=== 검증 성공 ===")
    print("판정: 이 백엔드는 실제 공공데이터포털 API를 호출하고 있습니다.")
    print()
    print("raw_result:", raw_result)
    print("service_result:", service_result)


if __name__ == "__main__":
    asyncio.run(main())