#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測試 Deepseek API 連接"""

import requests
import os

API_KEY = os.getenv("DEEPSEEK_API_KEY", "your_deepseek_api_key_here")
API_URL = "https://api.deepseek.com/v1/chat/completions"

def test_deepseek_api():
    """測試Deepseek API連接"""
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": "你好，請用繁體中文回答，你是什麼語言模型?"}
        ],
        "temperature": 0.7,
        "max_tokens": 300,
    }
    
    try:
        response = requests.post(API_URL, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            print("API 連接成功!")
            print("回應:", result["choices"][0]["message"]["content"])
        else:
            print(f"API 呼叫失敗，狀態碼: {response.status_code}")
            print(f"回應: {response.text}")
    except Exception as e:
        print(f"發生錯誤: {e}")

if __name__ == "__main__":
    test_deepseek_api()
