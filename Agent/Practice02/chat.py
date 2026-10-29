import configparser
import json
import os
import subprocess
import sys
from openai import OpenAI

from file_agent_tools import TOOLS as FILE_TOOLS, TOOL_MAP as FILE_TOOL_MAP

HISTORY_FILE = "chat_history.json"

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
    }
]

TOOLS = TOOLS + FILE_TOOLS


def is_leap_year(year):
    year = int(year)
    if year % 400 == 0:
        return True
    if year % 4 == 0 and year % 100 != 0:
        return True
    return False


def get_date():
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
        return f"{date_str} {time_str}"
    except Exception as e:
        return f"获取日期时间失败：{e}"


def load_config():
    config = configparser.ConfigParser()
    config.read("config.ini", encoding="utf-8")
    try:
        base_url = config["llm"]["base_url"]
        model_name = config["llm"]["model_name"]
        api_key = config["llm"]["api_key"]
    except KeyError as e:
        print(f"配置缺失：{e}")
        sys.exit(1)
    return base_url, model_name, api_key


def chat(base_url, model_name, api_key, messages):
    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        stream = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=TOOLS,
            stream=True,
        )
        response_content = ""
        tool_calls = {}
        for chunk in stream:
            delta = chunk.choices[0].delta
            content = delta.content
            if content is not None:
                print(content, end="", flush=True)
                response_content += content
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    index = tc.index
                    if index not in tool_calls:
                        tool_calls[index] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls[index]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls[index]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls[index]["arguments"] += tc.function.arguments
        print()
        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": response_content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in tool_calls.values()
                    ],
                }
            )
            for tc in tool_calls.values():
                if tc["name"] == "getDate":
                    result = get_date()
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        }
                    )
                    print(f"[getDate] {result}")
                elif tc["name"] == "isLeapYear":
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        year = args.get("year")
                        result = (
                            f"{year} 是闰年。"
                            if is_leap_year(year)
                            else f"{year} 不是闰年。"
                        )
                    except Exception as e:
                        result = f"判断闰年失败：{e}"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        }
                    )
                    print(f"[isLeapYear] {result}")
                elif tc["name"] in FILE_TOOL_MAP:
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        result = json.dumps(
                            FILE_TOOL_MAP[tc["name"]](**args), ensure_ascii=False
                        )
                    except Exception as e:
                        result = json.dumps(
                            {"success": False, "error": f"工具调用失败：{e}"},
                            ensure_ascii=False,
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        }
                    )
                    print(f"[{tc['name']}] {result}")
            stream = client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=True,
            )
            final_content = ""
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content is not None:
                    print(content, end="", flush=True)
                    final_content += content
            print()
            messages.append({"role": "assistant", "content": final_content})
        else:
            messages.append({"role": "assistant", "content": response_content})
    except Exception as e:
        print(f"API 调用失败：{e}")


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(messages):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def main():
    base_url, model_name, api_key = load_config()
    messages = load_history()
    while True:
        try:
            prompt = input("请输入提示词：")
            print(prompt)
            print("---")
            messages.append({"role": "user", "content": prompt})
            chat(base_url, model_name, api_key, messages)
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            save_history(messages)
            break


if __name__ == "__main__":
    main()
