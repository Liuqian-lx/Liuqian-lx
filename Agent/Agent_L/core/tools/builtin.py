"""内置工具：getDate、isLeapYear。

所有工具统一返回 {"success": True, "result": ...} 或
{"success": False, "error": ...}。
"""

from __future__ import annotations

import subprocess
from datetime import datetime

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "用于获取本机当前系统日期与时间，当用户询问当前时间、日期时会调用该工具。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "用于判断给定的年份是否为闰年，用户询问某一年是否是闰年时调用该工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "待检测的年份",
                    }
                },
                "required": ["year"],
            },
        },
    },
]


def get_date() -> dict:
    """获取系统当前日期与时间。"""
    try:
        date_result = subprocess.run(
            ["cmd", "/c", "date", "/t"],
            capture_output=True,
            text=True,
            check=True,
        )
        time_result = subprocess.run(
            ["cmd", "/c", "time", "/t"],
            capture_output=True,
            text=True,
            check=True,
        )
        date_str = date_result.stdout.strip()
        time_str = time_result.stdout.strip()
        return {"success": True, "result": f"{date_str} {time_str}"}
    except Exception:
        # 非 Windows 环境或系统命令不可用时，回退到 Python 系统时间。
        try:
            return {
                "success": True,
                "result": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as exc:
            return {"success": False, "error": f"获取日期时间失败：{exc}"}


def is_leap_year(year) -> dict:
    """判断给定年份是否为闰年。"""
    try:
        value = int(year)
        leap = value % 400 == 0 or (value % 4 == 0 and value % 100 != 0)
        return {
            "success": True,
            "result": f"{value} 是闰年。" if leap else f"{value} 不是闰年。",
        }
    except Exception as exc:
        return {"success": False, "error": f"判断闰年失败：{exc}"}


TOOL_MAP = {
    "getDate": get_date,
    "isLeapYear": is_leap_year,
}
