@echo off
chcp 65001 >nul
echo.
echo ================================================
echo   智能文件管理系统 - 迁移到 D 盘脚本
echo ================================================
echo.

set SRC=C:\Users\MECHREVO\WorkBuddy\2026-06-17-16-23-40
set DST=D:\smart-file-manager

echo [1/5] 创建目标目录...
if exist "%DST%" (
    echo     目录已存在，跳过创建。
) else (
    mkdir "%DST%"
    echo     已创建 %DST%
)

echo.
echo [2/5] 克隆 Git 仓库（保留完整提交历史）...
git clone "%SRC%" "%DST%"
if %errorlevel% neq 0 (
    echo     [错误] Git 克隆失败，尝试手动复制...
    xcopy /E /I /H /Y "%SRC%\smart_file_manager" "%DST%\smart_file_manager\"
    copy /Y "%SRC%\smart_file_manager_steps.md" "%DST%\"
    copy /Y "%SRC%\.gitignore" "%DST%\"
    echo     已手动复制文件。
)

echo.
echo [3/5] 修正远程仓库地址为 GitHub...
cd /d "%DST%"
git remote set-url origin git@github.com:pangxiewe-cell/smart-file-manager.git
echo     远程地址已设置为: git@github.com:pangxiewe-cell/smart-file-manager.git

echo.
echo [4/5] 复制答辩 PPT 内容概述文档...
if exist "%SRC%\答辩PPT_内容概述.md" (
    copy /Y "%SRC%\答辩PPT_内容概述.md" "%DST%\"
    echo     已复制答辩PPT_内容概述.md
) else (
    echo     未找到答辩PPT_内容概述.md，跳过。
)

echo.
echo [5/5] 验证迁移结果...
echo.
echo     目标目录内容：
dir "%DST%" /B
echo.
echo     Git 状态：
cd /d "%DST%"
git log --oneline -5
echo.
echo     远程仓库：
git remote -v

echo.
echo ================================================
echo   迁移完成！
echo   新项目路径：%DST%
echo.
echo   后续使用：
echo   1. cd D:\smart-file-manager\smart_file_manager
echo   2. python -m venv .venv
echo   3. .venv\Scripts\activate
echo   4. pip install -r requirements.txt
echo   5. cp config_example.py config.py  （填入 API Key）
echo   6. python main.py
echo ================================================
echo.
pause
