#!/usr/bin/env python3
"""
智能文件管理系统 — 入口文件
启动方式：python main.py
"""
import asyncio
import sys
import os
import signal

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
from core.db import init_db, cleanup_expired_tasks
from core.watcher import start_watcher
from chat.interface import launch


async def _background_cleanup():
    """定期清理过期 pending 任务的后台协程"""
    while True:
        await asyncio.sleep(1800)  # 每 30 分钟
        try:
            from core.db import get_conn
            with get_conn() as conn:
                cleanup_expired_tasks(conn)
        except Exception:
            pass


def _check_config():
    """启动时检查配置是否合法"""
    if not config.USE_LOCAL_LLM:
        key = config.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
        if not key:
            print("=" * 60)
            print("  [警告] 未配置 OPENAI_API_KEY！")
            print("  请复制 config.example.py → config.py 并填入 API Key")
            print("  或设置 USE_LOCAL_LLM = True 使用本地 Ollama")
            print("=" * 60)
            print()
            print("是否继续启动（LLM 标注功能将不可用）？[y/N] ", end="")
            try:
                ans = input().strip().lower()
                if ans != "y":
                    sys.exit(1)
            except (EOFError, KeyboardInterrupt):
                sys.exit(1)


async def main():
    _check_config()

    # 初始化数据库
    print("[Main] 初始化数据库…")
    init_db()

    # 启动文件监控
    print("[Main] 启动文件监控…")
    loop = asyncio.get_event_loop()
    observer = start_watcher(loop)

    # 启动后台清理任务
    cleanup_task = asyncio.create_task(_background_cleanup())

    print(f"[Main] 系统启动完成！")
    print(f"[Main] 对话界面将在浏览器中打开：http://localhost:{config.GRADIO_PORT}")
    print(f"[Main] 按 Ctrl+C 停止系统")
    print()

    # 启动 Gradio（阻塞，直到用户关闭）
    try:
        launch()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[Main] 正在停止…")
        observer.stop()
        observer.join(timeout=5)
        cleanup_task.cancel()
        print("[Main] 已停止。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出。")
