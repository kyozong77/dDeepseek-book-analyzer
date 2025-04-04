#!/usr/bin/env python3
import requests
import json
import time

# DeepSeek API 設定
API_KEY = "sk-8f32c535222145e594366ba158698c59"
API_URL = "https://api.deepseek.com/v1/chat/completions"

# 測試內容
test_text = """
Test Book Title
Chapter 1: Introduction
This is a test book created for testing the DeepSeek processor script.
"""

# 設定請求頭
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

# 設定請求體 - 使用極簡化的提示
payload = {
    "model": "deepseek-chat",
    "messages": [
        {
            "role": "user",
            "content": f"請以JSON格式分析這段文本的基本資訊：\n\n{test_text}"
        }
    ],
    "temperature": 0.1,
    "max_tokens": 300,
    "response_format": {"type": "json_object"}
}

# 發送請求
print("開始呼叫 DeepSeek API...")
start_time = time.time()

response = requests.post(
    API_URL,
    headers=headers,
    json=payload,
    timeout=60
)

elapsed_time = time.time() - start_time
print(f"API 回應時間: {elapsed_time:.2f} 秒")

# 處理回應
if response.status_code == 200:
    result = response.json()
    if "choices" in result and len(result["choices"]) > 0:
        content = result["choices"][0]["message"]["content"]
        print(f"成功取得 DeepSeek API 回應, 回應長度: {len(content)} 字符")
        print("回應內容:")
        print(json.dumps(json.loads(content), indent=2, ensure_ascii=False))
    else:
        print(f"無效的API回應: {result}")
else:
    print(f"API請求失敗: 狀態碼 {response.status_code}, 回應: {response.text}")
