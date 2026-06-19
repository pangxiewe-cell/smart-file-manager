"""
配置模板 — 复制此文件为 config.py 并填入实际值
"""

# ===== OpenAI / LLM 配置 =====
OPENAI_API_KEY = ""         # 填入你的 OpenAI API Key，使用本地 LLM 时可留空
OPENAI_BASE_URL = ""        # 留空使用官方接口，或填自定义端点（如 Ollama）
OPENAI_MODEL     = "gpt-4o-mini"   # 模型名称
USE_LOCAL_LLM    = False   # True = 使用本地 Ollama，False = 使用 OpenAI API

# ===== Ollama 本地模型配置（USE_LOCAL_LLM=True 时生效）=====
OLLAMA_BASE_URL  = "http://localhost:11434/v1"
OLLAMA_MODEL      = "llama3.1:8b"

# ===== 文件监控配置 =====
# 监控目录（~ 代表用户主目录）
WATCH_DIRS = [
    "~/Desktop",
    "~/Documents",
    "~/Downloads",
]

# 支持的文件扩展名
SUPPORTED_EXTS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json",
    ".yaml", ".yml", ".csv",
    ".docx", ".pdf", ".xlsx", ".pptx",
}

# ===== 数据库配置 =====
DB_DIR = "~/.smart_fm"   # 数据库存放目录

# ===== LLM 标注配置 =====
LLM_MAX_RETRY     = 3      # 标注失败最大重试次数
LLM_CACHE_SECONDS = 3600   # 相同内容缓存时间（秒）
LLM_MAX_TEXT_CHARS = 3000  # 传给 LLM 的最大文本字符数

# ===== 文件稳定等待时间（秒）=====
FILE_STABLE_WAIT = 2.0

# ===== 对话界面配置 =====
GRADIO_PORT   = 7860
GRADIO_SHARE  = False   # True = 生成公网分享链接
