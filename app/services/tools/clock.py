"""时间工具：让 Agent 知道“今天”是哪天——回答“今天/现在/最近”类问题的基础。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

CLOCK_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "获取当前日期与星期，用于回答“今天/现在/最近”相关的问题",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_TZ = timezone(timedelta(hours=8))
_WEEK = ("一", "二", "三", "四", "五", "六", "日")


def get_current_time() -> dict:
    now = datetime.now(_TZ)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "weekday": "周" + _WEEK[now.weekday()],
        "timezone": "UTC+8",
    }
