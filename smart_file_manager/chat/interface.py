"""
Gradio 对话界面
提供 Web 聊天界面，支持文件搜索、打开、整理建议。
LLM 通过 Function Calling 调用 tools.py 中定义的工具。
"""
import json
import gradio as gr
import config
from openai import OpenAI

from chat.tools import TOOLS, execute_tool


# ===== OpenAI 客户端（同步，Gradio 事件循环内使用）=====
def _client():
    if config.USE_LOCAL_LLM:
        return OpenAI(
            base_url=config.OLLAMA_BASE_URL,
            api_key="ollama",
        )
    else:
        return OpenAI(
            api_key=config.OPENAI_API_KEY or None,
            base_url=config.OPENAI_BASE_URL or None,
        )


SYSTEM_MSG = {
    "role": "system",
    "content": (
        "你是一个本地文件管理助手。帮助用户搜索、查看、打开、整理文件。\n"
        "回答要简洁自然，对于移动/删除操作必须先调用工具创建待确认任务，"
        "并明确告知用户'需要您确认后才会执行'。\n"
        "保留最近对话上下文以支持指代消解（如'就是那个''第二个'等）。"
    ),
}


# ===== 核心对话逻辑 ===========================================================

def chat(user_input: str, history: list) -> tuple[str, list]:
    """多轮对话 + Function Calling 循环"""
    client = _client()
    model = config.OLLAMA_MODEL if config.USE_LOCAL_LLM else config.OPENAI_MODEL

    # 构建消息列表（最近 10 轮）
    messages = [SYSTEM_MSG]
    for h in (history[-10:] if history else []):
        messages.append({"role": "user",      "content": h[0]})
        messages.append({"role": "assistant", "content": h[1]})
    messages.append({"role": "user", "content": user_input})

    # 多轮 Tool 调用循环
    while True:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                args   = json.loads(tc.function.arguments)
                result = execute_tool(tc.function.name, args)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      result,
                })
        else:
            reply = msg.content or "（未能生成回复）"
            new_history = (history or []).copy()
            new_history.append((user_input, reply))
            return reply, new_history


# ===== Gradio 界面 ===========================================================

def build_ui():
    with gr.Blocks(
        title="智能文件管理助手",
        theme=gr.themes.Soft(),
    ) as demo:
        gr.Markdown(
            "# 🗂️ 智能文件管理助手\n"
            "用自然语言管理你的文件：搜索、打开、整理、清理建议。\n"
            "_提示：移动/删除操作会在执行前要求确认。_"
        )
        chatbot  = gr.Chatbot(height=500, show_copy_button=True)
        inp      = gr.Textbox(
            placeholder="说点什么…（如：帮我找上周的报告、这些大文件哪些可以清理？）",
            show_label=False,
            container=False,
        )
        state    = gr.State([])

        # 发送消息
        inp.submit(chat, [inp, state], [chatbot, state])
        inp.submit(lambda: "", None, [inp])

        # 底部说明
        gr.Markdown(
            "---\n"
            "**支持的命令示例：**\n"
            "- `搜索文件名包含 报告 的文件`\n"
            "- `打开 ~/Documents/xxx.docx`\n"
            "- `把 main.py 移动到 Projects/Code 文件夹`\n"
            "- `帮我看看哪些文件可以清理`\n"
            "**注意：** 首次使用请复制 `config.example.py` 为 `config.py` 并填入 API Key。"
        )

    return demo


def launch():
    demo = build_ui()
    demo.launch(
        server_port=config.GRADIO_PORT,
        share=config.GRADIO_SHARE,
        inbrowser=True,
    )
