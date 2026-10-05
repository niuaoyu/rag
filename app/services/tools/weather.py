"""天气工具：配置 WEATHER_API_KEY 时调用 OpenWeatherMap，否则返回离线 mock。"""
from __future__ import annotations

import json

import requests

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_CITY_COORDS = {
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "杭州": (30.2741, 120.1551),
    "成都": (30.5728, 104.0668),
    "武汉": (30.5928, 114.3055),
    "西安": (34.3416, 108.9398),
}

# function calling 用的 schema
WEATHER_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的当前天气，用于判断是否适合户外活动",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，例如 北京"},
            },
            "required": ["city"],
        },
    },
}


def _mock_weather(city: str) -> dict:
    temp = 22.0 + (sum(ord(c) for c in city) % 10) - 5
    return {
        "city": city,
        "temperature_c": round(temp, 1),
        "description": "多云",
        "humidity": 55,
        "wind_speed": 3.2,
        "source": "mock",
    }


def get_weather(city: str) -> dict:
    if not settings.weather_api_key:
        logger.info("weather tool: mock city=%s", city)
        return _mock_weather(city)

    coords = _CITY_COORDS.get(city)
    params = {"q": city, "appid": settings.weather_api_key, "units": "metric", "lang": "zh_cn"}
    if coords:
        params = {"lat": coords[0], "lon": coords[1], "appid": settings.weather_api_key,
                  "units": "metric", "lang": "zh_cn"}
    resp = requests.get(f"{settings.weather_base_url}/weather", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    result = {
        "city": city,
        "temperature_c": data["main"]["temp"],
        "description": data["weather"][0]["description"],
        "humidity": data["main"]["humidity"],
        "wind_speed": data.get("wind", {}).get("speed"),
        "source": "openweathermap",
    }
    logger.info("weather tool: api city=%s result=%s", city, json.dumps(result, ensure_ascii=False))
    return result


def run_tool(name: str, arguments: dict) -> dict:
    if name == "get_weather":
        return get_weather(arguments.get("city", "北京"))
    raise ValueError(f"未知工具: {name}")
