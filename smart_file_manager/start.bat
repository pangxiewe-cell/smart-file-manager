@echo off
chcp 65001 >nul
echo.
echo ================================================
echo   智能文件管理系统 - 快速启动
echo ================================================
echo.

cd /d "%~dp0smart_file_manager"

echo [检查] Python 虚拟环境...
if not exist ".venv\Scripts\activate.bat" (
    echo     首次运行，创建虚拟环境...
    python -m venv .venv
    echo     安装依赖...
    .venv\Scripts\pip install -r requirements.txt
    echo.
    echo     [!] 请先配置 config.py 文件：
    echo         copy config_example.py config.py
    echo         然后编辑 config.py，填入你的 OpenAI API Key
    echo.
    pause
) else (
    echo     虚拟环境已存在，跳过安装。
)

if not exist "config.py" (
    echo.
    echo     [警告] config.py 不存在！
    echo     正在从模板复制...
    copy config_example.py config.py
    echo.
    echo     请用文本编辑器打开 config.py，填入你的 API Key：
    notepad config.py
    echo.
    pause
)

echo.
echo [启动] 系统启动中...
echo     访问地址：http://localhost:7860
echo     按 Ctrl+C 停止服务
echo.
.venv\Scripts\python main.py

pause
