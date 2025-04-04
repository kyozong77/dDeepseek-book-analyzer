# 深度書籍分析工具 (Deep Book Analyzer)

一個強大的PDF書籍分析工具，使用AI生成深度分析報告，透過多階段處理提供超過15,000字的詳盡內容分析。

## 主要功能

- **多階段AI分析**：將一本書的分析分為7個獨立部分，每部分由專門的AI提示詞生成
- **深度內容理解**：提供書籍的理論框架、關鍵論點、方法論、實用指引等多維度分析
- **批判性思維**：不只總結內容，還提供觀點評價和反思
- **跨領域啟示**：探討書中理念在不同領域的應用潛力
- **高品質輸出**：生成結構清晰、內容豐富的Markdown格式報告
- **支援中文**：全面支援繁體中文輸出
- **翻譯功能**：支援使用OpenAI或DeepL進行內容翻譯

## 分析報告包含

- **導論與整體定位**：書籍概覽、作者背景、理論框架
- **核心摘要**：關鍵論點解析、方法論與案例分析
- **批判分析**：章節深度剖析、實用指引、跨領域啟示
- **批判性反思**：書籍觀點評估、當代價值與時代侷限、延伸閱讀建議

## 安裝與設置

### 1. 安裝依賴套件

```bash
pip install -r requirements.txt
```

### 2. 配置API密鑰

創建`.env`檔案，包含以下內容：

```bash
DEEPSEEK_API_KEY=your_deepseek_api_key
OPENAI_API_KEY=your_openai_api_key  # 如果使用OpenAI作為翻譯服務
TRANSLATOR_SERVICE=openai  # 或 deepl
```

您也可以使用提供的`.env.example`作為模板。

## 使用方法

### 基本使用

```bash
python deep_book_analyzer.py
# 然後按照提示輸入PDF檔案路徑
```

### 直接指定檔案路徑

```bash
python deep_book_analyzer.py '/path/to/your/book.pdf'
```

### 使用多階段分析（推薦）

```bash
python pdf-book-main.py '/path/to/your/book.pdf'
```

### 分析報告輸出

所有生成的報告將保存在桌面的「深度書籍分析報告」資料夾中：

```
~/Desktop/深度書籍分析報告/書名_深度分析報告.md
```

## 不同版本的分析工具

本專案包含三個主要腳本，提供不同程度的分析深度：

1. `deep_book_analyzer.py` - 基本版本，單次API呼叫
2. `multi_section_analyzer.py` - 中級版本，三次API呼叫
3. `pdf-book-main.py` - 高級版本（推薦），七次API呼叫，提供最詳盡分析

## 環境要求

- Python 3.8+
- 有效的Deepseek API金鑰
- 用於翻譯功能的OpenAI或DeepL API金鑰（可選）

## 技術特點

- 使用分割技術處理大型PDF文件
- 採用多階段API呼叫生成全面報告
- 智能提示詞設計，確保高品質輸出
- 優化的Token使用，提高API效率
- 快速的簡繁中文轉換
