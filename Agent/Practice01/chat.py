import configparser
import json
import os
import sys
from openai import OpenAI

HISTORY_FILE = "chat_history.json"


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
            stream=True,
        )
        response_content = ""
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is not None:
                print(content, end="", flush=True)
                response_content += content
        print()
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
