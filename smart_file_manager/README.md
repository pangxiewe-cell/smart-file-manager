# 智能文件管理系统

基于 LLM 的本地文件智能标注、搜索与整理工具。自动监控文件变化，用 AI 生成文件备注与整理建议，并通过对话界面管理文件。

## 🌟 功能特性

- 📁 **文件监控**：自动监控 Desktop / Documents / Downloads 目录，文件写入后自动分析
- 🤖 **LLM 智能标注**：自动生成文件内容摘要、重要性评分、清理建议
- 💬 **对话式文件管理**：自然语言搜索、打开、移动、删除文件
- 🧹 **空间清理建议**：自动发现大文件并给出清理建议
- 🔒 **安全执行**：所有写操作需二次确认，支持撤销

## 🚀 安装指南

### 方式一：从 GitHub 克隆（推荐）

```bash
# 1. 克隆仓库到本地
git clone git@github.com:pangxiewe-cell/smart-file-manager.git
# 或使用 HTTPS 方式
# git clone https://github.com/pangxiewe-cell/smart-file-manager.git

# 2. 进入项目目录
cd smart-file-manager/smart_file_manager
```

### 方式二：下载 ZIP 包

1. 访问 [项目主页](https://github.com/pangxiewe-cell/smart-file-manager)
2. 点击绿色 **Code** 按钮 → **Download ZIP**
3. 解压后进入 `smart_file_manager` 目录

---

## 📦 依赖安装

### 1. 创建虚拟环境（推荐）

```bash
# 进入项目目录
cd smart-file-manager/smart_file_manager

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```

### 2. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

**依赖说明：**

| 依赖包 | 用途 | 必需 |
|--------|------|------|
| `watchdog` | 文件系统监控 | ✅ |
| `openai` | LLM API 调用 | ✅ |
| `gradio` | Web 对话界面 | ✅ |
| `python-docx` | Word 文档提取 | ✅ |
| `pypdfium2` | PDF 内容提取 | ✅ |
| `xxhash` | 文件内容快速哈希 | ✅ |
| `send2trash` | 安全删除（回收站） | ✅ |
| `pytesseract` | OCR 图片文字识别 | ⚠️ 可选 |
| `whisper` | 音频转写 | ⚠️ 可选 |

### 3. 可选：安装 OCR 支持（图片文字识别）

```bash
# macOS
brew install tesseract tesseract-lang

# Windows（下载安装包）
# 访问 https://github.com/UB-Mannheim/tesseract/wiki
# 下载并安装，然后将安装路径添加到系统 PATH

# Linux
sudo apt install tesseract-ocr tesseract-ocr-chi-sim  # 中文支持
```

---

## ⚙️ 配置指南

### 1. 创建配置文件

```bash
# 复制配置模板
cp config.example.py config.py
```

### 2. 编辑 `config.py`

```python
# config.py

# === LLM 配置 ===
# 选项 A：使用 OpenAI API（推荐，效果最好）
OPENAI_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxx"  # 填入你的 OpenAI API Key
OPENAI_BASE_URL = ""                         # 留空使用官方接口，或填写代理地址
OPENAI_MODEL     = "gpt-4o-mini"            # 可选：gpt-4o / gpt-4-turbo
USE_LOCAL_LLM    = False                      # False = 使用 OpenAI API

# 选项 B：使用本地 Ollama（免费，无需 API Key）
# 1. 先安装 Ollama：https://ollama.com
# 2. 运行：ollama pull llama3.1:8b
# 3. 修改以下配置：
# OPENAI_API_KEY = "ollama"
# OPENAI_BASE_URL = "http://localhost:11434/v1"
# OPENAI_MODEL     = "llama3.1:8b"
# USE_LOCAL_LLM    = True

# === 文件监控配置 ===
# 监控目录（按需要修改，支持 `~` 指代用户主目录）
WATCH_DIRS = [
    "~/Desktop",
    "~/Documents",
    "~/Downloads",
]

# === 数据库配置 ===
# 数据库存储路径（默认在用户主目录下）
DB_PATH = "~/.smart_fm/index.db"

# === 高级配置 ===
# 文件分析延迟（秒），避免文件未完全写入就分析
ANALYSIS_DELAY = 2.0

# 最大同时分析任务数
MAX_CONCURRENT_TASKS = 3

# 大文件阈值（字节），超过此大小的文件只分析前 N 字节
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB

# 清理建议的大文件阈值（字节）
CLEANUP_SIZE_THRESHOLD = 100 * 1024 * 1024  # 100MB

# 清理建议的访问时间阈值（天）
CLEANUP_ACCESS_DAYS = 30
```

### 3. 获取 OpenAI API Key

1. 访问 [platform.openai.com](https://platform.openai.com)
2. 注册/登录账号
3. 进入 **API Keys** 页面
4. 点击 **Create new secret key**
5. 复制生成的 Key（以 `sk-` 开头）并填入 `config.py`

> **💡 提示**：如果没有 API Key，可以使用本地 Ollama（免费），详见上方"选项 B"。

---

## 🏃 启动系统

### 方式一：正常启动

```bash
# 确保已激活虚拟环境
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

# 启动系统
python main.py
```

启动成功后，终端会显示：

```
🚀 智能文件管理系统启动中...
✅ 数据库初始化完成
✅ 文件监控已启动（监控 3 个目录）
🌐 对话界面已启动：http://localhost:7860
```

打开浏览器访问 **http://localhost:7860** 即可使用。

### 方式二：调试模式（显示详细日志）

```bash
# Windows
set DEBUG=true && python main.py

# macOS / Linux
DEBUG=true python main.py
```

---

## 💬 使用指南

### 基础对话示例

在 Web 界面中输入以下命令：

| 用户指令 | 功能说明 |
|----------|----------|
| `帮我找一下上周的季度报表` | 语义搜索文件 |
| `打开我昨天写的那个 Python 脚本` | 打开最近编辑的 Python 文件 |
| `把 main.py 移动到 Projects 文件夹` | 移动文件（需确认） |
| `删除 temp.txt` | 删除文件（移入回收站，需确认） |
| `这些大文件哪些可以清理？` | 生成清理建议 |
| `查看最近分析的文件` | 列出已索引的文件 |
| `重新分析 documents 文件夹` | 手动触发文件分析 |

### 文件监控演示

1. 系统启动后，自动监控 `WATCH_DIRS` 中的目录
2. 将新文件放入监控目录（如 `~/Desktop`）
3. 等待 2-5 秒，系统自动分析文件内容
4. 在对话界面中询问文件信息，LLM 会基于分析结果回答

### 空间清理演示

```
用户：帮我找找哪些文件可以清理

系统：
我找到了以下可以清理的大文件（共 5 个，可释放 2.3 GB）：

1. [紧急清理] old_backup.zip (1.2 GB)
   - 位置：~/Downloads/old_backup.zip
   - 原因：压缩包，最后访问时间超过 60 天
   - 操作：[移至回收站]

2. [可压缩] vacation_video_raw.mp4 (800 MB)
   - 位置：~/Desktop/vacation_video_raw.mp4
   - 原因：未压缩的视频文件，建议使用 HandBrake 压缩
   - 操作：[查看详情]

...
```

---

## 📂 项目结构

```
smart_file_manager/
├── core/                      # 核心功能模块
│   ├── __init__.py
│   ├── db.py                  # SQLite 数据库操作（建表、CRUD）
│   ├── watcher.py             # 文件系统监控（watchdog + 防抖）
│   ├── extractor.py           # 文件内容提取（文本/PDF/DOCX/OCR）
│   ├── llm_engine.py          # LLM 标注引擎（Prompt 模板 + 缓存）
│   ├── executor.py            # 文件操作执行器（安全沙箱 + 二次确认）
│   └── cleaner.py             # 空间清理建议引擎
├── chat/                      # 对话界面模块
│   ├── __init__.py
│   ├── tools.py               # Function Calling 工具定义
│   └── interface.py           # Gradio 对话界面
├── config.py                  # 配置文件（需自行创建，已加入 .gitignore）
├── config.example.py          # 配置模板（可参考）
├── main.py                    # 入口文件
├── requirements.txt           # Python 依赖列表
└── README.md                 # 本文件
```

---

## ❓ 常见问题

### Q1：系统支持哪些操作系统？

- ✅ **Windows** 10/11（推荐）
- ✅ **macOS** 12.0+
- ✅ **Linux**（Ubuntu 20.04+ 测试通过）

### Q2：没有 OpenAI API Key 可以用吗？

可以！使用本地 Ollama 完全免费：

```bash
# 1. 安装 Ollama
# 访问 https://ollama.com 下载安装

# 2. 下载模型
ollama pull llama3.1:8b

# 3. 修改 config.py
OPENAI_API_KEY = "ollama"
OPENAI_BASE_URL = "http://localhost:11434/v1"
OPENAI_MODEL     = "llama3.1:8b"
USE_LOCAL_LLM    = True
```

### Q3：文件监控会消耗很多系统资源吗？

不会。系统采用**异步防抖机制**，确保：
- 同一文件 2 秒内多次修改只分析一次
- 最大同时分析任务数限制为 3 个
- LLM 分析在后台线程执行，不阻塞主线程

### Q4：我的文件隐私安全吗？

✅ **完全安全**：
- 所有数据存储在本地 SQLite 数据库（`~/.smart_fm/index.db`）
- 文件内容仅发送至你配置的 LLM API（OpenAI 或本地 Ollama）
- 不会上传任何文件到第三方服务器
- `config.py`（含 API Key）已加入 `.gitignore`，不会上传到 GitHub

### Q5：如何停止文件监控？

在终端按 **Ctrl + C** 即可停止系统，监控会自动停止。

### Q6：数据库文件太大怎么办？

```bash
# 查看数据库大小
ls -lh ~/.smart_fm/index.db

# 清空数据库（慎用，会丢失所有分析结果）
rm ~/.smart_fm/index.db
# 重启系统会自动重建数据库
```

### Q7：如何修改监控目录？

编辑 `config.py`，修改 `WATCH_DIRS`：

```python
WATCH_DIRS = [
    "~/Desktop",
    "~/Documents",
    "~/Downloads",
    "~/Projects",    # 新增目录
    # "~/Downloads",  # 注释掉不需要监控的目录
]
```

修改后重启系统生效。

---

## 🛠️ 开发指南

### 运行测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行所有测试
pytest tests/

# 运行单个测试文件
pytest tests/test_db.py -v
```

### 代码格式化

```bash
# 安装格式化工具
pip install black isort

# 格式化代码
black smart_file_manager/
isort smart_file_manager/
```

### 打包分发

```bash
# 安装打包工具
pip install pyinstaller

# 打包为可执行文件（Windows）
pyinstaller --onefile --name smart-fm main.py

# 打包后的文件在 dist/ 目录下
```

---

## ⚠️ 注意事项

1. **数据库隐私**：数据库文件存储在 `~/.smart_fm/index.db`，包含文件路径索引和分析结果，请注意隐私保护。

2. **监控目录**：默认只监控 Desktop / Documents / Downloads，可在 `config.py` 中修改。不建议监控系统目录（如 `C:\Windows`）。

3. **删除操作**：删除操作会移入回收站（非永久删除），可在系统的回收站中恢复。

4. **API 成本**：使用 OpenAI API 会产生费用，建议：
   - 使用 `gpt-4o-mini` 模型（成本低）
   - 开启 SimHash 缓存（相同内容不重复分析）
   - 限制监控目录数量

5. **大文件分析**：超过 10MB 的文件只分析前 N 字节，可能影响分析准确性。

6. **OCR 识别**：图片 OCR 识别准确率取决于图片质量和 Tesseract 语言包，建议仅对清晰图片使用。

---

## 📝 更新日志

### v1.0.0 (2026-06-17)

- ✨ 初始版本发布
- ✨ 支持文件监控与自动分析
- ✨ 支持 LLM 智能标注（OpenAI API + Ollama 本地模型）
- ✨ 支持对话式文件管理（Gradio Web 界面）
- ✨ 支持空间清理建议
- ✨ 支持安全执行器（二次确认 + 撤销）

---

## 📄 License

MIT License - 详见 [LICENSE](LICENSE) 文件

---

## 🙏 致谢

- [OpenAI](https://openai.com) - LLM API 支持
- [Ollama](https://ollama.com) - 本地 LLM 运行环境
- [Gradio](https://gradio.app) - Web 界面框架
- [Watchdog](https://github.com/gorakhargosh/watchdog) - 文件系统监控库

---

## 📧 联系作者

- GitHub Issues：[提交问题](https://github.com/pangxiewe-cell/smart-file-manager/issues)
- Email：pangxiewe-cell@example.com

---

**🎉 开始使用吧！如果有任何问题，欢迎提交 Issue 或 Pull Request。**
