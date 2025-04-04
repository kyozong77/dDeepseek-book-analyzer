#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
強化版多階段深度書籍分析工具

這個腳本會處理 PDF 檔案，使用7次 Deepseek API 呼叫生成極為詳盡的深度書籍分析報告，
將報告分為多個精細部分分別處理，然後合併成完整報告，最終以 Markdown 格式輸出。
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
            
            # 將文本限制在20000個token以內
            if tokens > 20000:
                logger.info(f"文本過長，將截斷至約20000個tokens")
                # 估計截斷點（粗略計算）
                cutoff = int(len(text) * (20000 / tokens))
                text = text[:cutoff]
                logger.info(f"截斷後約 {estimate_tokens(text)} tokens")
            
            return text
    except Exception as e:
        logger.error(f"PDF提取失敗: {str(e)}")
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

def generate_api_section(content, book_name, section_type, max_tokens=4096, temperature=0.4):
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
        # 第一部分：導論與整體定位
        "book_overview": f"""
        您是一位專精於深度書籍分析的學者。請針對《{book_name}》進行詳盡的整體定位和背景分析，內容需包含：
        
        1. 書籍整體定位與類型（至少400字）
           - 詳細分析該書在知識體系中的位置（思想類、商業類、心理學類等）
           - 涉及的學科領域及跨領域特性
           - 出版背景與時代意義
           - 全球影響力和讀者覆蓋範圍
           
        2. 作者背景與權威性（至少500字）
           - 深入探討作者的專業背景與學術成就
           - 詳述作者的社會地位、影響力及專業信譽
           - 分析作者撰寫本書的背景動機
           - 評估作者在相關領域的貢獻及專業地位
           - 其他著作與本書的關聯
        
        分析需深入、全面、專業，總字數至少900字。請基於以下書籍節錄進行分析：
        
        {content[:int(len(content)/7)]}
        """,
        
        "theoretical_framework": f"""
        您是一位專精於思想體系分析的學者。請針對《{book_name}》進行深入的理論架構分析，內容需包含：
        
        1. 核心主題與理論框架（至少600字）
           - 詳細闡述本書的核心思想體系
           - 分析書中主要概念間的邏輯關係
           - 辨識並評估支撐全書的思想基礎
           - 歸納本書獨特的理論貢獻
           
        2. 與同類書籍比較的獨特價值（至少500字）
           - 與至少4本同領域經典著作的系統性對比
           - 分析本書在思想史上的定位和貢獻
           - 評估本書的創新性觀點和方法論
           - 制作對比表格，呈現各書的特點與差異
           
        3. 目標讀者與適用場景（至少400字）
           - 詳細分析適合的讀者群體特徵
           - 閱讀本書的最佳時機與心理狀態
           - 不同職業、年齡層讀者的收穫差異
           - 企業/個人應用的具體場景建議
        
        分析需邏輯嚴謹、見解獨到，總字數至少1500字。請基於以下書籍節錄進行分析：
        
        {content[int(len(content)/7):int(2*len(content)/7)]}
        """,
        
        # 第二部分：核心摘要
        "key_arguments": f"""
        您是一位精通思想提煉的分析專家。請針對《{book_name}》提供詳盡的核心論點分析，內容需包含：
        
        1. 關鍵論點概述（至少800字）
           - 系統提取書中至少7個核心論點
           - 詳細分析每個論點的前提、推理過程和結論
           - 評估各論點間的邏輯關係與層次架構
           - 引用原文關鍵段落作為證據
           - 解析作者論證方式的特點
           
        2. 理論基礎闡述（至少500字）
           - 深入分析支撐書中觀點的哲學、心理學等理論基礎
           - 追溯相關理論的歷史發展與學術淵源
           - 評估作者如何創新性地發展或應用這些理論
           - 分析理論基礎的科學性與可靠性
        
        分析需深入、學術性強，總字數至少1300字。請基於以下書籍節錄進行分析：
        
        {content[int(2*len(content)/7):int(3*len(content)/7)]}
        """,
        
        "methodology_analysis": f"""
        您是一位專精於方法論分析的專家。請針對《{book_name}》提供詳盡的方法論與實證案例分析，內容需包含：
        
        1. 方法論詳解（至少700字）
           - 系統性展開書中所有核心方法和具體步驟
           - 分析每個方法的操作流程、應用條件和預期效果
           - 評估各方法間的協同作用和適用優先級
           - 提供方法實施的可能障礙和應對策略
           
        2. 實證案例分析（至少600字）
           - 選取書中至少4個關鍵案例進行深入剖析
           - 對每個案例進行結構化分析（背景-過程-結果-啟示）
           - 評估案例的代表性、說服力和可借鑑性
           - 分析案例對理論的支持程度
           
        3. 主要價值貢獻（至少500字）
           - 從認知、實踐、社會三層面全面評估書籍價值
           - 分析本書對個人發展的潛在影響
           - 評估書中方法在現代社會的適用性和創新性
           - 比較歷史上類似著作的長期影響
        
        分析需具體、實用、深入，總字數至少1800字。請基於以下書籍節錄進行分析：
        
        {content[int(3*len(content)/7):int(4*len(content)/7)]}
        """,
        
        # 第三部分：批判分析
        "chapter_deep_dive": f"""
        您是一位精通深度文本分析的學者。請針對《{book_name}》進行詳盡的章節深度分析，內容需包含：
        
        1. 深度章節分析（至少1200字）
           - 選擇5個最關鍵章節進行精細拆解
           - 對每章進行結構分析：核心目標、關鍵概念、論證結構
           - 評估每章的理論深度、原創性和實用價值
           - 分析各章節間的邏輯連貫性和漸進發展
           - 引用關鍵段落並提供深度解讀
           - 比較同一主題在不同著作中的處理方式
        
        分析需學術性強、見解獨到，總字數至少1200字。請基於以下書籍節錄進行分析：
        
        {content[int(4*len(content)/7):int(5*len(content)/7)]}
        """,
        
        "practical_guidance": f"""
        您是一位專注於知識應用的實踐指導專家。請針對《{book_name}》提供詳盡的實用指引與跨領域啟示，內容需包含：
        
        1. 理論架構評析（至少600字）
           - 全面評估書中理論體系的內部一致性
           - 指出理論的創新點、盲點與局限性
           - 分析理論與當代實踐的契合度
           - 評估理論框架的普適性與特殊適用情境
           
        2. 實用指引提煉（至少800字）
           - 將書中核心方法轉化為具體、可操作的行動指南
           - 設計階段性實施計劃與效果評估標準
           - 提供針對不同應用場景的實施變體
           - 預測實施過程中可能遇到的障礙與解決方案
           - 設計自我檢視表或實踐清單
           
        3. 跨領域啟示（至少600字）
           - 探討書中理念在至少4個不同領域的應用潛力
           - 分析與新興技術或趨勢的結合可能
           - 提出基於書中理論的商業模式創新
           - 評估在教育、管理、心理健康等領域的實踐價值
        
        分析需實用性強、前瞻性高、操作性強，總字數至少2000字。請基於以下書籍節錄進行分析：
        
        {content[int(5*len(content)/7):int(6*len(content)/7)]}
        """,
        
        "critical_reflection": f"""
        您是一位兼具批判思維和建設性反思的評論家。請針對《{book_name}》提供深度的批判性反思，內容需包含：
        
        1. 書籍觀點與反思論點（至少900字）
           - 系統提煉書中6-8個核心主張
           - 對每個主張進行批判性評估，分析其優勢和侷限
           - 提出經過論證的替代觀點或互補理論
           - 分析這些觀點在不同文化背景中的適用差異
           - 探討作者可能忽略的重要視角或因素
           
        2. 當代價值與時代侷限（至少700字）
           - 評估書中理論在當代社會環境中的適用性
           - 分析社會、技術變遷對書中理論的挑戰
           - 提出書中內容需要更新或擴展的方面
           - 預測書中思想在未來10-20年的發展方向
           
        3. 綜合建議與延伸閱讀（至少600字）
           - 提供系統性閱讀與應用建議
           - 設計循序漸進的學習路徑
           - 推薦至少8本相關延伸閱讀，並說明與本書的關聯
           - 提出個人化學習計劃模板
        
        分析需批判性強、建設性高、前瞻視野廣，總字數至少2200字。請基於以下書籍節錄進行分析：
        
        {content[int(6*len(content)/7):]}
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
                "temperature": temperature,
                "max_tokens": max_tokens
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

# ==========================
# 主要處理函數
# ==========================
def process_book(pdf_path):
    """處理流程，使用7次API呼叫生成極度詳細的書籍分析報告"""
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
        print("正在使用 Deepseek API 分段生成極詳盡的深度分析報告...")
        
        # 第一部分：導論與整體定位
        print("\n=== 第一部分：導論與整體定位 ===")
        
        print("- 正在生成書籍概覽...")
        book_overview = generate_api_section(pdf_text, book_name, "book_overview")
        
        print("- 正在生成理論框架分析...")
        theoretical_framework = generate_api_section(pdf_text, book_name, "theoretical_framework")
        
        # 第二部分：核心摘要
        print("\n=== 第二部分：核心摘要 ===")
        
        print("- 正在生成關鍵論點分析...")
        key_arguments = generate_api_section(pdf_text, book_name, "key_arguments")
        
        print("- 正在生成方法論與案例分析...")
        methodology_analysis = generate_api_section(pdf_text, book_name, "methodology_analysis")
        
        # 第三部分：批判分析
        print("\n=== 第三部分：批判分析 ===")
        
        print("- 正在生成章節深度剖析...")
        chapter_deep_dive = generate_api_section(pdf_text, book_name, "chapter_deep_dive")
        
        print("- 正在生成實用指引與跨領域啟示...")
        practical_guidance = generate_api_section(pdf_text, book_name, "practical_guidance")
        
        print("- 正在生成批判性反思...")
        critical_reflection = generate_api_section(pdf_text, book_name, "critical_reflection")
        
        # 檢查是否至少有部分內容生成成功
        successful_sections = [
            section for section in [
                book_overview, theoretical_framework, 
                key_arguments, methodology_analysis,
                chapter_deep_dive, practical_guidance, critical_reflection
            ] if section
        ]
        
        if not successful_sections:
            print("錯誤：所有部分都生成失敗")
            return
        
        # 3. 合併所有部分
        print("正在合併各部分報告...")
        
        # 創建報告標題和目錄
        full_report = f"""# 《{book_name}》深度分析報告

## 目錄
1. [導論與整體定位](#1-導論與整體定位)
   1.1 [書籍概覽與定位](#11-書籍概覽與定位)
   1.2 [理論框架與比較價值](#12-理論框架與比較價值)
2. [核心摘要](#2-核心摘要)
   2.1 [關鍵論點解析](#21-關鍵論點解析)
   2.2 [方法論與案例分析](#22-方法論與案例分析)
3. [批判分析](#3-批判分析)
   3.1 [章節深度剖析](#31-章節深度剖析)
   3.2 [實用指引與跨領域啟示](#32-實用指引與跨領域啟示)
   3.3 [批判性反思](#33-批判性反思)
4. [結語與延伸閱讀](#4-結語與延伸閱讀)

---

"""
        
        # 添加導論部分
        full_report += "## 1. 導論與整體定位\n\n"
        
        if book_overview:
            full_report += "### 1.1 書籍概覽與定位\n\n"
            full_report += f"{book_overview}\n\n"
        
        if theoretical_framework:
            full_report += "### 1.2 理論框架與比較價值\n\n"
            full_report += f"{theoretical_framework}\n\n"
            
        full_report += "---\n\n"
        
        # 添加核心摘要部分
        full_report += "## 2. 核心摘要\n\n"
        
        if key_arguments:
            full_report += "### 2.1 關鍵論點解析\n\n"
            full_report += f"{key_arguments}\n\n"
        
        if methodology_analysis:
            full_report += "### 2.2 方法論與案例分析\n\n"
            full_report += f"{methodology_analysis}\n\n"
            
        full_report += "---\n\n"
        
        # 添加批判分析部分
        full_report += "## 3. 批判分析\n\n"
        
        if chapter_deep_dive:
            full_report += "### 3.1 章節深度剖析\n\n"
            full_report += f"{chapter_deep_dive}\n\n"
        
        if practical_guidance:
            full_report += "### 3.2 實用指引與跨領域啟示\n\n"
            full_report += f"{practical_guidance}\n\n"
        
        if critical_reflection:
            full_report += "### 3.3 批判性反思\n\n"
            full_report += f"{critical_reflection}\n\n"
        
        # 添加結語
        full_report += """## 4. 結語與延伸閱讀

本報告透過多維度、深層次的分析，全面解讀了《""" + book_name + """》這部作品的核心價值與實踐意義。我們從理論基礎、方法論、實際案例和批判反思等多個角度進行了系統分析，旨在為讀者提供一個全面、深入且實用的閱讀指南。

透過本書的學習與實踐，讀者可以獲得思維模式的轉變與實際能力的提升。希望本分析報告能夠幫助讀者更加高效地吸收書中精華，並在實際生活和工作中取得更好的成果。

（本報告由多階段AI分析生成，僅供參考。若有不足之處，請結合原書內容進行判斷。）
"""
        
        # 4. 儲存報告
        report_path = save_report(full_report, book_name)
        if not report_path:
            print("錯誤：無法儲存分析報告")
            return
        
        # 5. 完成並顯示耗時與字數統計
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        
        # 計算各部分和總字數
        section_word_counts = {
            "書籍概覽": len(book_overview or ""),
            "理論框架": len(theoretical_framework or ""),
            "關鍵論點": len(key_arguments or ""),
            "方法論與案例": len(methodology_analysis or ""),
            "章節深度剖析": len(chapter_deep_dive or ""),
            "實用指引": len(practical_guidance or ""),
            "批判性反思": len(critical_reflection or "")
        }
        total_words = len(full_report)
        
        print(f"\n處理完成！")
        print(f"總耗時: {int(minutes)}分{seconds:.2f}秒")
        print(f"分析報告已儲存至: {report_path}")
        print(f"報告總字數: {total_words}")
        print("\n各部分字數統計:")
        for section, count in section_word_counts.items():
            if count > 0:
                print(f"- {section}: {count} 字")
        
    except Exception as e:
        print(f"處理過程中發生錯誤: {str(e)}")
        logger.error(f"處理失敗: {str(e)}")

# ==========================
# 主程式
# ==========================
def main():
    """主程式入口點"""
    print("=" * 80)
    print("強化版多階段深度書籍分析工具")
    print("此工具將使用7次 Deepseek API 呼叫生成極為詳盡的深度書籍分析報告")
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
