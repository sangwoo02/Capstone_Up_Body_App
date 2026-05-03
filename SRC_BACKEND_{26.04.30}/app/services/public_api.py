# 공공데이터 포털 API와 통신하여 실시간 평균 건강 데이터를 가져오는 기능.
# app/services/public_api.py

import logging
import time
from urllib.parse import unquote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PUBLIC_DATA_URL = "https://apis.data.go.kr/B551014/SRVC_NFA_TEST_RESULT/TODZ_NFA_TEST_RESULT_NEW"


def _mask_api_key(api_key: str | None) -> str:
    """
    로그에 공공데이터 서비스키가 그대로 노출되지 않도록 마스킹한다.
    """
    if not api_key:
        return "<empty>"

    if api_key == "default_key":
        return "default_key"

    if len(api_key) <= 8:
        return "****"

    return f"{api_key[:4]}...{api_key[-4:]}(len={len(api_key)})"


def _normalize_items(items):
    """
    공공데이터 응답의 items.item은 결과 개수에 따라 list 또는 dict가 될 수 있다.
    내부 평균 계산은 항상 list 기준으로 처리한다.
    """
    if items is None:
        return []

    if isinstance(items, list):
        return items

    if isinstance(items, dict):
        return [items]

    return []


def _get_item_value(item: dict, *field_names: str):
    """
    공공데이터 응답 키가 대문자/소문자/혼합 형태로 올 수 있어 유연하게 값을 꺼낸다.
    예: TEST_AGE, test_age, ITEM_F001, item_f001
    """
    if not isinstance(item, dict):
        return None

    for field_name in field_names:
        if field_name in item:
            return item.get(field_name)

    lower_map = {str(k).lower(): v for k, v in item.items()}
    for field_name in field_names:
        key = str(field_name).lower()
        if key in lower_map:
            return lower_map.get(key)

    return None


def _to_positive_float(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if parsed <= 0:
        return None

    return parsed


def _to_int_or_none(value):
    try:
        if value is None:
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _normalize_sex_code(value: object) -> str | None:
    if value is None:
        return None

    raw = str(value).strip().upper()
    if raw in {"M", "MALE", "남", "남성"}:
        return "M"
    if raw in {"F", "FEMALE", "여", "여성"}:
        return "F"
    return raw or None


def _age_gbn_for_age(age: int | None) -> str | None:
    """
    국민체력100 AGE_GBN 기준으로 사용자 나이를 넓은 연령 구분으로 변환한다.
    - 청소년: 만 13~18세
    - 성인: 만 19~64세
    - 어르신: 만 65세 이상

    현재 공공 API 응답에서는 TEST_AGE가 내려오지 않고 AGE_GBN만 내려오는 경우가 있어,
    정확한 나이 필터가 불가능하면 이 구분으로 로컬 필터링한다.
    """
    age_int = _to_int_or_none(age)
    if age_int is None:
        return None
    if age_int >= 65:
        return "어르신"
    if age_int >= 19:
        return "성인"
    return "청소년"


def _normalize_age_gbn(value: object) -> str | None:
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    lowered = raw.lower()
    if raw in {"청소년", "청소년기"} or lowered in {"teen", "teenager", "adolescent", "youth"}:
        return "청소년"
    if raw in {"성인", "성인기"} or lowered in {"adult"}:
        return "성인"
    if raw in {"어르신", "노인", "노년", "노년기", "고령", "고령자"} or lowered in {"senior", "elder", "elderly", "old"}:
        return "어르신"
    if raw in {"유소년", "유소년기", "아동"} or lowered in {"child", "children"}:
        return "유소년"
    if raw in {"유아", "유아기"} or lowered in {"infant", "preschool"}:
        return "유아"

    return raw


def _filter_items_by_requested_profile(items, requested_age: int | None, gender_code: str):
    """
    공공 API가 검색 파라미터 일부를 무시할 수 있으므로 응답 item을 한 번 더 검증한다.

    안정화 수정:
    - 정확한 연령(TEST_AGE/test_age)이 있으면 exact age로 필터링한다.
    - 정확한 연령이 없고 AGE_GBN이 있으면 청소년/성인/어르신 기준으로 필터링한다.
    - 그런데 API가 age_gbn/test_age 파라미터를 무시하고 성인 데이터만 앞쪽 페이지에 주는 경우가 있다.
      이때 엄격 필터 결과가 0개라고 None을 반환하면 프론트에서 공공데이터가 아예 사라진다.
    - 그래서 엄격 필터 결과가 0개면, "나이 필터 실패"를 메타에 남기고 성별 기준 item으로 fallback한다.
      이 fallback은 더미값이 아니라 실제 공공 API 응답값이지만, 나이별 평균이라고 보면 안 된다.
    """
    if not items:
        return [], {
            "age_field_seen": False,
            "age_gbn_field_seen": False,
            "sex_field_seen": False,
            "matched_count": 0,
            "strict_matched_count": 0,
            "sex_matched_count": 0,
            "requested_age_gbn": _age_gbn_for_age(requested_age),
            "age_filter_mode": "none",
            "age_filter_fallback_applied": False,
            "age_filter_fallback_reason": None,
        }

    requested_age_int = _to_int_or_none(requested_age)
    requested_age_gbn = _age_gbn_for_age(requested_age_int)
    requested_sex = _normalize_sex_code(gender_code)

    age_field_seen = False
    age_gbn_field_seen = False
    sex_field_seen = False

    strict_filtered = []
    sex_matched_items = []

    for item in items:
        if not isinstance(item, dict):
            continue

        item_age = _to_int_or_none(_get_item_value(
            item,
            "test_age", "TEST_AGE",
            "age", "AGE",
            "testAge", "TESTAGE",
            "age_val", "AGE_VAL",
            "연령",
        ))
        item_age_gbn = _normalize_age_gbn(_get_item_value(
            item,
            "age_gbn", "AGE_GBN",
            "ageGbn", "AGEGBN",
            "age_se", "AGE_SE",
            "ageSe", "AGESE",
            "age_div", "AGE_DIV",
            "age_group", "AGE_GROUP",
            "나이구분",
        ))
        item_sex = _normalize_sex_code(_get_item_value(
            item,
            "test_sex", "TEST_SEX",
            "sex", "SEX",
            "testSex", "TESTSEX",
            "gender", "GENDER",
            "성별",
        ))

        if item_age is not None:
            age_field_seen = True
        if item_age_gbn:
            age_gbn_field_seen = True
        if item_sex:
            sex_field_seen = True

        if requested_sex and item_sex and item_sex != requested_sex:
            continue

        sex_matched_items.append(item)

        age_matched = True

        # 정확한 나이 필드가 있으면 exact age를 최우선으로 사용한다.
        if requested_age_int is not None and item_age is not None:
            age_matched = item_age == requested_age_int
        # 정확한 나이 필드가 없고 AGE_GBN만 있으면 청소년/성인/어르신 기준으로 필터링한다.
        elif item_age is None and requested_age_gbn and item_age_gbn:
            age_matched = item_age_gbn == requested_age_gbn
        # 둘 다 없으면 나이 검증은 불가능하므로 성별 통과 item을 일단 사용한다.
        else:
            age_matched = True

        if age_matched:
            strict_filtered.append(item)

    if age_field_seen:
        age_filter_mode = "exact_age"
    elif age_gbn_field_seen:
        age_filter_mode = "age_gbn"
    else:
        age_filter_mode = "none"

    age_filter_fallback_applied = False
    age_filter_fallback_reason = None
    result_items = strict_filtered

    # 핵심: 엄격 나이/AGE_GBN 필터 결과가 0이면 데이터가 아예 사라지지 않도록 성별 기준으로 되돌린다.
    # 이 경우 메타에 fallback 사실을 남겨서 UI/로그에서 구분할 수 있게 한다.
    if not result_items and sex_matched_items:
        result_items = sex_matched_items
        age_filter_fallback_applied = True
        if age_filter_mode == "age_gbn":
            age_filter_fallback_reason = "no_items_for_requested_age_gbn_in_scanned_pages"
            age_filter_mode = "gender_only_after_age_gbn_miss"
        elif age_filter_mode == "exact_age":
            age_filter_fallback_reason = "no_items_for_requested_exact_age_in_scanned_pages"
            age_filter_mode = "gender_only_after_exact_age_miss"
        else:
            age_filter_fallback_reason = "age_fields_unavailable"
            age_filter_mode = "gender_only_age_unavailable"

    return result_items, {
        "age_field_seen": age_field_seen,
        "age_gbn_field_seen": age_gbn_field_seen,
        "sex_field_seen": sex_field_seen,
        "matched_count": len(result_items),
        "strict_matched_count": len(strict_filtered),
        "sex_matched_count": len(sex_matched_items),
        "requested_age_gbn": requested_age_gbn,
        "age_filter_mode": age_filter_mode,
        "age_filter_fallback_applied": age_filter_fallback_applied,
        "age_filter_fallback_reason": age_filter_fallback_reason,
    }

class PublicHealthService:
    @staticmethod
    async def get_average_metrics(user_age: int, user_gender: str):
        api_key = unquote(settings.PUBLIC_DATA_API_KEY or "")
        gender = (user_gender or "male").strip().lower()
        gender_code = "M" if gender == "male" else "F"
        requested_age = _to_int_or_none(user_age) or 20
        requested_age_gbn = _age_gbn_for_age(requested_age)

        # 공공 API는 test_sex는 적용되지만, test_age는 응답 로그상 무시되는 경우가 있다.
        # 그래서 서버 파라미터로는 가능한 값을 보내되, 최종 평균은 응답 item을 로컬 필터링해서 계산한다.
        base_params = {
            "serviceKey": api_key,
            "numOfRows": "1000",
            "resultType": "json",
            "test_age": str(requested_age),
            "test_sex": gender_code,
        }
        # 일부 공공 API 배포본에서는 AGE_GBN이 조회조건으로 동작할 수 있어 같이 보낸다.
        # 지원하지 않는 경우에는 API가 무시하므로, 아래 로컬 필터/fallback 로직에서 한 번 더 보정한다.
        if requested_age_gbn:
            base_params["age_gbn"] = requested_age_gbn

        safe_base_params = {
            "numOfRows": base_params["numOfRows"],
            "resultType": base_params["resultType"],
            "test_age": base_params["test_age"],
            "age_gbn": base_params.get("age_gbn"),
            "test_sex": base_params["test_sex"],
            "serviceKey": _mask_api_key(api_key),
        }

        logger.info(
            "[PUBLIC_DATA] request_start data_origin=public_api_live public_api_called=true url=%s params=%s",
            PUBLIC_DATA_URL,
            safe_base_params,
        )

        started_at = time.perf_counter()
        max_pages = 5
        target_sample_count = 50
        collected_items = []
        first_result_code = None
        first_result_msg = None
        first_total_count = None
        first_http_status = None
        first_host = None
        first_path = None
        last_filter_meta = None
        total_raw_count = 0
        last_elapsed_ms = None

        try:
            async with httpx.AsyncClient(verify=False, timeout=20.0) as client:
                for page_no in range(1, max_pages + 1):
                    params = {**base_params, "pageNo": str(page_no)}
                    response = await client.get(PUBLIC_DATA_URL, params=params)

                    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
                    last_elapsed_ms = elapsed_ms
                    first_http_status = first_http_status or response.status_code
                    first_host = first_host or response.url.host
                    first_path = first_path or response.url.path

                    logger.info(
                        "[PUBLIC_DATA] response_received status=%s elapsed_ms=%s host=%s path=%s pageNo=%s",
                        response.status_code,
                        elapsed_ms,
                        response.url.host,
                        response.url.path,
                        page_no,
                    )

                    if response.status_code != 200:
                        logger.error(
                            "[PUBLIC_DATA] page_skip reason=http_error status=%s pageNo=%s body_preview=%s",
                            response.status_code,
                            page_no,
                            response.text[:500],
                        )
                        continue

                    try:
                        result = response.json()
                    except ValueError:
                        logger.error(
                            "[PUBLIC_DATA] page_skip reason=json_parse_error pageNo=%s body_preview=%s",
                            page_no,
                            response.text[:500],
                        )
                        continue

                    response_obj = result.get("response", {}) if isinstance(result, dict) else {}
                    header = response_obj.get("header", {}) if isinstance(response_obj, dict) else {}
                    body = response_obj.get("body", {}) if isinstance(response_obj, dict) else {}

                    result_code = header.get("resultCode")
                    result_msg = header.get("resultMsg")
                    total_count = body.get("totalCount") if isinstance(body, dict) else None

                    if first_result_code is None:
                        first_result_code = result_code
                    if first_result_msg is None:
                        first_result_msg = result_msg
                    if first_total_count is None:
                        first_total_count = total_count

                    logger.info(
                        "[PUBLIC_DATA] response_header resultCode=%s resultMsg=%s totalCount=%s pageNo=%s",
                        result_code,
                        result_msg,
                        total_count,
                        page_no,
                    )

                    items_container = body.get("items", {}) if isinstance(body, dict) else {}
                    raw_items = items_container.get("item") if isinstance(items_container, dict) else None
                    raw_items = _normalize_items(raw_items)
                    total_raw_count += len(raw_items)

                    first_item = raw_items[0] if raw_items and isinstance(raw_items[0], dict) else {}
                    logger.info(
                        "[PUBLIC_DATA] raw_item_count=%s first_item_profile test_age=%s age_gbn=%s test_sex=%s pageNo=%s",
                        len(raw_items),
                        _get_item_value(first_item, "test_age", "TEST_AGE", "age", "AGE", "testAge", "연령"),
                        _get_item_value(first_item, "age_gbn", "AGE_GBN", "ageGbn", "나이구분"),
                        _get_item_value(first_item, "test_sex", "TEST_SEX", "sex", "SEX", "testSex", "성별"),
                        page_no,
                    )

                    filtered_items, filter_meta = _filter_items_by_requested_profile(
                        raw_items,
                        requested_age=requested_age,
                        gender_code=gender_code,
                    )
                    last_filter_meta = filter_meta

                    logger.info(
                        "[PUBLIC_DATA] filtered_item_count=%s strict_matched_count=%s sex_matched_count=%s requested_test_age=%s requested_age_gbn=%s requested_test_sex=%s age_filter_mode=%s age_filter_fallback_applied=%s age_filter_fallback_reason=%s age_field_seen=%s age_gbn_field_seen=%s sex_field_seen=%s pageNo=%s",
                        len(filtered_items),
                        filter_meta.get("strict_matched_count"),
                        filter_meta.get("sex_matched_count"),
                        requested_age,
                        filter_meta.get("requested_age_gbn"),
                        gender_code,
                        filter_meta.get("age_filter_mode"),
                        filter_meta.get("age_filter_fallback_applied"),
                        filter_meta.get("age_filter_fallback_reason"),
                        filter_meta.get("age_field_seen"),
                        filter_meta.get("age_gbn_field_seen"),
                        filter_meta.get("sex_field_seen"),
                        page_no,
                    )

                    collected_items.extend(filtered_items)

                    if len(collected_items) >= target_sample_count:
                        break

            if not collected_items:
                logger.warning(
                    "[PUBLIC_DATA] result data_origin=unavailable public_api_called=true public_api_success=false is_fallback_value=true fallback_reason=no_items_after_profile_filter requested_test_age=%s requested_age_gbn=%s requested_test_sex=%s raw_item_count=%s resultCode=%s resultMsg=%s age_filter_mode=%s",
                    requested_age,
                    requested_age_gbn,
                    gender_code,
                    total_raw_count,
                    first_result_code,
                    first_result_msg,
                    (last_filter_meta or {}).get("age_filter_mode"),
                )
                return None

            items = collected_items[:target_sample_count]

            height_values = []
            weight_values = []
            body_fat_values = []
            bmi_values = []

            for item in items:
                if not isinstance(item, dict):
                    continue

                height = _to_positive_float(_get_item_value(item, "item_f001", "ITEM_F001"))
                weight = _to_positive_float(_get_item_value(item, "item_f002", "ITEM_F002"))
                body_fat = _to_positive_float(_get_item_value(item, "item_f003", "ITEM_F003"))
                bmi = _to_positive_float(_get_item_value(item, "item_f018", "ITEM_F018"))

                if height is not None:
                    height_values.append(height)
                if weight is not None:
                    weight_values.append(weight)
                if body_fat is not None:
                    body_fat_values.append(body_fat)
                if bmi is not None:
                    bmi_values.append(bmi)

            count = min(
                len(height_values),
                len(weight_values),
                len(body_fat_values),
                len(bmi_values),
            )

            if count == 0:
                logger.warning(
                    "[PUBLIC_DATA] result data_origin=unavailable public_api_called=true public_api_success=false is_fallback_value=true fallback_reason=no_valid_numeric_values test_age=%s requested_age_gbn=%s test_sex=%s raw_item_count=%s filtered_item_count=%s",
                    requested_age,
                    requested_age_gbn,
                    gender_code,
                    total_raw_count,
                    len(items),
                )
                return None

            filter_meta = last_filter_meta or {}
            age_filter_mode = filter_meta.get("age_filter_mode")
            age_filter_fallback_applied = bool(filter_meta.get("age_filter_fallback_applied"))
            exact_age_applied = age_filter_mode == "exact_age" and not age_filter_fallback_applied
            age_gbn_applied = age_filter_mode == "age_gbn" and not age_filter_fallback_applied

            meta = {
                "data_origin": "public_api_live",
                "public_api_called": True,
                "public_api_success": True,
                "is_fallback_value": False,
                "fallback_reason": None,
                "http_status": first_http_status,
                "elapsed_ms": last_elapsed_ms,
                "result_code": first_result_code,
                "result_msg": first_result_msg,
                "total_count": first_total_count,
                "raw_item_count": total_raw_count,
                "filtered_item_count": len(items),
                "sample_count": count,
                "requested_test_age": requested_age,
                "requested_age_gbn": requested_age_gbn,
                "test_sex": gender_code,
                "age_field_seen": filter_meta.get("age_field_seen"),
                "age_gbn_field_seen": filter_meta.get("age_gbn_field_seen"),
                "sex_field_seen": filter_meta.get("sex_field_seen"),
                "age_filter_mode": age_filter_mode,
                "age_filter_fallback_applied": age_filter_fallback_applied,
                "age_filter_fallback_reason": filter_meta.get("age_filter_fallback_reason"),
                "strict_matched_count": filter_meta.get("strict_matched_count"),
                "sex_matched_count": filter_meta.get("sex_matched_count"),
                "exact_age_filter_applied": exact_age_applied,
                "age_gbn_filter_applied": age_gbn_applied,
                "age_filter_note": (
                    "요청한 연령/연령구분에 맞는 데이터가 조회된 페이지 안에 없어 성별 기준 공공데이터 평균으로 표시했습니다."
                    if age_filter_fallback_applied
                    else "정확한 연령(TEST_AGE) 필드가 응답에 없어 AGE_GBN 기준으로 필터링했습니다."
                    if age_gbn_applied and not exact_age_applied
                    else None
                ),
                "endpoint_host": first_host,
                "endpoint_path": first_path,
            }

            average_result = {
                "avg_height": round(sum(height_values) / len(height_values), 1),
                "avg_weight": round(sum(weight_values) / len(weight_values), 1),
                "avg_body_fat": round(sum(body_fat_values) / len(body_fat_values), 1),
                "avg_bmi": round(sum(bmi_values) / len(bmi_values), 1),
                "sample_count": count,
                "prescription": items[0].get("pres_note", "꾸준한 운동을 권장합니다.") if isinstance(items[0], dict) else "꾸준한 운동을 권장합니다.",
                "_meta": meta,
            }

            logger.info(
                "[PUBLIC_DATA] result data_origin=public_api_live public_api_called=true public_api_success=true is_fallback_value=false fallback_reason=None test_age=%s requested_age_gbn=%s test_sex=%s age_filter_mode=%s age_filter_fallback_applied=%s age_filter_fallback_reason=%s sample_count=%s avg_height=%s avg_weight=%s avg_body_fat=%s avg_bmi=%s",
                requested_age,
                requested_age_gbn,
                gender_code,
                age_filter_mode,
                age_filter_fallback_applied,
                filter_meta.get("age_filter_fallback_reason"),
                average_result["sample_count"],
                average_result["avg_height"],
                average_result["avg_weight"],
                average_result["avg_body_fat"],
                average_result["avg_bmi"],
            )

            return average_result

        except httpx.TimeoutException:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
            logger.error(
                "[PUBLIC_DATA] result data_origin=unavailable public_api_called=true public_api_success=false is_fallback_value=true fallback_reason=timeout elapsed_ms=%s test_age=%s requested_age_gbn=%s test_sex=%s",
                elapsed_ms,
                requested_age,
                requested_age_gbn,
                gender_code,
            )
            return None
        except httpx.HTTPError as exc:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
            logger.error(
                "[PUBLIC_DATA] result data_origin=unavailable public_api_called=true public_api_success=false is_fallback_value=true fallback_reason=httpx_error elapsed_ms=%s test_age=%s requested_age_gbn=%s test_sex=%s error=%s",
                elapsed_ms,
                requested_age,
                requested_age_gbn,
                gender_code,
                str(exc),
            )
            return None
        except Exception as exc:
            logger.exception(
                "[PUBLIC_DATA] result data_origin=unavailable public_api_called=true public_api_success=false is_fallback_value=true fallback_reason=unexpected_error error=%s",
                str(exc),
            )
            return None
