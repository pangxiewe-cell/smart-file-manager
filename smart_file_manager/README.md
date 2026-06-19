# 智能文件管理系统

基于 LLM 的本地文件智能标注、搜索与整理工具。自动监控文件变化，
用 AI 生成文件备注与整理建议，并通过对话界面管理文件。

## 功能特性

- 📁 **文件监控**：自动监控 Desktop / Documents / Downloads 目录，文件写入后自动分析
- 🤖 **LLM 智能标注**：自动生成文件内容摘要、重要性评分、清理建议
- 💬 **对话式文件管理**：自然语言搜索、打开、移动、删除文件
- 🧹 **空间清理建议**：自动发现大文件并给出清理建议
- 🔒 **安全执行**：所有写操作需二次确认，支持撤销

## 快速开始

### 1. 安装依赖

```bash
cd smart_file_manager
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# 复制配置模板
cp config.example.py config.py

# 编辑 config.py，填入你的 OpenAI API Key
# 或使用本地 Ollama（无需 API Key）
```

`config.py` 示例：

```python
OPENAI_API_KEY = "sk- your key"
OPENAI_BASE_URL = ""          # 留空使用官方接口，或填自定义端点
OPENAI_MODEL     = "gpt-4o-mini"   # 或 "llama3.1:8b"（本地 Ollama）
USE_LOCAL_LLM    = False       # True = 使用 Ollama 本地模型

# 监控目录（按需要修改）
WATCH_DIRS = [
    "~/Desktop",
    "~/Documents",
    "~/Downloads",
]
```

### 3. 可选：安装 OCR 支持

```bash
# macOS
brew install tesseract tesseract-lang

# Windows（下载安装包）
# https://github.com/UB-Mannheim/tesseract/wiki

# Linux
sudo apt install tesseract-ocr tesseract-ocr-chi-sim
```

### 4. 启动系统

```bash
python main.py
```

启动后访问终端输出的地址（默认 http://localhost:7860）打开对话界面。

## 使用示例

在对话界面中输入：

```
帮我找一下上周的季度报表
打开我昨天写的那个 Python 脚本
这些大文件哪些可以清理？
把 main.py 移动到 Projects 文件夹
```

## 项目结构

```
smart_file_manager/
├── core/
│   ├── db.py           # SQLite 数据库操作
│   ├── watcher.py      # 文件系统监控（watchdog）
│   ├── extractor.py    # 文件内容提取（文本 / PDF / OCR）
│   ├── llm_engine.py   # LLM 标注引擎
│   ├── executor.py     # 文件操作执行器（安全沙箱）
│   └── cleaner.py      # 空间清理建议引擎
├── chat/
│   ├── tools.py        # Function Calling 工具定义
│   └── interface.py    # Gradio 对话界面
├── config.py            # 配置文件（需自行创建）
├── config.example.py    # 配置模板
├── main.py              # 入口文件
└── requirements.txt
```

## 注意事项

- 数据库文件存储在 `~/.smart_fm/index.db`，含文件路径索引，请注意隐私
- 默认只监控 Desktop / Documents / Downloads，可在 `config.py` 中修改
- 删除操作移入回收站（非永久删除），可在系统中恢复

## License

MIT
