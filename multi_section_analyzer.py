#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多階段深度書籍分析工具

這個腳本會處理 PDF 檔案，使用多次 Deepseek API 呼叫生成詳盡的深度書籍分析報告，
將報告分為三個部分（導論、核心摘要和批判分析）分別處理，然後合併成完整報告，
最終以 Markdown 格式輸出到桌面的專用資料夾。
"""

import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
import PyPDF2
import re
import math
from dotenv import load_dotenv
import opencc

# 載入環境變數
load_dotenv()

# ==========================
# 配置與常數設定
# ==========================
# 獲取 Deepseek API 金鑰，優先從環境變數取得
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# 建立桌面上的輸出資料夾
DESKTOP_PATH = str(Path.home() / "Desktop")
OUTPUT_FOLDER = os.path.join(DESKTOP_PATH, "深度書籍分析報告")
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 初始化 OpenCC（簡體轉繁體）
cc = opencc.OpenCC('s2tw')  # 針對台灣繁體中文進行最佳化

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("processing.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==========================
# 輔助函數
# ==========================
def estimate_tokens(text):
    """估算文字的 token 數量"""
    # 一個中文字約為1.5個token，一個英文單詞約為1個token
    chinese_char_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_char_count = len(text)
    english_word_count = len(re.findall(r'\b[a-zA-Z]+\b', text))
    
    # 估算總token數
    estimated_tokens = chinese_char_count * 1.5 + english_word_count + (total_char_count - chinese_char_count - english_word_count) * 0.5
    return int(estimated_tokens)

def extract_pdf_text(pdf_path):
    """從PDF檔案提取文字內容"""
    try:
        logger.info(f"正在提取PDF文本: {pdf_path}")
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ''
            for page in reader.pages:
                text += page.extract_text() + "\n\n"
            
            # 處理提取的文本
            text = text.strip()
            if not text:
                logger.error("無法從PDF中提取任何文本")
                return None
                
            # 估算token並截斷以符合API限制
            tokens = estimate_tokens(text)
            logger.info(f"提取完成。共 {len(reader.pages)} 頁，約 {tokens} tokens")
            
            # 將文本限制在15000個token以內（約10000個漢字）
            if tokens > 15000:
                logger.info(f"文本過長，將截斷至約15000個tokens")
                # 估計截斷點（粗略計算）
                cutoff = int(len(text) * (15000 / tokens))
                text = text[:cutoff]
                logger.info(f"截斷後約 {estimate_tokens(text)} tokens")
            
            return text
    except Exception as e:
        logger.error(f"PDF提取失敗: {str(e)}")
        return None

def generate_section_analysis(content, book_name, section_type):
    """為特定報告部分生成分析內容"""
    if not DEEPSEEK_API_KEY:
        logger.error("未設置DEEPSEEK_API_KEY環境變數")
        return None
        
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}", 
        "Content-Type": "application/json"
    }
    
    # 針對不同部分設計不同的提示詞
    section_prompts = {
        "introduction": f"""
        您是一位專精於書籍分析的學者。請針對《{book_name}》進行深入的整體定位與導論分析，內容需包含：
        
        1. 書籍整體定位與類型（至少300字）
           - 詳細分析該書在知識體系中的位置
           - 涉及的學科領域
           - 獨特的類型特徵
           
        2. 核心主題與理論框架（至少400字）
           - 系統性呈現書籍的理論架構
           - 主要概念、理論基礎
           - 邏輯體系和知識結構
           
        3. 作者背景與權威性（至少300字）
           - 深入探討作者的專業背景
           - 研究成就與行業地位
           - 對內容可信度的影響
           
        4. 目標讀者與適用場景（至少300字）
           - 適合的讀者群體特徵
           - 適用場景與最佳應用時機
           - 不同需求的閱讀建議
           
        5. 與同類書籍比較的獨特價值（至少300字）
           - 至少比較3本相關領域的代表作
           - 對比分析本書的創新點和局限性
        
        分析需深入、全面、專業，總字數至少1600字。請基於以下書籍節錄內容進行分析：
        
        {content[:int(len(content)/3)]}
        """,
        
        "core_summary": f"""
        您是一位頂尖的思想提煉專家。請對《{book_name}》提供詳盡的核心摘要分析，內容需包含：
        
        1. 關鍵論點概述（至少500字）
           - 提取書中至少5個核心論點
           - 以論證結構方式呈現每個論點的前提、推理和結論
           - 引用書中原文支持您的分析
           
        2. 理論基礎闡述（至少400字）
           - 深入分析支撐書中觀點的哲學思想
           - 探討心理學或科學基礎
           - 追溯其學術淵源
           
        3. 方法論詳解（至少500字）
           - 系統性展開書中所有方法和步驟
           - 提供完整操作指南
           - 分析方法間的關聯性
           
        4. 實證案例分析（至少400字）
           - 選取書中至少3個核心案例深入剖析
           - 分析案例的背景、過程、結果和啟示
           - 評估案例的論證力度和實用性
           
        5. 主要價值貢獻（至少300字）
           - 從認知、實踐、社會三層面評估書籍價值
           - 分析其突破性貢獻和長期影響力
           - 比較歷史上類似著作的影響
        
        分析需深入、具體、富有洞見，總字數至少2100字。請基於以下書籍節錄內容進行分析：
        
        {content[int(len(content)/3):int(2*len(content)/3)]}
        """,
        
        "critical_analysis": f"""
        您是一位兼具批判思維和實用導向的書評家。請對《{book_name}》提供多角度的批判性分析，內容需包含：
        
        1. 深度章節分析（至少800字）
           - 選擇5個關鍵章節進行詳細分析
           - 評估每章核心目標、關鍵概念和邏輯結構
           - 提取每章的實用價值和應用方法
           
        2. 理論架構評析（至少500字）
           - 檢視書中理論體系的內部一致性
           - 指出創新觀點和理論依據
           - 分析潛在盲點與局限性
           - 與當前學術前沿的銜接
           
        3. 實用指引提煉（至少600字）
           - 提煉書中最具價值的實用方法
           - 轉化為具體、可操作的行動指南
           - 提供應對常見困難的解決方案
           - 分析不同場景的適應性調整
           
        4. 跨領域啟示（至少400字）
           - 探討書中理念在其他領域的應用潛力
           - 分析與新興技術或趨勢的結合可能
           - 提出商業模式創新的洞見
           - 評估社會層面的長期影響
           
        5. 書籍觀點與反思論點（至少700字）
           - 系統提煉書中5-7個核心主張
           - 評估這些觀點在當代社會的適用性
           - 提出深度批判和質疑
           - 列舉與作者觀點相對立的替代理論
           
        分析需批判性強、實用性高、見解獨到，總字數至少3000字。請基於以下書籍節錄內容進行分析：
        
        {content[int(2*len(content)/3):]}
        """
    }
    
    prompt = section_prompts.get(section_type)
    if not prompt:
        logger.error(f"無效的部分類型: {section_type}")
        return None
    
    try:
        logger.info(f"開始呼叫 Deepseek API 生成 {section_type} 部分的分析報告...")
        
        response = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 4096  # 每部分使用較小的token限制
            },
            timeout=300
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if content:
                # 轉換為繁體中文
                content = cc.convert(content)
                logger.info(f"成功獲取 {section_type} 部分報告，字數約: {len(content)}")
                return content
            else:
                logger.error("API 返回空內容")
        else:
            logger.error(f"API 請求失敗: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"API 調用錯誤: {str(e)}")
    
    return None

def save_report(content, book_name):
    """儲存分析報告到指定路徑"""
    try:
        report_path = os.path.join(OUTPUT_FOLDER, f"{book_name}_深度分析報告.md")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"分析報告已儲存至: {report_path}")
        return report_path
    except Exception as e:
        logger.error(f"儲存報告失敗: {str(e)}")
        return None

# ==========================
# 主要處理函數
# ==========================
def process_book(pdf_path):
    """處理流程，使用多次API呼叫生成更詳細的書籍分析報告"""
    try:
        # 1. 提取PDF文本
        start_time = time.time()
        pdf_text = extract_pdf_text(pdf_path)
        if not pdf_text:
            print("錯誤：無法從PDF提取文本或內容為空")
            return
        
        # 獲取書名（不含副檔名）
        book_name = os.path.splitext(os.path.basename(pdf_path))[0]
        
        # 2. 分段生成分析報告
        print("正在使用 Deepseek API 分段生成深度分析報告...")
        
        # 2.1 生成導論部分
        print("- 正在生成導論與整體定位...")
        intro_section = generate_section_analysis(pdf_text, book_name, "introduction")
        if not intro_section:
            print("警告：導論部分生成失敗，將繼續處理其他部分")
        
        # 2.2 生成核心摘要部分
        print("- 正在生成核心摘要...")
        core_section = generate_section_analysis(pdf_text, book_name, "core_summary")
        if not core_section:
            print("警告：核心摘要部分生成失敗，將繼續處理其他部分")
        
        # 2.3 生成批判分析部分
        print("- 正在生成批判分析部分...")
        critical_section = generate_section_analysis(pdf_text, book_name, "critical_analysis")
        if not critical_section:
            print("警告：批判分析部分生成失敗")
        
        # 3. 合併所有部分
        print("正在合併各部分報告...")
        
        # 創建報告標題和目錄
        full_report = f"""# 《{book_name}》深度分析報告

## 目錄
1. 導論與整體定位
2. 核心摘要
3. 深度章節分析
4. 理論架構評析
5. 實用指引提煉
6. 跨領域啟示
7. 書籍觀點與反思論點

---

"""
        
        # 添加導論部分
        if intro_section:
            full_report += f"## 一、導論與整體定位\n\n{intro_section}\n\n---\n\n"
        
        # 添加核心摘要部分
        if core_section:
            full_report += f"## 二、核心摘要\n\n{core_section}\n\n---\n\n"
        
        # 添加批判分析部分
        if critical_section:
            full_report += f"{critical_section}\n\n"
        
        # 添加結語
        full_report += """
## 結語

以上分析旨在提供對本書的多角度、深入解讀，同時結合實踐指導，幫助讀者更好地理解和應用書中核心理念。希望此分析報告能為您的閱讀提供有益的參考和啟發。

（本報告由AI分析生成，僅供參考。若有不足之處，請結合原書內容進行判斷。）
"""
        
        # 檢查是否至少有一部分生成成功
        if not (intro_section or core_section or critical_section):
            print("錯誤：所有部分都生成失敗")
            return
        
        # 4. 儲存報告
        report_path = save_report(full_report, book_name)
        if not report_path:
            print("錯誤：無法儲存分析報告")
            return
        
        # 5. 完成並顯示耗時
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        print(f"\n處理完成！")
        print(f"總耗時: {int(minutes)}分{seconds:.2f}秒")
        print(f"分析報告已儲存至: {report_path}")
        print(f"報告總字數約: {len(full_report)}")
        
    except Exception as e:
        print(f"處理過程中發生錯誤: {str(e)}")
        logger.error(f"處理失敗: {str(e)}")

# ==========================
# 主程式
# ==========================
def main():
    """主程式入口點"""
    print("=" * 80)
    print("多階段深度書籍分析工具")
    print("此工具將使用多次 Deepseek API 呼叫生成更詳細的深度書籍分析報告")
    print(f"結果將存放於桌面的「{os.path.basename(OUTPUT_FOLDER)}」資料夾中")
    print("=" * 80)
    
    # 取得PDF路徑
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = input("請輸入PDF檔案完整路徑: ").strip()
    
    if not pdf_path:
        print("錯誤：未提供PDF檔案路徑")
        return
    
    # 檢查檔案是否存在且為PDF
    if not os.path.exists(pdf_path):
        print(f"錯誤：找不到檔案 '{pdf_path}'")
        return
    
    if not pdf_path.lower().endswith('.pdf'):
        print(f"錯誤：'{pdf_path}' 不是 PDF 檔案")
        return
    
    # 處理書籍
    process_book(pdf_path)

if __name__ == "__main__":
    main()
