from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="lm-studio",
    timeout=10  # 新增：10秒超时，不会无限卡死
)

resp = client.chat.completions.create(
    model="qwen-4b-saiga",
    messages=[{"role":"user", "content":"你好，请用中文回答我"}]
)
print(resp.choices[0].message.content)
