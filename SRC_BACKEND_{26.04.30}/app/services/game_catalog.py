# app/services/game_catalog.py

from typing import Dict, Any, Optional

# 중요:
# - DB에는 문자열 ID만 저장
# - 가격, starter 여부, 이름 등은 이 카탈로그에서 관리
# - 나중에 픽셀 아트가 들어와도 ID만 유지하면 프론트 자산만 교체하면 됨

CHARACTER_CATALOG: Dict[str, Dict[str, Any]] = {
    "char-default": {
        "price": 0,
        "name": "기본 전사",
        "is_starter": True,
        "rarity": "common",
    },
    "char-bunny": {
        "price": 100,
        "name": "토끼 모험가",
        "is_starter": False,
        "rarity": "common",
    },
    "char-bear": {
        "price": 250,
        "name": "곰 전사",
        "is_starter": False,
        "rarity": "rare",
    },
    "char-cat": {
        "price": 400,
        "name": "고양이 닌자",
        "is_starter": False,
        "rarity": "epic",
    },
    "char-dragon": {
        "price": 700,
        "name": "드래곤 기사",
        "is_starter": False,
        "rarity": "legendary",
    },
}

BACKGROUND_CATALOG: Dict[str, Dict[str, Any]] = {
    "bg-default": {
        "price": 0,
        "name": "기본 초원",
        "is_starter": True,
        "rarity": "common",
    },
    "bg-sky": {
        "price": 150,
        "name": "하늘 정원",
        "is_starter": False,
        "rarity": "common",
    },
    "bg-sunset": {
        "price": 300,
        "name": "노을 평원",
        "is_starter": False,
        "rarity": "rare",
    },
    "bg-night": {
        "price": 500,
        "name": "별밤 마을",
        "is_starter": False,
        "rarity": "epic",
    },
    "bg-galaxy": {
        "price": 800,
        "name": "은하 신전",
        "is_starter": False,
        "rarity": "legendary",
    },
}


def get_character_catalog() -> Dict[str, Dict[str, Any]]:
    return CHARACTER_CATALOG


def get_background_catalog() -> Dict[str, Dict[str, Any]]:
    return BACKGROUND_CATALOG


def get_character_item(character_id: str) -> Optional[Dict[str, Any]]:
    return CHARACTER_CATALOG.get(character_id)


def get_background_item(background_id: str) -> Optional[Dict[str, Any]]:
    return BACKGROUND_CATALOG.get(background_id)


def is_valid_character_id(character_id: str) -> bool:
    return character_id in CHARACTER_CATALOG


def is_valid_background_id(background_id: str) -> bool:
    return background_id in BACKGROUND_CATALOG


def get_character_price(character_id: str) -> int:
    item = get_character_item(character_id)
    if not item:
        raise KeyError(f"Unknown character_id: {character_id}")
    return int(item["price"])


def get_background_price(background_id: str) -> int:
    item = get_background_item(background_id)
    if not item:
        raise KeyError(f"Unknown background_id: {background_id}")
    return int(item["price"])


def is_starter_character(character_id: str) -> bool:
    item = get_character_item(character_id)
    if not item:
        raise KeyError(f"Unknown character_id: {character_id}")
    return bool(item.get("is_starter", False))


def is_starter_background(background_id: str) -> bool:
    item = get_background_item(background_id)
    if not item:
        raise KeyError(f"Unknown background_id: {background_id}")
    return bool(item.get("is_starter", False))

NICKNAME_CHANGE_PRICE = 500

def get_game_nickname_change_price() -> int:
    return NICKNAME_CHANGE_PRICE