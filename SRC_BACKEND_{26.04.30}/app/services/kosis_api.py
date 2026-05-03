# KOSIS 국가통계포털 건강검진통계 평균 신장/체중 조회 서비스
# app/services/kosis_api.py

import logging
import re
import time
from urllib.parse import unquote
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

KOSIS_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
KOSIS_ORG_ID = "350"
KOSIS_HEIGHT_TBL_ID = "DT_35007_N130"  # 시도별 연령별 성별 평균 신장 분포 현황 : 일반
KOSIS_WEIGHT_TBL_ID = "DT_35007_N132"  # 시도별 연령별 성별 평균 체중 분포 현황 : 일반


def _mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return "<empty>"
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}...{api_key[-4:]}(len={len(api_key)})"


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _normalize_gender(user_gender: str | None) -> Tuple[str, str]:
    gender = (user_gender or "male").strip().lower()
    if gender in {"female", "f", "여", "여성", "여자"}:
        return "female", "여자"
    return "male", "남자"


def _estimate_body_fat_from_bmi(avg_bmi: Optional[float], age: int, gender: str) -> Optional[float]:
    """
    KOSIS 건강검진통계에는 체지방률 평균이 없으므로 BMI, 나이, 성별 기반 추정식을 사용한다.

    Deurenberg 공식 기준:
    - 성인: BF% = 1.20 * BMI + 0.23 * age - 10.8 * sex - 5.4
    - 만 15세 이하: BF% = 1.51 * BMI - 0.70 * age - 3.6 * sex + 1.4
    - sex: 남성=1, 여성=0

    이 값은 실제 공공통계 체지방률 평균이 아니라 "공공통계 기반 추정 평균"이다.
    """
    if avg_bmi is None:
        return None

    try:
        bmi = float(avg_bmi)
        age_int = int(age or 0)
    except (TypeError, ValueError):
        return None

    if bmi <= 0 or age_int <= 0:
        return None

    sex = 1 if (gender or "male").strip().lower() == "male" else 0

    if age_int <= 15:
        estimated = (1.51 * bmi) - (0.70 * age_int) - (3.6 * sex) + 1.4
        formula_key = "deurenberg_child_bmi_age_sex"
    else:
        estimated = (1.20 * bmi) + (0.23 * age_int) - (10.8 * sex) - 5.4
        formula_key = "deurenberg_adult_bmi_age_sex"

    # 비정상적인 API/계산 결과가 화면에 그대로 노출되지 않도록 현실적인 범위로 제한한다.
    estimated = max(3.0, min(70.0, estimated))
    return round(estimated, 1)


def _row_labels(row: Dict[str, Any]) -> List[str]:
    labels: List[str] = []

    for key, value in row.items():
        key_str = str(key).upper()
        if value is None:
            continue

        # KOSIS 기본 응답은 C1_NM, C2_NM, C3_NM ... 형태로 분류값명이 내려온다.
        if re.fullmatch(r"C[1-8]_NM", key_str):
            labels.append(str(value).strip())

    # outputFields 설정에 따라 NM으로만 내려오는 경우도 방어한다.
    for key in ("NM", "NM_ENG"):
        value = row.get(key)
        if value is not None:
            labels.append(str(value).strip())

    return [label for label in labels if label]


def _is_total_region_label(label: str) -> bool:
    compact = re.sub(r"\s+", "", label)
    return compact in {"계", "합계", "전체", "전국", "전국계", "전국합계"}


def _is_gender_label(label: str) -> bool:
    compact = re.sub(r"\s+", "", label)
    return compact in {"남", "남자", "남성", "M", "여", "여자", "여성", "F"}


def _matches_gender(label: str, target_gender_label: str) -> bool:
    compact = re.sub(r"\s+", "", label)
    if target_gender_label == "남자":
        return compact in {"남", "남자", "남성", "M"}
    return compact in {"여", "여자", "여성", "F"}


def _is_age_like_label(label: str) -> bool:
    compact = re.sub(r"\s+", "", label)
    return bool(re.search(r"\d+\s*세|\d+\s*대|\d+\s*[~-]\s*\d+", compact)) or "이상" in compact or "이하" in compact


def _matches_age(label: str, age: int) -> bool:
    compact = re.sub(r"\s+", "", label)

    # 예: 20~24세, 20-24세
    range_match = re.search(r"(\d+)\s*[~-]\s*(\d+)", compact)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return start <= age <= end

    # 예: 85세이상, 80세 이상
    ge_match = re.search(r"(\d+)\s*세?이상", compact)
    if ge_match:
        return age >= int(ge_match.group(1))

    # 예: 19세이하, 20세 이하
    le_match = re.search(r"(\d+)\s*세?이하", compact)
    if le_match:
        return age <= int(le_match.group(1))

    # 예: 20대, 30대
    decade_match = re.search(r"(\d+)\s*대", compact)
    if decade_match:
        decade = int(decade_match.group(1))
        return (age // 10) * 10 == decade

    # 예: 24세처럼 단일 나이로 내려오는 경우
    exact_match = re.fullmatch(r"(\d+)세", compact)
    if exact_match:
        return age == int(exact_match.group(1))

    return False


def _score_row(row: Dict[str, Any], *, age: int, gender_label: str) -> Optional[int]:
    labels = _row_labels(row)
    if not labels:
        return None

    score = 0
    gender_seen = False
    age_seen = False

    for label in labels:
        if _is_total_region_label(label):
            score += 10

        if _is_gender_label(label):
            gender_seen = True
            if _matches_gender(label, gender_label):
                score += 100
            else:
                return None

        if _is_age_like_label(label):
            age_seen = True
            if _matches_age(label, age):
                score += 100
            else:
                return None

    # 성별/연령 분류가 있는 통계표이므로 둘 다 확인된 행을 우선 사용한다.
    if not gender_seen:
        score -= 50
    if not age_seen:
        score -= 50

    # DT 값이 없으면 사용할 수 없다.
    if _to_float(row.get("DT")) is None:
        return None

    return score


def _select_best_row(rows: List[Dict[str, Any]], *, age: int, gender_label: str) -> Optional[Dict[str, Any]]:
    best_row: Optional[Dict[str, Any]] = None
    best_score: Optional[int] = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        score = _score_row(row, age=age, gender_label=gender_label)
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_score = score
            best_row = row

    return best_row


class KosisHealthStatsService:
    @staticmethod
    async def _fetch_table(tbl_id: str, *, user_age: int, gender_label: str) -> Tuple[Optional[float], Dict[str, Any]]:
        api_key = unquote(getattr(settings, "KOSIS_API_KEY", "") or "")
        if not api_key:
            return None, {
                "kosis_api_called": False,
                "kosis_api_success": False,
                "kosis_fallback_reason": "missing_kosis_api_key",
            }

        params = {
            "method": "getList",
            "apiKey": api_key,
            "orgId": KOSIS_ORG_ID,
            "tblId": tbl_id,
            "itmId": "001+",
            "objL1": "ALL",
            "objL2": "ALL",
            "objL3": "ALL",
            "objL4": "",
            "objL5": "",
            "objL6": "",
            "objL7": "",
            "objL8": "",
            "format": "json",
            "jsonVD": "Y",
            "prdSe": "Y",
            "newEstPrdCnt": "1",
        }

        safe_params = {**params, "apiKey": _mask_api_key(api_key)}
        started_at = time.perf_counter()

        logger.info(
            "[KOSIS_DATA] request_start tbl_id=%s age=%s gender_label=%s params=%s",
            tbl_id,
            user_age,
            gender_label,
            safe_params,
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(KOSIS_URL, params=params)

            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
            logger.info(
                "[KOSIS_DATA] response_received tbl_id=%s status=%s elapsed_ms=%s host=%s path=%s",
                tbl_id,
                response.status_code,
                elapsed_ms,
                response.url.host,
                response.url.path,
            )

            if response.status_code != 200:
                return None, {
                    "kosis_api_called": True,
                    "kosis_api_success": False,
                    "kosis_fallback_reason": f"http_status_{response.status_code}",
                    "kosis_http_status": response.status_code,
                    "kosis_elapsed_ms": elapsed_ms,
                }

            try:
                data = response.json()
            except ValueError:
                return None, {
                    "kosis_api_called": True,
                    "kosis_api_success": False,
                    "kosis_fallback_reason": "json_parse_error",
                    "kosis_http_status": response.status_code,
                    "kosis_elapsed_ms": elapsed_ms,
                }

            rows = data if isinstance(data, list) else []
            best_row = _select_best_row(rows, age=user_age, gender_label=gender_label)

            if not best_row:
                preview_labels = [_row_labels(row) for row in rows[:5] if isinstance(row, dict)]
                logger.warning(
                    "[KOSIS_DATA] result tbl_id=%s success=false reason=no_matching_row row_count=%s preview_labels=%s",
                    tbl_id,
                    len(rows),
                    preview_labels,
                )
                return None, {
                    "kosis_api_called": True,
                    "kosis_api_success": False,
                    "kosis_fallback_reason": "no_matching_row",
                    "kosis_row_count": len(rows),
                    "kosis_preview_labels": preview_labels,
                    "kosis_http_status": response.status_code,
                    "kosis_elapsed_ms": elapsed_ms,
                }

            value = _to_float(best_row.get("DT"))
            labels = _row_labels(best_row)
            meta = {
                "kosis_api_called": True,
                "kosis_api_success": True,
                "kosis_fallback_reason": None,
                "kosis_http_status": response.status_code,
                "kosis_elapsed_ms": elapsed_ms,
                "kosis_tbl_id": tbl_id,
                "kosis_prd_de": best_row.get("PRD_DE"),
                "kosis_unit": best_row.get("UNIT_NM"),
                "kosis_selected_labels": labels,
                "kosis_row_count": len(rows),
            }

            logger.info(
                "[KOSIS_DATA] result tbl_id=%s success=true prd_de=%s value=%s unit=%s labels=%s",
                tbl_id,
                best_row.get("PRD_DE"),
                value,
                best_row.get("UNIT_NM"),
                labels,
            )

            return value, meta

        except httpx.TimeoutException:
            return None, {
                "kosis_api_called": True,
                "kosis_api_success": False,
                "kosis_fallback_reason": "timeout",
            }
        except httpx.HTTPError as exc:
            return None, {
                "kosis_api_called": True,
                "kosis_api_success": False,
                "kosis_fallback_reason": "httpx_error",
                "kosis_error": str(exc),
            }
        except Exception as exc:
            logger.exception("[KOSIS_DATA] unexpected_error tbl_id=%s error=%s", tbl_id, str(exc))
            return None, {
                "kosis_api_called": True,
                "kosis_api_success": False,
                "kosis_fallback_reason": "unexpected_error",
                "kosis_error": str(exc),
            }

    @staticmethod
    async def get_average_metrics(user_age: int, user_gender: str) -> Optional[Dict[str, Any]]:
        age = int(user_age or 20)
        gender, gender_label = _normalize_gender(user_gender)

        avg_height, height_meta = await KosisHealthStatsService._fetch_table(
            KOSIS_HEIGHT_TBL_ID,
            user_age=age,
            gender_label=gender_label,
        )
        avg_weight, weight_meta = await KosisHealthStatsService._fetch_table(
            KOSIS_WEIGHT_TBL_ID,
            user_age=age,
            gender_label=gender_label,
        )

        if avg_height is None or avg_weight is None:
            return None

        avg_bmi = round(avg_weight / ((avg_height / 100) ** 2), 1) if avg_height > 0 else None
        estimated_body_fat = _estimate_body_fat_from_bmi(avg_bmi, age, gender)
        body_fat_formula_key = (
            "deurenberg_child_bmi_age_sex" if age <= 15 else "deurenberg_adult_bmi_age_sex"
        )

        meta = {
            "data_origin": "kosis_health_checkup_live",
            "public_api_called": True,
            "public_api_success": True,
            "is_fallback_value": False,
            "fallback_reason": None,
            "source_detail": "KOSIS 국민건강보험공단 건강검진통계 평균 신장/체중",
            "requested_test_age": age,
            "gender": gender,
            "height_table": height_meta,
            "weight_table": weight_meta,
            "avg_bmi_basis": "calculated_from_kosis_avg_height_weight",
            "is_bmi_statistical_average": False,
            "avg_body_fat_basis": body_fat_formula_key,
            "is_body_fat_estimated": True,
            "body_fat_estimation_note": "KOSIS에는 체지방률 평균이 없어 평균 신장·체중 기반 BMI, 나이, 성별로 추정했습니다.",
        }

        return {
            "avg_height": round(avg_height, 1),
            "avg_weight": round(avg_weight, 1),
            "avg_body_fat": estimated_body_fat,
            "avg_body_fat_basis": body_fat_formula_key,
            "is_body_fat_estimated": True,
            "avg_bmi": avg_bmi,
            "sample_count": None,
            "prescription": None,
            "source": "kosis_health_checkup",
            "_meta": meta,
        }
