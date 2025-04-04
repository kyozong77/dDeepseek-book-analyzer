#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度書籍分析工具

這個腳本會處理 PDF 檔案，使用 Deepseek API 生成深度書籍分析報告，
並將結果以 Markdown 格式輸出到桌面的專用資料夾。
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

def generate_analysis(content, book_name):
    """使用Deepseek API生成深度分析報告"""
    if not DEEPSEEK_API_KEY:
        logger.error("未設置DEEPSEEK_API_KEY環境變數")
        return None
        
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}", 
        "Content-Type": "application/json"
    }
    
    # 準備七大模組分析指令（擴充版本）
    instructions = {
        "報告需求": {
            "最低字數": "至少7500字，不含標題和格式符號",
            "內容深度": "每個模組和子項目都必須詳盡展開，完整論述，不得簡略帶過",
            "引述密度": "引用書中至少20個具體段落或案例作為論據",
            "實用性": "所有分析必須落地為具體可行的指導和方法"
        },
        "模組結構": [
            {
                "名稱": "導論與整體定位",
                "字數指引": "至少1000字",
                "要求": [
                    {
                        "項目": "書籍整體定位與類型",
                        "說明": "需詳細分析該書在知識體系中的位置，涉及的學科領域，以及其獨特的類型特徵"
                    },
                    {
                        "項目": "核心主題與理論框架",
                        "說明": "系統性呈現書籍的理論架構，包括主要概念、理論基礎、邏輯體系和知識結構，必須超過250字"
                    },
                    {
                        "項目": "作者背景與權威性",
                        "說明": "深入探討作者的專業背景、研究成就、行業地位，及其對內容可信度的影響"
                    },
                    {
                        "項目": "目標讀者與適用場景",
                        "說明": "具體分析適合的讀者群體特徵、適用場景、最佳應用時機，以及如何根據不同需求選擇性閱讀"
                    },
                    {
                        "項目": "與同類書籍比較的獨特價值",
                        "說明": "以對比表格形式呈現至少3本相關領域的代表作，對比分析本書的創新點和局限性"
                    }
                ]
            },
            {
                "名稱": "核心摘要",
                "字數指引": "至少1500字",
                "要素": [
                    {
                        "項目": "關鍵論點概述",
                        "說明": "提取書中至少5個核心論點，並以論證結構方式呈現每個論點的前提、推理和結論"
                    },
                    {
                        "項目": "理論基礎闡述",
                        "說明": "深入分析支撐書中觀點的哲學思想、科學理論或研究方法，追溯其學術淵源"
                    },
                    {
                        "項目": "方法論詳解",
                        "說明": "系統性展開書中提出的所有方法、流程、步驟或框架，必須提供完整操作指南"
                    },
                    {
                        "項目": "實證案例分析",
                        "說明": "選取書中至少3個核心案例，深入剖析其背景、過程、結果和啟示，評估其論證力度"
                    },
                    {
                        "項目": "主要價值貢獻",
                        "說明": "從認知、實踐、社會三個層面，評估該書的突破性貢獻和長期影響力"
                    }
                ]
            },
            {
                "名稱": "深度章節分析",
                "字數指引": "至少2000字",
                "說明": "需對每個主要章節進行詳盡分析，若章節過多，至少選擇5個最具代表性的章節：",
                "分析點": [
                    {
                        "項目": "章節核心目標",
                        "說明": "明確闡述各章節的寫作目的、內容結構和在全書中的位置和作用"
                    },
                    {
                        "項目": "關鍵概念解析",
                        "說明": "提取並深入解析每章的核心概念、專業術語和思想體系，建立概念間的聯繫"
                    },
                    {
                        "項目": "邏輯推演評估",
                        "說明": "評估章節內論證過程的嚴密性、推理的有效性和結論的可靠性，指出優勢與不足"
                    },
                    {
                        "項目": "論據強度分析",
                        "說明": "檢視支持論點的證據質量，包括數據可靠性、案例代表性、實驗設計合理性等"
                    },
                    {
                        "項目": "實用價值提取",
                        "說明": "從每章中提煉出可立即應用的工具、方法、框架或觀念，並提供實施建議"
                    }
                ]
            },
            {
                "名稱": "理論架構評析",
                "字數指引": "至少1000字",
                "重點": [
                    {
                        "項目": "理論邏輯一致性",
                        "說明": "全面檢視書中理論體系的內部一致性，指出可能的矛盾點和調和方案"
                    },
                    {
                        "項目": "創新觀點識別",
                        "說明": "明確指出書中具有原創性的思想、方法或視角，評估其創新程度和價值"
                    },
                    {
                        "項目": "理論依據紮實度",
                        "說明": "評估理論基礎的科學性、實證支持的充分性和推理過程的嚴謹性"
                    },
                    {
                        "項目": "潛在盲點與漏洞",
                        "說明": "指出作者可能忽略的視角、未考慮的變數或理論適用的邊界條件"
                    },
                    {
                        "項目": "與學術前沿的銜接",
                        "說明": "將書中觀點與當前學術研究、新興理論和實踐趨勢進行對比分析"
                    }
                ]
            },
            {
                "名稱": "實用指引提煉",
                "字數指引": "至少1000字",
                "內容": [
                    {
                        "項目": "核心實踐方法",
                        "說明": "提煉書中最具價值的實用方法，並轉化為具體、可操作的行動指南"
                    },
                    {
                        "項目": "具體操作步驟",
                        "說明": "將抽象原則轉化為明確步驟，提供詳細的執行流程、檢查點和評估標準"
                    },
                    {
                        "項目": "常見困難與解決方案",
                        "說明": "預測實施過程中可能遇到的阻礙，並提供針對性的解決策略和備選方案"
                    },
                    {
                        "項目": "場景適應性分析",
                        "說明": "分析方法在不同環境、行業、組織或個人情境中的適用性和調整建議"
                    },
                    {
                        "項目": "實施路徑圖",
                        "說明": "設計短期、中期和長期的實施計劃，包括里程碑、資源需求和效果評估方式"
                    }
                ]
            },
            {
                "名稱": "跨領域啟示",
                "字數指引": "至少500字",
                "延伸": [
                    {
                        "項目": "學科交叉價值",
                        "說明": "探討書中觀點如何與其他學科領域產生有益交叉，創造新的研究方向"
                    },
                    {
                        "項目": "方法論遷移潛力",
                        "說明": "分析書中方法論應用到其他領域的可能性，以及所需的調整和優化"
                    },
                    {
                        "項目": "技術整合可能性",
                        "說明": "探索與新興技術（如AI、區塊鏈、VR等）結合的創新應用場景"
                    },
                    {
                        "項目": "商業模式啟發",
                        "說明": "從書中提取可能催生新商業模式或優化現有商業實踐的洞見"
                    },
                    {
                        "項目": "社會影響評估",
                        "說明": "評估書中理念大規模應用後可能對社會、文化、經濟產生的長期影響"
                    }
                ]
            },
            {
                "名稱": "書籍觀點與反思論點",
                "字數指引": "至少1000字",
                "層次": [
                    {
                        "項目": "核心思想觀點",
                        "說明": "系統性提煉書中最重要的兰5-7個核心主張，並分析其思想淵源和影響"
                    },
                    {
                        "項目": "論點的當代價值",
                        "說明": "評估書中核心觀點在當代社會的適用性與相關性，強化與前瞻性"
                    },
                    {
                        "項目": "批判性反思",
                        "說明": "提出對書中觀點的深度批判，包含彼時與今日的考量，以及可能的偏見與限制"
                    },
                    {
                        "項目": "論證的有效性分析",
                        "說明": "剖析書中用來支持觀點的論證方式與案例，評估其邏輯性、實證性和說服力"
                    },
                    {
                        "項目": "反面觀點與對比",
                        "說明": "列舉與作者觀點相對立的替代理論或觀點，並提供延伸閱讀建議"
                    }
                ]
            }
        ],
        "格式規範": {
            "語言": "繁體中文",
            "字數": "必須超過7500字，不含標題和格式符號",
            "風格": "學術深度與實用性兼具，避免空泛表達，每個觀點都需有具體支撐",
            "結構": "清晰的標題層級、段落組織和邏輯連貫性，適當使用列表、表格增強可讀性",
            "引用": "準確引用書中原文作為論據，並明確標示來源"
        },
        "輸出要求": {
            "格式": "Markdown格式，善用標題層級、列表、表格和引用格式",
            "必要元素": "封面信息（含書名、作者）、目錄、模組內容、延伸閱讀建議",
            "溝通風格": "專業、系統、深入淺出，避免過度學術化而脫離實用性"
        }
    }
    
    prompt = f"""
    [高階AI指令：超詳盡書籍深度分析報告生成]
    
    您是一位頂尖的文學評論家、學術研究者和實用知識提煉專家。您的任務是生成一份極其詳盡、系統全面、深度剖析的書籍分析報告。
    
    請嚴格遵循以下指導方針，使用專業嚴謹的繁體中文生成一份超過7500字的深度分析報告，確保內容豐富、論證充分、見解獨到且實用性強：
    
    {json.dumps(instructions, ensure_ascii=False)}
    
    ===分析對象===
    書籍名稱：{book_name}
    
    ===書籍內容節錄===
    {content}
    
    重要提示：
    1. 必須確保最終報告總字數超過7500字，內容豐富且深入
    2. 請深入挖掘文本，提取關鍵概念、理論框架和方法論
    3. 每個分析點都需有具體例證，避免空泛表述
    4. 結合實際應用場景，提供可操作的實施指南
    5. 批判性思考，評估優缺點，識別理論盲點
    6. 使用清晰的標題層級和格式，增強可讀性
    
    請立即生成這份全面、深入且實用的書籍分析報告。
    """
    
    try:
        logger.info("開始呼叫 Deepseek API 生成分析報告...")
        
        response = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,  # 稍微提高創造性
                "max_tokens": 8192  # API允許的最大token數
            },
            timeout=300  # 增加超時時間
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if content:
                # 轉換為繁體中文
                content = cc.convert(content)
                logger.info(f"成功獲取分析報告，字數約: {len(content)}")
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
# 主程式
# ==========================
def main():
    """主程式入口點"""
    print("=" * 80)
    print("深度書籍分析工具")
    print("此工具將使用 Deepseek API 生成深度書籍分析報告")
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
    
    # 獲取書名（不含副檔名）
    book_name = os.path.splitext(os.path.basename(pdf_path))[0]
    
    # 處理流程
    try:
        # 1. 提取PDF文本
        start_time = time.time()
        pdf_text = extract_pdf_text(pdf_path)
        if not pdf_text:
            print("錯誤：無法從PDF提取文本或內容為空")
            return
        
        # 2. 生成分析報告
        print("正在使用 Deepseek API 生成深度分析報告...")
        analysis = generate_analysis(pdf_text, book_name)
        if not analysis:
            print("錯誤：無法生成分析報告")
            return
        
        # 3. 儲存報告
        report_path = save_report(analysis, book_name)
        if not report_path:
            print("錯誤：無法儲存分析報告")
            return
        
        # 4. 完成並顯示耗時
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        print(f"\n處理完成！")
        print(f"總耗時: {int(minutes)}分{seconds:.2f}秒")
        print(f"分析報告已儲存至: {report_path}")
        
    except Exception as e:
        print(f"處理過程中發生錯誤: {str(e)}")
        logger.error(f"處理失敗: {str(e)}")

if __name__ == "__main__":
    main()
