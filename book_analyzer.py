#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 書籍分析工具

這個腳本會處理 PDF 檔案，使用 Deepseek Chat 提取摘要、目錄與各章節重點，
並將結果以 Markdown 格式輸出到桌面的專用資料夾。
"""

import os
import sys
import json
import time
import logging
import argparse
import requests
from datetime import datetime
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
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-8f32c535222145e594366ba158698c59")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# 建立桌面上的輸出資料夾
DESKTOP_PATH = str(Path.home() / "Desktop")
OUTPUT_FOLDER = os.path.join(DESKTOP_PATH, "書籍分析結果")
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 初始化 OpenCC（簡體轉繁體）
cc = opencc.OpenCC('s2tw')  # 針對台灣繁體中文進行最佳化

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(OUTPUT_FOLDER, "processing.log"), encoding="utf-8"),
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

def split_text_into_chunks(text, max_tokens=8000):
    """將文本分割成較小的塊，以符合 API 限制"""
    estimated_total_tokens = estimate_tokens(text)
    
    if estimated_total_tokens <= max_tokens:
        return [text]
    
    # 計算需要的塊數
    num_chunks = math.ceil(estimated_total_tokens / max_tokens)
    chunk_size = len(text) // num_chunks
    
    # 確保在完整段落處分割
    chunks = []
    start = 0
    
    for i in range(1, num_chunks):
        # 尋找最接近的段落結尾
        end = min(start + chunk_size, len(text))
        
        # 嘗試在段落結束處分割
        paragraph_end = text.rfind('\n\n', start, end)
        if paragraph_end != -1 and paragraph_end > start + chunk_size // 2:
            end = paragraph_end + 2  # 包含兩個換行符
        else:
            # 如果找不到段落結束，嘗試在句子結束處分割
            sentence_end = max(
                text.rfind('. ', start, end),
                text.rfind('。', start, end),
                text.rfind('！', start, end),
                text.rfind('？', start, end)
            )
            if sentence_end != -1 and sentence_end > start + chunk_size // 2:
                end = sentence_end + 1
        
        chunks.append(text[start:end])
        start = end
    
    # 添加最後一個塊
    chunks.append(text[start:])
    
    return chunks

def ensure_json_format(text):
    """確保回傳的文本是有效的 JSON 格式"""
    # 移除可能干擾 JSON 解析的前後綴
    text = text.strip()
    
    # 尋找第一個 { 和最後一個 }
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        text = text[start_idx:end_idx+1]
    
    try:
        # 嘗試解析 JSON
        json_data = json.loads(text)
        return json_data
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失敗: {str(e)}")
        logger.error(f"原始文本: {text}")
        
        # 嘗試修復常見的 JSON 問題
        text = re.sub(r',\s*}', '}', text)  # 移除尾隨逗號
        text = re.sub(r',\s*]', ']', text)  # 移除尾隨逗號
        
        try:
            return json.loads(text)
        except:
            logger.error("無法修復 JSON，返回原始文本")
            return {"error": "JSON 解析錯誤", "raw_text": text}

# ==========================
# Deepseek API 客戶端
# ==========================
class DeepseekClient:
    """Deepseek API 客戶端"""
    
    def __init__(self, api_key):
        """初始化 Deepseek 客戶端"""
        self.api_key = api_key
        self.api_url = DEEPSEEK_API_URL
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    
    def extract_content(self, prompt, max_retries=3, model="deepseek-chat"):
        """使用 Deepseek API 提取內容"""
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                logger.info(f"呼叫 Deepseek API (嘗試 {retry_count + 1}/{max_retries})")
                
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.5,
                    "max_tokens": 4000,
                }
                
                response = requests.post(
                    self.api_url, 
                    headers=self.headers, 
                    json=payload,
                    timeout=120
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    if content:
                        # 轉換為繁體中文
                        content = cc.convert(content)
                        return ensure_json_format(content)
                    else:
                        logger.error(f"API 返回空內容")
                else:
                    logger.error(f"API 請求失敗: {response.status_code} - {response.text}")
                
                retry_count += 1
                time.sleep(5)  # 在重試前等待
                
            except Exception as e:
                logger.error(f"API 調用錯誤: {str(e)}")
                retry_count += 1
                time.sleep(5)  # 在重試前等待
        
        return {"error": "達到最大重試次數後仍無法獲取內容"}

# ==========================
# PDF 處理函數
# ==========================
def extract_pdf_text(pdf_file):
    """從 PDF 提取文本"""
    try:
        logger.info(f"開始提取 PDF 文本: {pdf_file}")
        text = ""
        
        with open(pdf_file, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            num_pages = len(reader.pages)
            
            logger.info(f"PDF 共有 {num_pages} 頁")
            
            for page_num in range(num_pages):
                page = reader.pages[page_num]
                page_text = page.extract_text()
                
                if page_text:
                    text += page_text + "\n\n"
                
                # 每10頁記錄一次進度
                if (page_num + 1) % 10 == 0 or page_num == num_pages - 1:
                    logger.info(f"已處理 {page_num + 1}/{num_pages} 頁")
        
        if not text.strip():
            logger.warning("提取的 PDF 文本為空")
        
        return text
    except Exception as e:
        logger.error(f"提取 PDF 文本時發生錯誤: {str(e)}")
        raise

def analyze_book_content(text):
    """使用 Deepseek API 分析書籍內容"""
    try:
        start_time = time.time()
        estimated_tokens = estimate_tokens(text)
        logger.info(f"估計書籍文本約含有 {estimated_tokens} tokens")
        
        # 建立提示詞
        prompt = f"""
        請以專業知識研究者的身份，針對以下書籍內容，生成一份具備深度、邏輯清晰、結構完整的長篇書籍分析報告。報告需使用繁體中文撰寫，總字數超過7000字，並盡可能接近可支援的最大生成限制。

        【分析架構：七大模組】

        一、導論與整體定位
        1. 作者簡介與其背景影響
        2. 本書的寫作動機、問題意識與核心主題
        3. 書籍在其領域中的定位與影響力，與當代社會、文化、知識體系之關聯性

        二、核心摘要與知識精華提取
        1. 概括全書主要內容，形成一份高度濃縮的知識摘要
        2. 萃取書中關鍵理論、主張與策略，並進行交叉整合
        3. 擷取書中具代表性的金句或核心段落，搭配詮釋或應用說明

        三、章節結構與重點逐章解析
        （針對各章進行以下分析）
        1. 梳理每一章的主要論述內容與邏輯層次
        2. 提出本章核心概念及其內部邏輯結構
        3. 分析與前後章節之間的邏輯銜接與呼應
        4. 分析關鍵引述、理論或案例的代表性與深層意涵

        四、底層邏輯與思想架構分析
        1. 提煉本書隱含的世界觀、知識架構與預設立場
        2. 繪製出作者概念體系的內在邏輯關聯（以文字邏輯方式呈現）
        3. 分析其理論體系是否具備一致性、預測性與延展性，並指出潛在的矛盾與限制

        五、跨領域對應與延伸應用
        1. 將書中核心觀點對應至心理學、AI、哲學、教育、科技、社會系統等不同領域
        2. 評估若將本書邏輯內化為組織設計、社會制度或個人思維模型的系統變化
        3. 與其他經典著作進行觀點對話，提出補強、修正或跨域整合的見解

        六、批判性觀點與深層提問
        1. 就書中主張進行批判性審視，提出值得商榷或深化的部分
        2. 模擬與作者進行理性辯證的提問清單，聚焦在價值觀、方法論與應用層面
        3. 指出本書在當代環境下可能遺漏的核心問題，或其理論侷限未能觸及之處

        七、附錄與補充內容
        1. 以文字方式簡述本書邏輯與內容的思維導圖結構
        2. 建立關鍵詞彙索引，並對其進行簡要定義與語境說明
        3. 提出進一步閱讀的延伸推薦書目，並簡述其與本書的關聯性與互補性

        PDF 內容如下：
        ```
        {text}
        ```

        請以有效的 JSON 格式回傳結果，包含以下欄位：
        ```json
        {{
            "title": "書名",
            "author": "作者",
            "module_1": {
                "author_background": "作者簡介與背景影響（500-800字）",
                "writing_motivation": "寫作動機與核心主題（500-800字）",
                "book_positioning": "書籍定位與影響力（500-800字）"
            },
            "module_2": {
                "core_summary": "全書主要內容摘要（800-1200字）",
                "key_theories": [
                    {
                        "theory_name": "理論或策略名稱",
                        "explanation": "理論或策略解釋（300-500字）",
                        "application": "應用場景與價值（200-300字）"
                    }
                ],
                "key_quotes": [
                    {
                        "quote": "金句或核心段落",
                        "interpretation": "詮釋或應用說明（100-200字）"
                    }
                ]
            },
            "module_3": {
                "chapter_analysis": [
                    {
                        "chapter_number": "章節編號（如有）",
                        "chapter_title": "章節標題",
                        "content_analysis": "論述內容與邏輯層次分析（500-800字）",
                        "core_concepts": [
                            {
                                "concept_name": "概念名稱",
                                "explanation": "概念解釋與內部邏輯（200-300字）"
                            }
                        ],
                        "connection_analysis": "與其他章節的邏輯銜接（200-300字）",
                        "key_cases": [
                            {
                                "case_description": "案例或引述描述", 
                                "significance": "代表性與深層意涵（200-300字）"
                            }
                        ]
                    }
                ]
            },
            "module_4": {
                "underlying_logic": "本書隱含的世界觀與預設立場（600-800字）",
                "concept_system": "作者概念體系的內在邏輯關聯（800-1000字）",
                "theoretical_assessment": "理論體系的一致性、預測性與延展性分析（600-800字）",
                "limitations": [
                    {
                        "limitation_type": "矛盾或限制類型",
                        "explanation": "詳細解釋（200-300字）"
                    }
                ]
            },
            "module_5": {
                "interdisciplinary_applications": [
                    {
                        "field": "領域名稱",
                        "application": "核心觀點在此領域的應用（300-500字）"
                    }
                ],
                "systemic_implications": "系統的變化性評估（500-700字）",
                "comparative_dialogue": [
                    {
                        "referenced_work": "相關經典著作",
                        "dialogue": "觀點對話與整合見解（300-400字）"
                    }
                ]
            },
            "module_6": {
                "critical_review": "批判性審視（700-900字）",
                "philosophical_questions": [
                    {
                        "question": "理性辯證提問",
                        "rationale": "提問背後的思考邏輯（200-300字）"
                    }
                ],
                "contemporary_gaps": "當代環境下的理論遺漏與侷限（500-700字）"
            },
            "module_7": {
                "mind_map_description": "思維導圖結構文字描述（500-700字）",
                "key_terms": [
                    {
                        "term": "關鍵詞彙",
                        "definition": "簡要定義與語境說明（100-150字）"
                    }
                ],
                "recommended_reading": [
                    {
                        "book_title": "推薦書籍",
                        "relevance": "與本書的關聯性與互補性（100-200字）"
                    }
                ]
            }}
        }}
        ```

        請確保：
        1. 嚴格遵循提供的 JSON 結構
        2. 分析深入且具備學術性
        3. 總字數超過7000字，並盡可能接近最大生成限制
        4. 避免使用口語或簡化描述，保持分析深度與批判思維
        5. 回應採用繁體中文，語句專業、嚴謹、具邏輯性
        """
        
        """
        
        # 分割長文本處理
        if estimated_tokens > 8000:
            logger.info("文本過長，將分段處理")
            return process_large_book(text)
        else:
            # 呼叫 Deepseek API
            client = DeepseekClient(DEEPSEEK_API_KEY)
            response = client.extract_content(prompt)
            
            # 記錄處理時間
            elapsed_time = time.time() - start_time
            minutes, seconds = divmod(elapsed_time, 60)
            logger.info(f"分析完成，耗時: {int(minutes)}分{seconds:.2f}秒")
            
            return response
    
    except Exception as e:
        error_message = f"分析書籍內容時發生錯誤：{str(e)}"
        logger.error(error_message)
        import traceback
        traceback.print_exc()
        return {"error": error_message}
    
    except Exception as e:
        error_message = f"分析書籍內容時發生錯誤：{str(e)}"
        logger.error(error_message)
        import traceback
        traceback.print_exc()
        return {"error": error_message}

def process_large_book(text):
    """處理大型書籍文本，分段送入API處理後合併結果"""
    start_time = time.time()
    logger.info("開始處理大型書籍文本...")
    
    # 分割文本
    chunks = split_text_into_chunks(text)
    logger.info(f"文本已分割為 {len(chunks)} 個片段")
    
    # 先處理第一部分，獲取基本結構
    first_chunk = chunks[0]
    client = DeepseekClient(DEEPSEEK_API_KEY)
    
    # 為第一部分構建提示詞
    first_prompt = f"""
    請對以下書籍內容的第一部分進行初步分析，識別書籍結構和基本信息：

    1. 書名
    2. 作者
    3. 目錄結構（各章節標題）
    4. 書籍整體主題和風格

    請注意這只是書籍的開始部分，你需要根據有限的信息進行最佳判斷。

    文本內容：
    ```
    {first_chunk}
    ```

    請以有效的 JSON 格式回傳基本結構：
    ```json
    {{
        "title": "書名（如能確定）",
        "author": "作者（如能確定）",
        "estimated_structure": [
            {{
                "chapter_number": "章節編號（如有）",
                "title": "章節標題"
            }}
        ],
        "overall_theme": "書籍整體主題的初步判斷"
    }}
    ```
    """
    
    logger.info("分析第一部分，獲取書籍基本結構...")
    base_structure = client.extract_content(first_prompt)
    
    if "error" in base_structure:
        logger.error("無法獲取書籍基本結構，終止處理")
        return base_structure
    
    # 準備完整分析結果的框架
    final_result = {
        "title": base_structure.get("title", "未知書名"),
        "author": base_structure.get("author", "未知作者"),
        "overview": "",
        "table_of_contents": base_structure.get("estimated_structure", []),
        "chapter_analysis": [],
        "reading_guide": "",
        "evaluation": ""
    }
    
    # 對每個文本塊進行處理
    logger.info("開始處理各部分內容...")
    for i, chunk in enumerate(chunks):
        logger.info(f"處理第 {i+1}/{len(chunks)} 部分...")
        
        # 為每個部分構建提示詞
        chunk_prompt = f"""
        這是一本名為「{final_result['title']}」的書籍的第 {i+1}/{len(chunks)} 部分。
        請分析這部分內容，提取章節信息和重點內容。這是完整書籍的一部分，請專注於這部分文本內容的分析。

        文本內容：
        ```
        {chunk}
        ```

        請以有效的 JSON 格式回傳以下信息：
        ```json
        {{
            "identified_chapters": [
                {{
                    "chapter_number": "章節編號（如有）",
                    "chapter_title": "章節標題",
                    "summary": "章節摘要（300-500字）",
                    "key_points": ["關鍵點1", "關鍵點2", "關鍵點3", "關鍵點4", "關鍵點5"],
                    "key_concepts": [
                        {
                            "concept": "概念名稱",
                            "explanation": "概念解釋"
                        }
                    ],
                    "practical_value": "實用價值分析"
                }
            ],
            "partial_overview": "基於此部分的書籍概述",
            "partial_evaluation": "基於此部分的評價"
        }}
        ```
        """
        
        # 呼叫 API
        chunk_result = client.extract_content(chunk_prompt)
        
        if "error" in chunk_result:
            logger.warning(f"處理第 {i+1} 部分時出錯，繼續處理下一部分")
            continue
        
        # 合併結果
        if "identified_chapters" in chunk_result:
            final_result["chapter_analysis"].extend(chunk_result["identified_chapters"])
        
        # 收集書籍概述和評價的片段
        if i == 0 and "partial_overview" in chunk_result:
            final_result["overview"] = chunk_result.get("partial_overview", "")
        elif "partial_overview" in chunk_result:
            final_result["overview"] += " " + chunk_result.get("partial_overview", "")
        
        if i == 0 and "partial_evaluation" in chunk_result:
            final_result["evaluation"] = chunk_result.get("partial_evaluation", "")
        elif "partial_evaluation" in chunk_result:
            final_result["evaluation"] += " " + chunk_result.get("partial_evaluation", "")
    
    # 最後的整合分析
    final_prompt = f"""
    請基於以下已經分析的書籍內容，提供一個完整的讀者導讀和最終評價：

    書名：{final_result['title']}
    作者：{final_result['author']}
    
    書籍概述：{final_result['overview']}
    
    已分析的章節數量：{len(final_result['chapter_analysis'])}

    請以有效的 JSON 格式回傳以下信息：
    ```json
    {{
        "comprehensive_overview": "完整的書籍概述（500-800字）",
        "reading_guide": "讀者導讀（300-500字）",
        "final_evaluation": "書籍評價（300-500字）"
    }}
    ```
    """
    
    logger.info("進行最終整合分析...")
    final_integration = client.extract_content(final_prompt)
    
    if "error" not in final_integration:
        final_result["overview"] = final_integration.get("comprehensive_overview", final_result["overview"])
        final_result["reading_guide"] = final_integration.get("reading_guide", "")
        final_result["evaluation"] = final_integration.get("final_evaluation", final_result["evaluation"])
    
    # 記錄處理時間
    elapsed_time = time.time() - start_time
    minutes, seconds = divmod(elapsed_time, 60)
    logger.info(f"大型書籍分析完成，總耗時: {int(minutes)}分{seconds:.2f}秒")
    
    return final_result

# ==========================
# Markdown 產生函數
# ==========================
def generate_markdown(data, output_file):
    """根據分析結果產生 Markdown 檔案"""
    try:
        markdown = []
        
        # 標題和作者
        markdown.append(f"# {data.get('title', '未知書名')}\n")
        author_info = f"**作者：** {data.get('author', '未知')}"
        if data.get('author_background'):
            author_info += f"\n\n{data.get('author_background')}"
        markdown.append(author_info + "\n")
        
        # 書籍概述
        markdown.append("## 書籍概述\n")
        markdown.append(f"{data.get('overview', '無可用概述')}\n")
        
        # 目錄
        markdown.append("## 目錄\n")
        for chapter in data.get('table_of_contents', []):
            chapter_num = chapter.get('chapter_number', '')
            title = chapter.get('title', '未命名章節')
            if chapter_num:
                markdown.append(f"- {chapter_num}. {title}")
            else:
                markdown.append(f"- {title}")
            
            # 小節
            for subchapter in chapter.get('subchapters', []):
                sub_num = subchapter.get('number', '')
                sub_title = subchapter.get('title', '未命名小節')
                if sub_num:
                    markdown.append(f"  - {sub_num} {sub_title}")
                else:
                    markdown.append(f"  - {sub_title}")
        markdown.append("")
        
        # 章節分析
        markdown.append("## 章節詳解\n")
        for chapter in data.get('chapter_analysis', []):
            # 章節標題
            chapter_num = chapter.get('chapter_number', '')
            title = chapter.get('chapter_title', '未命名章節')
            if chapter_num:
                markdown.append(f"### {chapter_num}. {title}\n")
            else:
                markdown.append(f"### {title}\n")
            
            # 章節摘要
            markdown.append("#### 章節摘要\n")
            markdown.append(f"{chapter.get('summary', '無可用摘要')}\n")
            
            # 關鍵點
            markdown.append("#### 核心觀點\n")
            for point in chapter.get('key_points', []):
                markdown.append(f"- {point}")
            markdown.append("")
            
            # 關鍵概念
            if chapter.get('key_concepts'):
                markdown.append("#### 關鍵概念\n")
                for concept in chapter.get('key_concepts', []):
                    markdown.append(f"##### {concept.get('concept', '未命名概念')}\n")
                    markdown.append(f"{concept.get('explanation', '無可用解釋')}\n")
            
            # 實用價值
            markdown.append("#### 實用價值\n")
            markdown.append(f"{chapter.get('practical_value', '無可用實用價值分析')}\n")
        
        # 讀者導讀
        markdown.append("## 讀者導讀\n")
        markdown.append(f"{data.get('reading_guide', '無可用讀者導讀')}\n")
        
        # 書籍評價
        markdown.append("## 書籍評價\n")
        markdown.append(f"{data.get('evaluation', '無可用書籍評價')}\n")
        
        # 寫入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(markdown))
        
        logger.info(f"Markdown 文件已保存至：{output_file}")
        return True
    
    except Exception as e:
        logger.error(f"生成 Markdown 時發生錯誤：{str(e)}")
        import traceback
        traceback.print_exc()
        return False

# ==========================
# 主要處理函數
# ==========================
def process_book(input_file):
    """處理單一 PDF 書籍檔案的完整流程"""
    try:
        start_time = time.time()
        file_name = os.path.basename(input_file)
        book_name = os.path.splitext(file_name)[0]
        
        logger.info(f"開始處理書籍：{book_name}")
        
        # 建立書籍專屬資料夾
        book_folder = os.path.join(OUTPUT_FOLDER, book_name)
        os.makedirs(book_folder, exist_ok=True)
        
        # 提取 PDF 文本內容
        logger.info("正在提取 PDF 文本...")
        pdf_text = extract_pdf_text(input_file)
        
        if not pdf_text:
            logger.error("PDF 文本提取失敗或內容為空")
            return False
        
        # 儲存原始文本以便日後檢查
        text_file = os.path.join(book_folder, f"{book_name}_原始文本.txt")
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(pdf_text)
        logger.info(f"原始文本已保存至：{text_file}")
        
        # 分析書籍內容
        logger.info("正在使用 Deepseek API 分析書籍內容...")
        analysis_result = analyze_book_content(pdf_text)
        
        if "error" in analysis_result:
            logger.error(f"分析失敗：{analysis_result['error']}")
            return False
        
        # 儲存分析結果 JSON
        json_file = os.path.join(book_folder, f"{book_name}_分析結果.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)
        logger.info(f"分析結果已保存至：{json_file}")
        
        # 產生 Markdown 檔案
        markdown_file = os.path.join(book_folder, f"{book_name}_書籍報告.md")
        logger.info("正在生成 Markdown 檔案...")
        if generate_markdown(analysis_result, markdown_file):
            logger.info(f"Markdown 報告已保存至：{markdown_file}")
        else:
            logger.error("Markdown 生成失敗")
            return False
        
        # 記錄處理時間
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        logger.info(f"書籍處理完成，總耗時: {int(minutes)}分{seconds:.2f}秒")
        logger.info(f"所有檔案已保存在：{book_folder}")
        
        return True
    
    except Exception as e:
        logger.error(f"處理書籍時發生錯誤：{str(e)}")
        import traceback
        traceback.print_exc()
        return False

# ==========================
# 主程式
# ==========================
def main():
    """主程式入口點"""
    parser = argparse.ArgumentParser(description='PDF 書籍分析工具')
    parser.add_argument('input_file', nargs='?', help='要處理的 PDF 檔案路徑')
    args = parser.parse_args()
    
    print("=" * 80)
    print("PDF 書籍分析工具")
    print("此工具將使用 Deepseek Chat 分析 PDF 書籍內容，並產生結構化報告")
    print(f"結果將存放於桌面的「{os.path.basename(OUTPUT_FOLDER)}」資料夾中")
    print("=" * 80)
    
    # 如果沒有提供檔案路徑，則請求使用者輸入
    input_file = args.input_file
    if not input_file:
        input_file = input("請輸入 PDF 檔案路徑：").strip()
    
    # 檢查檔案是否存在且為PDF
    if not os.path.exists(input_file):
        print(f"錯誤：找不到檔案 '{input_file}'")
        return
    
    if not input_file.lower().endswith('.pdf'):
        print(f"錯誤：'{input_file}' 不是 PDF 檔案")
        return
    
    # 處理書籍
    success = process_book(input_file)
    
    if success:
        print(f"處理完成！結果保存在：{OUTPUT_FOLDER}")
    else:
        print("處理過程中發生錯誤，請查看日誌了解詳情。")

if __name__ == "__main__":
    main()
