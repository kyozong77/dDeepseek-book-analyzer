#!/usr/bin/env python3
import os
import sys
import json
import time
import base64
import logging
import argparse
import requests
from fpdf import FPDF
from opencc import OpenCC
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import PyPDF2  # 導入PyPDF2用於PDF文本提取
import re
import math
import traceback

# ==========================
# API 金鑰與端點設定
# ==========================
DEEPSEEK_API_KEY = "sk-8f32c535222145e594366ba158698c59"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1"  # 更新為正確的API端點

DEEPL_API_KEY = "d9e14478-ef4a-4ed2-b350-1a1306a2553a"
DEEPL_API_URL = "https://api.deepl.com/v2/translate"

# 初始化 OpenCC（簡體轉繁體）
cc = OpenCC('s2tw')  # 更改為 s2tw，特別針對台灣繁體中文進行最佳化

# 配置日誌
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("processing.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 文本分析輔助函數
def estimate_tokens(text):
    # 一個中文字約為1.5個token，一個英文單詞約為1個token
    # 這是粗略估計，實際token數會因模型分詞器而異
    chinese_char_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_char_count = len(text)
    english_word_count = len(re.findall(r'\b[a-zA-Z]+\b', text))
    
    # 估算總token數
    estimated_tokens = chinese_char_count * 1.5 + english_word_count + (total_char_count - chinese_char_count - english_word_count) * 0.5
    return int(estimated_tokens)

def split_text_into_chunks(text, max_tokens=40000):
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

def analyze_pdf_with_deepseek(text):
    """使用 DeepSeek API 分析 PDF 文字內容"""
    try:
        start_time = time.time()
        # 估計 token 數量
        token_estimate = len(text) / 0.75 * 1.23  # 中文字符到 token 的粗略轉換比例
        logger.info(f"估計PDF文本約含有 {int(token_estimate)} tokens")
        
        # 判斷是否需要分段處理
        if token_estimate > 7500:  # 如果估計token數量超過7500，進行分段處理
            logger.info(f"PDF文本較長，將進行分段處理")
            return process_large_pdf(text)
        
        # 建立提示詞
        prompt = f"""
        請對以下中文 PDF 書籍內容進行全面詳細的分析，並提供一份結構化的書籍分析報告，總字數不少於7000字。請確保分析深入、全面且有見地，覆蓋所有關鍵方面。

        【分析要求】
        1. 書名分析：識別並提供完整書名
        2. 作者分析：識別作者姓名
        3. 作者背景：詳細研究作者背景、成就和寫作風格（至少500字）
        4. 書籍概述：提供全面的內容摘要，包括寫作目的、目標受眾和核心訊息（至少1000字）
        5. 章節分析：對每個章節進行深入分析，包括：
           - 章節編號和標題
           - 詳細章節摘要（每章至少500字）
           - 關鍵重點（至少5點）
           - 實際應用（至少300字）
        6. 關鍵概念：識別並解釋至少10個關鍵概念或術語，包括：
           - 術語名稱
           - 詳細定義（至少100字）
           - 實際應用案例（至少200字）
        7. 批判性分析：評估書籍的優缺點、創新點和局限性（至少800字）
        8. 比較分析：與同類書籍或理論比較（至少600字）
        9. 讀者建議：針對不同讀者群體提供閱讀建議（至少500字）
        10. 結論：總結書籍的整體價值和影響（至少400字）

        PDF 內容如下：
        ```
        {text}
        ```

        請以有效的 JSON 格式回傳結果，包含以下欄位：
        ```json
        {{
            "title": "書名",
            "author": "作者姓名",
            "author_background": "詳細作者背景（至少500字）",
            "book_overview": "書籍詳細概述（至少1000字）",
            "chapters_analysis": [
                {{
                    "chapter_number": "章節編號（如有）",
                    "chapter_title": "章節標題",
                    "summary": "詳細章節摘要（至少500字）",
                    "key_points": ["關鍵點1", "關鍵點2", "關鍵點3", "關鍵點4", "關鍵點5"],
                    "practical_applications": "實際應用說明（至少300字）"
                }}
            ],
            "key_concepts": [
                {{
                    "term": "術語名稱",
                    "definition": "詳細定義（至少100字）",
                    "applications": "實際應用案例（至少200字）"
                }}
            ],
            "critical_analysis": "批判性分析（至少800字）",
            "comparative_analysis": "比較分析（至少600字）",
            "reader_recommendations": "讀者建議（至少500字）",
            "conclusion": "結論（至少400字）"
        }}
        ```

        請確保：
        1. 嚴格遵循提供的JSON結構
        2. 總字數不少於7000字
        3. 分析深入且有洞察力
        4. 所有章節和概念都得到全面覆蓋
        5. 不包含佔位符或一般性陳述
        """
        
        # 呼叫 DeepSeek API
        client = DeepseekClient(DEEPSEEK_API_KEY)
        response = client.extract_content(prompt)
        
        # 記錄處理時間
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(elapsed_time, 60)
        logger.info(f"分析完成，耗時: {elapsed_time:.2f} 秒")
        
        return response
    
    except Exception as e:
        error_message = f"分析 PDF 內容時發生錯誤：{str(e)}"
        logger.error(error_message)
        traceback.print_exc()
        return json.dumps({"error": error_message}, ensure_ascii=False)

def process_large_pdf(text):
    """處理大型PDF文本，將其分段送入DeepSeek API進行分析，然後合併結果"""
    start_time = time.time()
    
    try:
        # 檢查token數量
        estimated_tokens = estimate_tokens(text)
        logging.info(f"估計PDF文本約含有 {estimated_tokens} tokens")
        
        # 如果文本過大，分段處理
        if estimated_tokens > 40000:
            logging.info("PDF文本較長，將進行分段處理")
            
            # 分割文本為更小的片段，每段最多25000 tokens
            chunks = split_text_into_chunks(text, max_tokens=25000)
            logging.info(f"文本已分割為 {len(chunks)} 個部分")
            
            # 取第一部分用於基本資訊提取
            first_part = chunks[0]
            
            # 如果超過10個分段，只取10%的部分進行處理
            if len(chunks) > 10:
                logging.info(f"文本過大，將只取前 {max(5, len(chunks)//5)} 個和最後 {max(1, len(chunks)//10)} 個部分進行處理")
                sample_chunks = chunks[:max(5, len(chunks)//5)] + chunks[-max(1, len(chunks)//10):]
            else:
                sample_chunks = chunks
                
            logging.info(f"將PDF文本分割為 {len(sample_chunks)} 個部分進行處理")
            
            # 創建DeepseekClient客戶端
            client = DeepseekClient(DEEPSEEK_API_KEY)
            
            # 第一階段：處理第一個文本塊獲取基本信息和結構
            logger.info(f"第一階段：處理第一個文本塊獲取基本信息（1/{len(sample_chunks)}）")
            
            # 嘗試識別書籍的封面信息和封底，通常在前幾頁和最後幾頁
            first_part = sample_chunks[0]
            last_part = sample_chunks[-1] if len(sample_chunks) > 1 else ""
            cover_info = first_part[:2000] + "\n...\n" + last_part[-2000:] if last_part else first_part[:4000]
            
            base_prompt = f"""
            請仔細分析以下中文PDF書籍內容的封面、目錄和前言部分，提取書名、作者信息、書籍概述等基本信息。提供詳盡但精簡的分析，總字數嚴格控制在7500字以內。

            【分析要求】
            1. 書名分析：準確識別並提供完整書名，通常出現在封面或標題頁上
            2. 作者分析：準確識別作者全名，注意區分作者與譯者、編者
            3. 作者背景：簡要研究作者背景、成就和寫作風格（約300字）
            4. 書籍概述：提供內容摘要，包括寫作目的、目標受眾和核心訊息（約500字）
            5. 識別書中的主要主題和關鍵概念（不要以章節為分類）

            以下是PDF書籍的封面、目錄和前言部分：
            ```
            {cover_info}
            ```

            另外，以下是書籍的目錄或前言（如果存在）：
            ```
            {first_part}
            ```

            請以有效的JSON格式回傳結果：
            ```json
            {{
                "title": "完整書名（不含副標題）",
                "full_title": "完整書名（含副標題，如有）",
                "author": "作者姓名",
                "author_background": "作者背景（約300字）",
                "book_overview": "書籍概述（約500字）",
                "main_themes": ["主題1", "主題2", "主題3", "主題4", "主題5"]
            }}
            ```
            
            請確保：
            1. 書名和作者信息絕對準確，這是分析的基礎
            2. 作者背景和書籍概述要精煉，控制在指定字數內
            3. 主題列表應該反映書籍的核心內容，而非簡單的章節標題
            4. 嚴格遵循提供的JSON結構
            5. 不要捏造不確定的資訊，如確實找不到某項資訊，請標記為"未找到"
            """
            
            base_response = client.extract_content(base_prompt)
            
            try:
                base_data = json.loads(base_response)
                logger.info("成功獲取基本信息")
            except json.JSONDecodeError as e:
                logger.error(f"解析基本信息時發生錯誤: {e}")
                # 嘗試從回應中提取 JSON
                json_match = re.search(r'```json\s*([\s\S]*?)\s*```', base_response)
                if json_match:
                    try:
                        base_data = json.loads(json_match.group(1).strip())
                        logger.info("從文本中提取 JSON 成功")
                    except:
                        logger.error("無法從回應中提取有效 JSON")
                        return json.dumps({"error": "無法解析基本資訊回應"}, ensure_ascii=False)
                else:
                    logger.error("回應中找不到 JSON 格式內容")
                    return json.dumps({"error": "無法解析基本資訊回應"}, ensure_ascii=False)
            
            # 獲取書名和作者信息
            book_title = base_data.get("full_title", base_data.get("title", "未找到書名"))
            author_name = base_data.get("author", "未找到作者姓名")
            
            logger.info(f"書名: {book_title}")
            logger.info(f"作者: {author_name}")
            
            # 獲取主要主題
            main_themes = base_data.get("main_themes", [])
            if not main_themes:
                logger.warning("未找到主題列表，將自動分析主題")
                main_themes = ["輸出力法則", "高效工作", "生產力提升", "時間管理", "個人成長"]
            
            logger.info(f"找到 {len(main_themes)} 個主題，開始逐一分析")
            
            # 第二階段：處理主題分析
            logger.info("第二階段：處理主題分析")
            
            # 初始化最終結果
            final_result = {
                "title": book_title,
                "author": author_name,
                "author_background": base_data.get("author_background", ""),
                "book_overview": base_data.get("book_overview", ""),
                "themes_analysis": [],
                "key_concepts": [],
                "critical_analysis": "",
                "comparative_analysis": "",
                "reader_recommendations": "",
                "conclusion": ""
            }
            
            # 合併所有文本塊以便於主題分析
            all_text = "".join(sample_chunks)
            
            # 控制主題數量，僅分析前4-5個主要主題以控制字數
            max_themes = min(5, len(main_themes))
            important_themes = main_themes[:max_themes]
            logger.info(f"為控制總字數，將只分析前 {max_themes} 個主題")
            
            # 每次分析最多3個主題，避免超過API限制
            for i in range(0, len(important_themes), 3):
                theme_batch = important_themes[i:i+3]
                logger.info(f"分析主題 {i+1} 到 {i+len(theme_batch)}，共 {len(theme_batch)} 個主題")
                
                themes_prompt = f"""
                請對以下中文PDF書籍內容中的指定主題進行精簡分析，嚴格控制總字數，使最終報告不超過7500字。

                書名：{book_title}
                作者：{author_name}
                
                需要分析的主題：
                {', '.join(theme_batch)}

                PDF完整內容：
                ```
                {all_text}
                ```

                對於每個主題，請提供：
                1. 主題的詳細說明（約200-250字/主題）
                2. 2-3個相關核心觀點，每點簡潔說明（約50-70字/點）
                3. 簡短的實際應用指南（約100-150字/主題）

                請以有效的JSON格式回傳分析結果：
                ```json
                {{
                    "themes_analysis": [
                        {{
                            "theme_name": "主題名稱",
                            "description": "主題說明（約200-250字）",
                            "key_points": [
                                "核心觀點1：簡潔說明（約50-70字）",
                                "核心觀點2：簡潔說明（約50-70字）",
                                "核心觀點3：簡潔說明（約50-70字）"
                            ],
                            "practical_applications": "應用指南（約100-150字）"
                        }}
                    ]
                }}
                ```
                
                請確保：
                1. 提供精煉且簡潔的分析，避免冗長
                2. 嚴格控制每個部分的字數
                3. 只關注最核心的觀點和方法
                4. 準確展開關鍵觀點，但高度精簡
                5. 嚴格遵循JSON格式，確保格式正確無誤
                """
                
                themes_response = client.extract_content(themes_prompt)
                
                try:
                    themes_data = json.loads(themes_response)
                    if "themes_analysis" in themes_data and isinstance(themes_data["themes_analysis"], list):
                        final_result["themes_analysis"].extend(themes_data["themes_analysis"])
                        logger.info(f"成功獲取 {len(themes_data['themes_analysis'])} 個主題的分析")
                except:
                    logger.error("解析主題分析時發生錯誤")
                    # 嘗試從回應中提取 JSON
                    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', themes_response)
                    if json_match:
                        try:
                            themes_data = json.loads(json_match.group(1).strip())
                            if "themes_analysis" in themes_data and isinstance(themes_data["themes_analysis"], list):
                                final_result["themes_analysis"].extend(themes_data["themes_analysis"])
                                logger.info(f"從文本中提取 JSON 成功，獲取了 {len(themes_data['themes_analysis'])} 個主題的分析")
                        except:
                            logger.error("無法從回應中提取有效 JSON")
            
            # 第三階段：處理關鍵概念
            logger.info("第三階段：處理關鍵概念")
            
            concepts_prompt = f"""
            請基於以下中文PDF書籍內容的理解，提取並分析3-5個最關鍵概念。確保分析簡明扼要，嚴格控制字數。

            書名：{book_title}
            作者：{author_name}

            PDF內容：
            ```
            {sample_chunks[0] if len(sample_chunks) > 0 else text[:8000]}
            ```

            請為每個關鍵概念提供：
            1. 概念名稱和簡明定義（約70-90字）
            2. 概念的基本應用場景（約80-100字）

            請以有效的JSON格式回傳分析結果：
            ```json
            {{
                "key_concepts": [
                    {{
                        "term": "關鍵概念名稱",
                        "definition": "簡明定義（約70-90字）",
                        "applications": "基本應用場景（約80-100字）"
                    }},
                    {{
                        "term": "關鍵概念名稱2",
                        "definition": "簡明定義（約70-90字）",
                        "applications": "基本應用場景（約80-100字）"
                    }}
                    // 提供3-5個關鍵概念
                ]
            }}
            ```
            
            請確保：
            1. 只提供3-5個最核心的關鍵概念
            2. 嚴格控制每個概念的字數在規定範圍內
            3. 提供精準但簡短的概念分析
            4. 嚴格遵循JSON格式，確保格式正確無誤
            """
            
            concepts_response = client.extract_content(concepts_prompt)
            
            try:
                concepts_data = json.loads(concepts_response)
                if "key_concepts" in concepts_data and isinstance(concepts_data["key_concepts"], list):
                    final_result["key_concepts"] = concepts_data["key_concepts"]
                    logger.info(f"成功獲取 {len(concepts_data['key_concepts'])} 個關鍵概念")
            except:
                logger.error("解析關鍵概念時發生錯誤")
                # 嘗試從回應中提取 JSON
                json_match = re.search(r'```json\s*([\s\S]*?)\s*```', concepts_response)
                if json_match:
                    try:
                        concepts_data = json.loads(json_match.group(1).strip())
                        if "key_concepts" in concepts_data and isinstance(concepts_data["key_concepts"], list):
                            final_result["key_concepts"] = concepts_data["key_concepts"]
                            logger.info(f"從文本中提取 JSON 成功，獲取了 {len(concepts_data['key_concepts'])} 個關鍵概念")
                    except:
                        logger.error("無法從回應中提取有效 JSON")
            
            # 第四階段：批判性分析、比較分析和讀者建議
            logger.info("第四階段：處理批判性分析、比較分析和讀者建議")
            
            analysis_prompt = f"""
            請基於對《{book_title}》的理解，提供精簡的批判性分析、比較分析、讀者建議和總結。請嚴格控制總字數，使最終報告不超過7500字。

            【分析要求】
            1. 批判性分析（約200-250字）：
               - 書籍主要優點
               - 理論和方法的局限性
               - 適用範圍和條件
        
            2. 比較分析（約150-200字）：
               - 與同類書籍的簡要比較
               - 在相關領域的定位
               - 對讀者的價值
        
            3. 讀者建議（約150-200字）：
               - 適合的讀者群體
               - 閱讀建議
               - 如何應用書中方法
        
            4. 結論（約100-150字）：
               - 書籍整體評價
               - 核心價值

            書名：{book_title}
            作者：{author_name}

            請以有效的JSON格式回傳分析結果：
            ```json
            {{
                "critical_analysis": "批判性分析（約200-250字）",
                "comparative_analysis": "比較分析（約150-200字）",
                "reader_recommendations": "讀者建議（約150-200字）",
                "conclusion": "結論（約100-150字）"
            }}
            ```
            
            請確保：
            1. 分析要有深度但極其精簡
            2. 嚴格控制每個部分的字數
            3. 提供有價值但簡明的建議
            4. 評價客觀公正
            5. 嚴格遵循JSON格式，確保格式正確無誤
            """
            
            analysis_response = client.extract_content(analysis_prompt)
            
            try:
                analysis_data = json.loads(analysis_response)
                for field in ["critical_analysis", "comparative_analysis", "reader_recommendations", "conclusion"]:
                    if field in analysis_data:
                        final_result[field] = analysis_data[field]
                        logger.info(f"成功獲取{field}")
            except:
                logger.error("解析分析結果時發生錯誤")
                # 嘗試從回應中提取 JSON
                json_match = re.search(r'```json\s*([\s\S]*?)\s*```', analysis_response)
                if json_match:
                    try:
                        analysis_data = json.loads(json_match.group(1).strip())
                        for field in ["critical_analysis", "comparative_analysis", "reader_recommendations", "conclusion"]:
                            if field in analysis_data:
                                final_result[field] = analysis_data[field]
                                logger.info(f"從文本中提取 JSON 成功，獲取了{field}")
                    except:
                        logger.error("無法從回應中提取有效 JSON")
            
            # 返回最終合併結果
            elapsed_time = time.time() - start_time
            minutes, seconds = divmod(elapsed_time, 60)
            logger.info(f"大型PDF分析完成，總耗時: {int(minutes)}分{int(seconds)}秒")
            
            return json.dumps(final_result, ensure_ascii=False)
    
    except Exception as e:
        error_message = f"處理大型PDF時發生錯誤：{str(e)}"
        logger.error(error_message)
        traceback.print_exc()
        return json.dumps({"error": error_message}, ensure_ascii=False)

def split_large_text(text, max_chunk_size=5000):
    """
    將大型文本按一定大小分割，但嘗試以段落為單位切割，確保語意完整性
    """
    # 如果文本夠短，直接返回
    if len(text) <= max_chunk_size:
        return [text]
    
    chunks = []
    
    # 嘗試按章節分割
    chapter_patterns = [
        r'第[一二三四五六七八九十百零0-9１２３４５６７８９０]+[章節课]',  # 匹配"第一章"、"第1章"等格式
        r'Chapter\s+\d+',  # 匹配英文章節標題
        r'CHAPTER\s+\d+', 
        r'\n\d+[\.\s]+'   # 匹配數字+點+空格的格式
    ]
    
    # 合併所有章節模式
    combined_pattern = '|'.join(chapter_patterns)
    chapters = re.split(f'({combined_pattern})', text)
    
    current_chunk = ""
    for i in range(0, len(chapters), 2):
        if i < len(chapters):
            chapter_start = chapters[i]
            if i + 1 < len(chapters):
                chapter_title = chapters[i + 1]
                current_part = chapter_title + chapter_start
            else:
                current_part = chapter_start
                
            # 如果當前塊加上新章節超過最大大小，則保存當前塊並開始新塊
            if len(current_chunk) + len(current_part) > max_chunk_size and current_chunk:
                chunks.append(current_chunk)
                current_chunk = current_part
            else:
                current_chunk += current_part
    
    # 添加最後一個塊
    if current_chunk:
        chunks.append(current_chunk)
    
    # 如果按章節分割無效（例如沒有找到章節標記），則按段落分割
    if not chunks:
        paragraphs = text.split('\n\n')
        current_chunk = ""
        
        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 > max_chunk_size and current_chunk:
                chunks.append(current_chunk)
                current_chunk = para
            else:
                if current_chunk:
                    current_chunk += '\n\n'
                current_chunk += para
        
        if current_chunk:
            chunks.append(current_chunk)
    
    # 如果連段落分割也無效，則直接按字符數分割
    if not chunks:
        for i in range(0, len(text), max_chunk_size):
            chunks.append(text[i:i + max_chunk_size])
    
    logger.info(f"文本已分割為 {len(chunks)} 個部分")
    return chunks

# DeepSeek API 客戶端
class DeepseekClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
    def extract_content(self, prompt):
        """使用 DeepSeek API 擷取內容"""
        try:
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 8192
            }
            
            logger.info("發送請求至 DeepSeek API...")
            response = requests.post(self.api_url, json=payload, headers=self.headers)
            
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                logger.info("成功從 DeepSeek API 獲取回應")
                
                # 尝试提取 JSON 部分（如果存在）
                json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
                if json_match:
                    json_str = json_match.group(1).strip()
                    try:
                        # 验证 JSON 是否有效
                        parsed_json = json.loads(json_str)
                        return json.dumps(parsed_json, ensure_ascii=False)
                    except json.JSONDecodeError:
                        logger.warning("無法解析返回的 JSON 格式，返回原始內容")
                        return content
                else:
                    logger.warning("回應中找不到 JSON 格式，返回原始內容")
                    return content
            else:
                error_msg = f"DeepSeek API 請求失敗: HTTP {response.status_code}, {response.text}"
                logger.error(error_msg)
                return json.dumps({"error": error_msg}, ensure_ascii=False)
                
        except Exception as e:
            error_msg = f"呼叫 DeepSeek API 時發生錯誤: {str(e)}"
            logger.error(error_msg)
            traceback.print_exc()
            return json.dumps({"error": error_msg}, ensure_ascii=False)

# ==========================
# Step 1: 使用 PyPDF2 擷取PDF內容，再使用 deepseek API 分析
# ==========================
def extract_content(input_file, max_retries=3):
    """使用 PyPDF2 先擷取PDF文字內容，再使用 deepseek API 進行分析，支援重試機制"""
    # 首先使用PyPDF2提取PDF文本
    pdf_text = extract_pdf_text(input_file)
    
    # 如果提取的文本太長，則分段處理（DeepSeek API有輸入長度限制）
    if len(pdf_text) > 100000:  # 字元數限制
        logger.warning(f"PDF文本過長 ({len(pdf_text)} 字元)，將進行分段處理")
        # 這裡只取前100K字元進行分析，實際應用時可能需要更複雜的分段處理邏輯
        pdf_text = pdf_text[:100000]
    
    for attempt in range(max_retries):
        try:
            # 實例化 DeepseekClient 客戶端，連接至 DeepSeek API
            client = DeepseekClient(DEEPSEEK_API_KEY)
            
            logger.info(f"呼叫 DeepSeek API 分析PDF內容 (第 {attempt+1} 次嘗試)...")
            
            # 呼叫DeepSeek API，使用 DeepseekClient 類
            response = client.extract_content(pdf_text)
            
            # 處理回應
            content = response
            
            # 記錄原始回應內容，幫助調試
            logger.info(f"DeepSeek API 回應原始內容的前500字元: {content[:500]}")
            
            # 嘗試解析JSON
            try:
                extracted_data = json.loads(content)
                
                # 記錄解析後的數據結構，幫助調試
                logger.info(f"解析後的JSON數據結構: {json.dumps(extracted_data, ensure_ascii=False)[:500]}")
                
                # 標準化資料結構
                result = {
                    "title": extracted_data.get("title", extracted_data.get("標題", "無標題")),
                    "summary": extracted_data.get("executive_summary", extracted_data.get("summary", extracted_data.get("摘要", extracted_data.get("重點摘要", "無摘要")))),
                    "toc": extracted_data.get("table_of_contents", extracted_data.get("toc", extracted_data.get("目錄", "無目錄"))),
                    "chapters": []
                }
                
                # 處理章節內容
                chapters = extracted_data.get("chapter_analysis", extracted_data.get("chapters", extracted_data.get("各章節詳細內容", [])))
                if isinstance(chapters, dict):
                    # 如果是字典格式，將其轉換為列表格式
                    chapters_list = []
                    for title, content in chapters.items():
                        chapters_list.append({
                            "title": title,
                            "content": content
                        })
                    chapters = chapters_list
                
                if isinstance(chapters, list):
                    for chapter in chapters:
                        if isinstance(chapter, dict):
                            result["chapters"].append({
                                "title": chapter.get("title", "無標題章節"),
                                "content": chapter.get("content", "")
                            })
                        else:
                            result["chapters"].append({
                                "title": f"章節 {len(result['chapters'])+1}",
                                "content": str(chapter)
                            })
                
                logger.info(f"標準化後的資料結構: title={result['title']}, summary長度={len(result['summary'])}, chapters數量={len(result['chapters'])}")
                return result
                
            except json.JSONDecodeError:
                logger.error(f"無法解析DeepSeek回應為JSON: {content[:500]}...")
                if attempt == max_retries - 1:
                    raise Exception("無法解析DeepSeek回應為JSON")
                time.sleep(2 ** attempt)
                
        except Exception as e:
            logger.error(f"分析過程發生錯誤: {str(e)}")
            if attempt == max_retries - 1:
                raise Exception(f"分析過程失敗，已嘗試 {max_retries} 次: {str(e)}")
            time.sleep(2 ** attempt)  # 指數退避
    
    raise Exception("所有分析嘗試均失敗")

def extract_pdf_text(pdf_file):
    """使用PyPDF2從PDF提取文本"""
    logger.info(f"開始從PDF提取文本: {pdf_file}")
    
    try:
        # 計算檔案大小
        file_size = os.path.getsize(pdf_file)
        logger.info(f"PDF檔案大小: {file_size / 1024 / 1024:.2f} MB")
        
        text = ""
        with open(pdf_file, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            num_pages = len(reader.pages)
            logger.info(f"PDF頁數: {num_pages}")
            
            # 提取每頁文本
            for page_num in range(num_pages):
                page = reader.pages[page_num]
                page_text = page.extract_text()
                if page_text:
                    text += f"\n--- 第 {page_num+1} 頁 ---\n{page_text}"
        
        # 檢查是否成功提取文本
        if not text.strip():
            logger.warning("未能提取到任何文本，PDF可能包含掃描圖片或受保護")
            return "未能提取到文本，PDF可能包含掃描圖片或受保護。"
        
        logger.info(f"成功提取文本，共 {len(text)} 個字元")
        return text
        
    except Exception as e:
        logger.error(f"PDF文本提取失敗: {e}")
        return f"PDF文本提取失敗: {e}"

# ==========================
# Step 2: 利用 DeepL API 進行翻譯，並轉換成繁體中文
# ==========================
def translate_text(text, max_retries=3):
    if not text or text == "無摘要" or text == "無目錄":
        return text

    # 如果是字典類型，先轉為JSON字串
    if isinstance(text, dict) or isinstance(text, list):
        return text  # 直接返回字典或列表，不翻譯目錄結構

    # 處理純文本
    retry_count = 0
    while retry_count < max_retries:
        retry_count += 1
        try:
            logging.info(f"呼叫 DeepL API 進行翻譯 (第 {retry_count} 次嘗試)...")
            params = {
                "auth_key": DEEPL_API_KEY,
                "text": text,
                "target_lang": "ZH-HANT",  # 指定繁體中文作為目標語言
                "tag_handling": "xml",  # 保留格式標籤
                "formality": "default",  # 語氣：正式/非正式
                "preserve_formatting": True,  # 保留原文格式
                "split_sentences": "1"  # 保持句子完整性
            }
            response = requests.post(
                DEEPL_API_URL, 
                data=params,
                timeout=30  # 設定30秒超時
            )
            
            if response.status_code != 200:
                logger.error(f"DeepL API 請求失敗，狀態碼：{response.status_code}，回應內容：{response.text}")
                if retry_count == max_retries - 1:
                    raise Exception(f"DeepL API 請求失敗，狀態碼：{response.status_code}")
                time.sleep(2 ** retry_count)  # 指數退避
                continue
            
            result = response.json()
            translated_text = result["translations"][0]["text"]
            
            # 由於已經直接指定ZH-HANT作為目標語言，不需要額外轉換
            # 但保留此轉換以確保繁體字符的一致性
            traditional_text = cc.convert(translated_text)
            return traditional_text
            
        except Exception as e:
            logger.error(f"翻譯過程發生錯誤: {str(e)}")
            if retry_count == max_retries - 1:
                raise Exception(f"翻譯過程失敗，已嘗試 {max_retries} 次: {str(e)}")
            time.sleep(2 ** retry_count)  # 指數退避
    
    raise Exception("所有翻譯嘗試均失敗")

def process_chapters_for_translation(chapters):
    """特別處理章節資料結構，將其準備為可翻譯的格式"""
    result = []
    
    # 處理章節字典為章節列表
    if isinstance(chapters, dict):
        for title, content in chapters.items():
            result.append({
                "title": title,
                "content": content
            })
    elif isinstance(chapters, list):
        result = chapters
    
    return result

def translate_content(data):
    """翻譯所有內容"""
    logger.info("步驟2: 翻譯內容")
    
    try:
        # 將數據轉換為JSON物件，如果傳入的是字符串
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                logger.error("數據不是有效的JSON格式")
                return {"error": "數據格式無效"}
        
        # 翻譯標題
        logger.info("翻譯 title 內容...")
        if "title" in data:
            data["title"] = translate_text(data["title"])
        
        # 翻譯作者背景
        if "author_context" in data:
            logger.info("翻譯 author_context 內容...")
            data["author_context"] = translate_text(data["author_context"])
        
        # 翻譯執行摘要
        if "executive_summary" in data:
            logger.info("翻譯 executive_summary 內容...")
            data["executive_summary"] = translate_text(data["executive_summary"])
        
        # 翻譯結構分析
        if "structure_analysis" in data and isinstance(data["structure_analysis"], dict):
            logger.info("翻譯 structure_analysis 內容...")
            for key in data["structure_analysis"]:
                data["structure_analysis"][key] = translate_text(data["structure_analysis"][key])
        
        # 翻譯章節分析
        if "chapter_analysis" in data and isinstance(data["chapter_analysis"], list):
            logger.info(f"翻譯 chapter_analysis 清單 ({len(data['chapter_analysis'])} 個項目)...")
            for i, chapter in enumerate(data["chapter_analysis"]):
                try:
                    if isinstance(chapter, dict):
                        if "title" in chapter:
                            chapter["title"] = translate_text(chapter["title"])
                        if "content" in chapter:
                            chapter["content"] = translate_text(chapter["content"])
                    else:
                        logger.warning(f"章節 {i} 格式不正確，跳過翻譯")
                except Exception as e:
                    logger.error(f"翻譯第 {i} 個章節時發生錯誤: {str(e)}")
        
        # 翻譯關鍵概念
        if "key_concepts" in data and isinstance(data["key_concepts"], dict):
            logger.info(f"翻譯 key_concepts 內容 ({len(data['key_concepts'])} 個項目)...")
            translated_concepts = {}
            for concept, definition in data["key_concepts"].items():
                try:
                    translated_concept = translate_text(concept)
                    translated_definition = translate_text(definition)
                    translated_concepts[translated_concept] = translated_definition
                except Exception as e:
                    logger.error(f"翻譯概念 '{concept}' 時發生錯誤: {str(e)}")
                    translated_concepts[concept] = definition
            data["key_concepts"] = translated_concepts
        
        # 翻譯思想地圖
        if "thought_map" in data:
            logger.info("翻譯 thought_map 內容...")
            data["thought_map"] = translate_text(data["thought_map"])
        
        # 翻譯批判性分析
        if "critical_analysis" in data:
            logger.info("翻譯 critical_analysis 內容...")
            data["critical_analysis"] = translate_text(data["critical_analysis"])
        
        # 翻譯實踐應用
        if "practical_application" in data:
            logger.info("翻譯 practical_application 內容...")
            data["practical_application"] = translate_text(data["practical_application"])
        
        # 翻譯延伸閱讀
        if "extended_reading" in data:
            logger.info("翻譯 extended_reading 內容...")
            data["extended_reading"] = translate_text(data["extended_reading"])
        
        # 翻譯值得探討的論點
        if "debatable_points" in data:
            logger.info("翻譯 debatable_points 內容...")
            if isinstance(data["debatable_points"], str):
                data["debatable_points"] = translate_text(data["debatable_points"])
            elif isinstance(data["debatable_points"], list):
                translated_points = []
                for point in data["debatable_points"]:
                    if isinstance(point, dict):
                        translated_point = {
                            "point": translate_text(point.get("point", "")),
                            "analysis": translate_text(point.get("analysis", ""))
                        }
                        translated_points.append(translated_point)
                    else:
                        translated_points.append(translate_text(point))
                data["debatable_points"] = translated_points
        
        # 處理舊版API返回格式的兼容性
        # 翻譯摘要（可能是列表或字串）
        if "summary" in data:
            summary = data["summary"]
            if isinstance(summary, list):
                logger.info(f"翻譯 summary 清單 ({len(summary)} 個項目)...")
                translated_summary = []
                for i, item in enumerate(summary):
                    try:
                        translated_summary.append(translate_text(item))
                    except Exception as e:
                        logger.error(f"翻譯第 {i} 項失敗: {str(e)}")
                data["summary"] = translated_summary
            else:
                logger.info("翻譯 summary 內容...")
                data["summary"] = translate_text(data["summary"])
        
        # 翻譯目錄（可能是列表或字串）
        if "toc" in data:
            toc = data["toc"]
            if isinstance(toc, list):
                logger.info(f"翻譯 toc 清單 ({len(toc)} 個項目)...")
                translated_toc = []
                for i, item in enumerate(toc):
                    try:
                        translated_toc.append(translate_text(item))
                    except Exception as e:
                        logger.error(f"翻譯第 {i} 項失敗: {str(e)}")
                data["toc"] = translated_toc
            else:
                logger.info("翻譯 toc 內容...")
                data["toc"] = translate_text(data["toc"])
        
        # 舊版章節格式處理
        if "chapters" in data:
            chapters = process_chapters_for_translation(data["chapters"])
            if chapters:
                logger.info(f"翻譯 chapters 清單 ({len(chapters)} 個項目)...")
                translated_chapters = []
                for i, chapter in enumerate(chapters):
                    try:
                        if isinstance(chapter, dict):
                            translated_chapters.append({
                                "title": translate_text(chapter.get("title", "")),
                                "content": translate_text(chapter.get("content", ""))
                            })
                        else:
                            logger.warning(f"章節 {i} 格式不正確，跳過翻譯")
                    except Exception as e:
                        logger.error(f"翻譯第 {i} 項失敗: {str(e)}")
                data["chapters"] = translated_chapters
            else:
                logger.info("翻譯 chapters 清單 (0 個項目)...")
        
        # 翻譯延伸知識和關聯內容
        if "extended_knowledge" in data:
            extended_knowledge = data.get("extended_knowledge", "")
            if extended_knowledge:
                logger.info("翻譯 extended_knowledge 內容...")
                data["extended_knowledge"] = translate_text(extended_knowledge)
        
        # 翻譯專業術語表
        if "terminology" in data:
            terminology = data.get("terminology", "")
            if terminology:
                logger.info("翻譯 terminology 內容...")
                data["terminology"] = translate_text(terminology)
        
        return data
    except Exception as e:
        logger.error(f"翻譯內容時發生錯誤: {str(e)}")
        traceback.print_exc()
        return {"error": f"翻譯內容時發生錯誤: {str(e)}"}

# ==========================
# Step 3: 產生 PDF 檔案
# ==========================
class PDFWithPageNumbers(FPDF):
    """增強版PDF產生器，支援中文"""
    
    def __init__(self, orientation='P', unit='mm', format='A4'):
        super().__init__(orientation=orientation, unit=unit, format=format)
        # 使用 FPDF 內建的字體
        self.add_font('Arial', '', 'arial.ttf', uni=True)
        
    def header(self):
        """自定義頁首"""
        # 使用 Arial 替代中文字體
        self.set_font('Arial', '', 8)
        self.cell(0, 10, "DeepSeek 分析報告 - " + datetime.now().strftime("%Y-%m-%d"), 0, align='R')
        self.ln(15)
        
    def footer(self):
        """自定義頁尾"""
        self.set_y(-15)
        # 使用 Arial 替代中文字體
        self.set_font('Arial', '', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, align='C')

def generate_pdf(data, output_file):
    """根據分析結果產生PDF檔案，使用簡單格式"""
    try:
        # 由於 FPDF 對中文支持有限，我們選擇只輸出簡單的英文內容
        pdf = FPDF(orientation='P', unit='mm', format='A4')
        
        # 設定檔案資訊
        title = data.get("title", "Document Analysis Report")
        pdf.set_title("Analysis Report")
        pdf.set_author("DeepSeek Document Analysis Tool")
        pdf.set_creator("DeepSeek Document Analysis Tool")
        
        # 新增扉頁
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 20, "Analysis Report", 0, 1, 'C')
        pdf.ln(10)
        
        pdf.set_font("Helvetica", "", 12)
        pdf.multi_cell(0, 10, "The complete analysis is available in the Markdown file.")
        pdf.ln(5)
        
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, "Note:", 0, 1)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 10, "Due to font restrictions, Chinese content is only fully displayed in the Markdown report. Please refer to the .md file for the complete analysis.")
        
        # 保存到檔案
        pdf.output(output_file)
        
        logger.info(f"PDF 檔案已儲存：{output_file}")
        return True
        
    except Exception as e:
        logger.error(f"PDF 生成錯誤: {e}")
        traceback.print_exc()
        return False

# ==========================
# Step 3: 產生 Markdown 檔案
# ==========================
def generate_markdown(translated_data, output_file):
    """根據分析結果產生Markdown檔案"""
    try:
        title = translated_data.get("title", "無標題")
        author = translated_data.get("author", "")
        author_background = translated_data.get("author_background", "")
        book_overview = translated_data.get("book_overview", "")
        chapters_analysis = translated_data.get("chapters_analysis", [])
        key_concepts = translated_data.get("key_concepts", [])
        critical_analysis = translated_data.get("critical_analysis", "")
        comparative_analysis = translated_data.get("comparative_analysis", "")
        reader_recommendations = translated_data.get("reader_recommendations", "")
        conclusion = translated_data.get("conclusion", "")
        
        # 創建 Markdown 文字
        markdown_content = f"# {title} 分析報告\n\n"
        
        # 添加作者
        if author:
            markdown_content += f"## 作者\n\n{author}\n\n"
            
        # 添加作者背景
        if author_background:
            markdown_content += f"## 作者背景\n\n{author_background}\n\n"
        
        # 添加書籍概述
        if book_overview:
            markdown_content += f"## 書籍概述\n\n{book_overview}\n\n"
        
        # 添加目錄
        markdown_content += "## 目錄\n\n"
        markdown_content += "1. [作者背景](#作者背景)\n"
        markdown_content += "2. [書籍概述](#書籍概述)\n"
        markdown_content += "3. [章節分析](#章節分析)\n"
        markdown_content += "4. [關鍵概念](#關鍵概念)\n"
        markdown_content += "5. [批判性分析](#批判性分析)\n"
        if comparative_analysis:
            markdown_content += "6. [比較分析](#比較分析)\n"
            markdown_content += "7. [讀者建議](#讀者建議)\n"
            markdown_content += "8. [結論](#結論)\n\n"
        else:
            markdown_content += "6. [結論](#結論)\n\n"
        
        # 添加章節分析
        markdown_content += "## 章節分析\n\n"
        
        for chapter in chapters_analysis:
            chapter_number = chapter.get("chapter_number", "")
            chapter_title = chapter.get("chapter_title", "未知章節")
            summary = chapter.get("summary", "")
            key_points = chapter.get("key_points", [])
            practical_applications = chapter.get("practical_applications", "")
            
            # 創建章節標題
            if chapter_number:
                markdown_content += f"### {chapter_number}. {chapter_title}\n\n"
            else:
                markdown_content += f"### {chapter_title}\n\n"
            
            # 添加章節摘要
            if summary:
                markdown_content += f"{summary}\n\n"
            
            # 添加關鍵點
            if key_points:
                markdown_content += "**關鍵重點：**\n\n"
                for point in key_points:
                    markdown_content += f"- {point}\n"
                markdown_content += "\n"
            
            # 添加實際應用
            if practical_applications:
                markdown_content += "**實際應用：**\n\n"
                markdown_content += f"{practical_applications}\n\n"
            
            markdown_content += "---\n\n"
        
        # 添加關鍵概念
        markdown_content += "## 關鍵概念\n\n"
        
        if key_concepts:
            for concept in key_concepts:
                term = concept.get("term", "")
                definition = concept.get("definition", "")
                applications = concept.get("applications", "")
                
                if term:
                    markdown_content += f"### {term}\n\n"
                    
                    if definition:
                        markdown_content += f"**定義：** {definition}\n\n"
                    
                    if applications:
                        markdown_content += f"**應用：** {applications}\n\n"
        
        # 添加批判性分析
        if critical_analysis:
            markdown_content += "## 批判性分析\n\n"
            markdown_content += f"{critical_analysis}\n\n"
        
        # 添加比較分析
        if comparative_analysis:
            markdown_content += "## 比較分析\n\n"
            markdown_content += f"{comparative_analysis}\n\n"
        
        # 添加讀者建議
        if reader_recommendations:
            markdown_content += "## 讀者建議\n\n"
            markdown_content += f"{reader_recommendations}\n\n"
        
        # 添加結論
        if conclusion:
            markdown_content += "## 結論\n\n"
            markdown_content += f"{conclusion}\n\n"
        
        # 保存到文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        
        logger.info(f"Markdown 檔案已儲存：{output_file}")
        return True
    except Exception as e:
        logger.error(f"生成Markdown時發生錯誤: {e}")
        traceback.print_exc()
        return False

# ==========================
# 主流程
# ==========================
def process_single_file(input_file, output_folder):
    """處理單一PDF檔案的完整流程"""
    try:
        start_time = time.time()
        logger.info(f"開始處理檔案: {os.path.basename(input_file)}")
        
        # 1. 呼叫 deepseek API 分析中文 PDF 內容
        logger.info("步驟1: 分析 PDF 內容")
        extract_start = time.time()
        extracted_data_str = analyze_pdf_with_deepseek(extract_pdf_text(input_file))
        
        # 記錄原始回應長度以便調試
        logger.info(f"API回應長度: {len(extracted_data_str)} 字符")
        logger.debug(f"API回應前200字符: {extracted_data_str[:200]}")
        
        # 將 JSON 字串轉換為 Python 字典
        try:
            # 先檢查回應是否包含JSON格式的回應
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', extracted_data_str)
            if json_match:
                json_str = json_match.group(1).strip()
                logger.info("從回應中提取JSON格式文本")
                extracted_data = json.loads(json_str)
            else:
                # 直接嘗試解析整個回應
                extracted_data = json.loads(extracted_data_str)
        except json.JSONDecodeError as e:
            logger.error(f"無法解析 DeepSeek API 回傳的 JSON 格式: {e}")
            # 嘗試查找可能的JSON部分
            potential_json = re.search(r'(\{[^{]*"title"[^}]*\})', extracted_data_str)
            if potential_json:
                try:
                    logger.info("嘗試解析可能的JSON部分")
                    extracted_data = json.loads(potential_json.group(1))
                except:
                    return {
                        "filename": os.path.basename(input_file),
                        "success": False,
                        "error": f"無法解析 JSON 格式: {e}"
                    }
            else:
                logger.error("回應中找不到 JSON 格式內容")
                return {
                    "filename": os.path.basename(input_file),
                    "success": False,
                    "error": f"無法解析 JSON 格式: {e}"
                }
            
        logger.info(f"分析完成，耗時: {time.time() - extract_start:.2f} 秒")
        
        # 2. 檔案命名依據原始檔名產生檔案名稱
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        md_output = os.path.join(output_folder, f"{base_name}_分析報告.md")
        
        # 產生 Markdown 檔案
        logger.info("步驟2: 產生Markdown")
        md_start = time.time()
        md_result = generate_markdown(extracted_data, md_output)
        logger.info(f"Markdown生成{'成功' if md_result else '失敗'}，耗時: {time.time() - md_start:.2f} 秒")
        
        total_time = time.time() - start_time
        logger.info(f"檔案處理完成，總耗時: {total_time:.2f} 秒")
        
        return {
            "filename": os.path.basename(input_file),
            "success": md_result,
            "md_output": md_output,
            "time_elapsed": total_time
        }
        
    except Exception as e:
        logger.error(f"處理檔案 {os.path.basename(input_file)} 時發生錯誤：{str(e)}")
        traceback.print_exc()
        return {
            "filename": os.path.basename(input_file),
            "success": False,
            "error": str(e)
        }

def main():
    """主流程"""
    parser = argparse.ArgumentParser(description="Deepseek 文件分析與翻譯工具")
    
    # 輸入參數組 - 互斥，只能選一個
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--input", help="單一PDF檔案路徑")
    input_group.add_argument("--input-dir", help="輸入目錄路徑，將處理該目錄下所有PDF檔案")
    input_group.add_argument("--test", action="store_true", help="執行整合測試")
    
    parser.add_argument("--output", dest="output_dir", help="輸出目錄路徑")
    parser.add_argument("--max-workers", type=int, default=4, 
                        help="最大並行處理線程數")
    parser.add_argument("--max-files", type=int, default=0,
                        help="最大處理檔案數量 (0=全部)")
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error"], default="info",
                        help="日誌級別")
    
    args = parser.parse_args()
    
    # 設定日誌級別
    log_levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR
    }
    logger.setLevel(log_levels[args.log_level])
    
    # 執行測試模式
    if args.test:
        test_integration()
        return
    
    # 檢查必要參數
    if not args.input and not args.input_dir:
        parser.error("請提供 --input 或 --input-dir 參數")
        
    if not args.output_dir:
        parser.error("請提供 --output 參數")
    
    # 建立輸出目錄
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
        logger.info(f"已建立輸出目錄: {args.output_dir}")
    
    # 處理單一檔案模式
    if args.input:
        if not os.path.isfile(args.input):
            logger.error(f"輸入檔案不存在或不是檔案: {args.input}")
            return
        
        if not args.input.lower().endswith('.pdf'):
            logger.error(f"輸入檔案不是PDF格式: {args.input}")
            return
            
        # 執行單一檔案處理
        result = process_single_file(args.input, args.output_dir)
        if result["success"]:
            logger.info(f"成功處理檔案: {result['filename']}")
        else:
            logger.error(f"處理檔案失敗: {result['filename']}, 錯誤: {result.get('error', '未知錯誤')}")
        return
    
    # 處理目錄模式
    if args.input_dir:
        if not os.path.exists(args.input_dir):
            logger.error(f"輸入目錄不存在: {args.input_dir}")
            return
        
        if not os.path.isdir(args.input_dir):
            logger.error(f"指定的輸入路徑不是目錄: {args.input_dir}")
            return
        
        pdf_files = [os.path.join(args.input_dir, f) for f in os.listdir(args.input_dir) 
                    if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(args.input_dir, f))]
        
        if not pdf_files:
            logger.warning(f"沒有找到PDF檔案於目錄: {args.input_dir}")
            return
        
        # 限制處理檔案數量
        if args.max_files > 0 and len(pdf_files) > args.max_files:
            logger.info(f"限制處理檔案數量為 {args.max_files} (共有 {len(pdf_files)} 個檔案)")
            pdf_files = pdf_files[:args.max_files]
        
        logger.info(f"找到 {len(pdf_files)} 個PDF檔案需要處理")
        
        # 開始處理檔案
        results = []
        for i, pdf_file in enumerate(pdf_files):
            logger.info(f"處理檔案 ({i+1}/{len(pdf_files)}): {os.path.basename(pdf_file)}")
            result = process_single_file(pdf_file, args.output_dir)
            results.append(result)
        
        # 輸出統計
        success_count = sum(1 for r in results if r["success"])
        logger.info("\n===== 處理結果統計 =====")
        logger.info(f"總檔案數: {len(results)}")
        logger.info(f"成功處理: {success_count}")
        logger.info(f"失敗檔案: {len(results) - success_count}")
        
        if len(results) - success_count > 0:
            logger.info("\n失敗檔案清單:")
            for r in results:
                if not r["success"]:
                    logger.info(f"- {r['filename']}: {r.get('error', '未知錯誤')}")
    
    logger.info(f"\n處理完成，輸出目錄: {args.output_dir}")

def test_integration():
    """端對端整合測試"""
    logger.info("開始執行整合測試...")
    
    # 建立測試目錄
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_output")
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)
    
    # 測試API連線狀態
    logger.info("測試 DeepL API 連線...")
    try:
        test_text = "Hello, world!"
        translated_text = translate_text(test_text)
        logger.info(f"DeepL API 連線成功，測試翻譯: {test_text} -> {translated_text}")
    except Exception as e:
        logger.error(f"DeepL API 連線測試失敗: {str(e)}")
        return False
    
    # 測試輸出 PDF 生成
    logger.info("測試 PDF 生成...")
    try:
        # 使用與優化後數據結構兼容的測試數據
        test_data = {
            "title": "測試文件",
            "author": "測試作者",
            "author_background": "這是一位虛構的測試作者的背景介紹，用於測試系統功能。",
            "book_overview": "這是一個自動生成的測試文件概述，用於驗證系統功能是否正常運作。",
            "chapters_analysis": [
                {
                    "chapter_number": "1",
                    "chapter_title": "第一章：介紹",
                    "summary": "本章介紹了研究背景與重要性...",
                    "key_points": ["關鍵點1: 詳細解釋", "關鍵點2: 詳細解釋"],
                    "practical_applications": "實際應用說明內容..."
                },
                {
                    "chapter_number": "2",
                    "chapter_title": "第二章：方法",
                    "summary": "本章詳述了研究方法與流程...",
                    "key_points": ["關鍵點1: 詳細解釋", "關鍵點2: 詳細解釋"],
                    "practical_applications": "實際應用說明內容..."
                }
            ],
            "key_concepts": [
                {
                    "term": "測試概念1",
                    "definition": "這是測試概念1的詳細定義。",
                    "applications": "這是測試概念1的應用說明。"
                },
                {
                    "term": "測試概念2",
                    "definition": "這是測試概念2的詳細定義。",
                    "applications": "這是測試概念2的應用說明。"
                }
            ],
            "critical_analysis": "這是一段批判性分析的測試文本。",
            "comparative_analysis": "這是一段比較分析的測試文本。",
            "reader_recommendations": "這是一段閱讀建議的測試文本。",
            "conclusion": "這是一段結論的測試文本。"
        }
        test_output = os.path.join(test_dir, "test_output.pdf")
        pdf_result = generate_pdf(test_data, test_output)
        if pdf_result:
            logger.info(f"PDF 測試生成成功: {test_output}")
        else:
            logger.error("PDF 生成測試失敗")
            return False
    except Exception as e:
        logger.error(f"PDF 生成測試過程中發生錯誤: {str(e)}")
        traceback.print_exc()
        return False
    
    # 測試輸出 Markdown 生成
    logger.info("測試 Markdown 生成...")
    try:
        test_output = os.path.join(test_dir, "test_output.md")
        md_result = generate_markdown(test_data, test_output)
        if md_result:
            logger.info(f"Markdown 測試生成成功: {test_output}")
        else:
            logger.error("Markdown 生成測試失敗")
            return False
    except Exception as e:
        logger.error(f"Markdown 生成測試過程中發生錯誤: {str(e)}")
        traceback.print_exc()
        return False
    
    logger.info("整合測試完成，一切正常！")
    return True

if __name__ == "__main__":
    main()
