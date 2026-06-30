"""
LLM 标注引擎
负责调用 OpenAI API（或本地 Ollama）对文件内容进行智能标注，
返回：内容摘要、建议归档路径、重要性评分、清理优先级。
"""
import asyncio
import json
import logging
import os
import config
from openai import AsyncOpenAI, APIError


# ===== 可用归档路径白名单 =====
FOLDER_WHITELIST = [
    "Documents/Work",
    "Documents/Study",
    "Documents/Personal",
    "Downloads/Pending",
    "Desktop/Active",
    "Projects/Code",
    "Projects/Design",
    "Archive/2024",
    "Archive/2025",
    "Archive/2026",
]


def _get_client() -> AsyncOpenAI:
    """根据配置返回 OpenAI 客户端（支持本地 Ollama）"""
    if config.USE_LOCAL_LLM:
        return AsyncOpenAI(
            base_url=config.OLLAMA_BASE_URL,
            api_key="ollama",  # 本地 Ollama 不需要真实 key
        )
    else:
        return AsyncOpenAI(
            api_key=config.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY"),
            base_url=config.OPENAI_BASE_URL or None,
        )


PROMPT_SYSTEM = """你是一个本地文件智能标注助手。
用户会给你一段文件信息，你需要返回严格的 JSON 格式，不要包含任何额外文字或 markdown 代码块。

返回 JSON 格式（不要加 ```json ``` 包裹）：
{
  "remark": "一句话说明文件内容（20字以内）",
  "suggested_path": "建议归档的相对路径（必须是白名单之一，否则填 null）",
  "importance_scale": 1到10的整数（10=非常重要，1=可以删除）,
  "cleanup_score": 0到10的整数（10=应立即清理，0=必须保留）
}

可用白名单路径：
""" + "\n".join(f"- {p}" for p in FOLDER_WHITELIST)


async def annotate_file(
    file_name: str,
    full_path: str,
    size_bytes: int,
    file_type: str,
    extracted_text: str,
    content_hash: str,
) -> dict | None:
    """调用 LLM 标注文件，带缓存检查和重试"""

    # 先查缓存（由调用方负责，此处不再重复）

    # 构造用户消息
    size_kb = size_bytes / 1024
    user_msg = (
        f"文件名：{file_name}\n"
        f"路径：{full_path}\n"
        f"类型：{file_type}\n"
        f"大小：{size_kb:.1f} KB\n"
        f"内容摘要：\n"
        f"{extracted_text[:2000] if extracted_text else '（无法提取文本内容）'}"
    )

    client = _get_client()
    model = config.OLLAMA_MODEL if config.USE_LOCAL_LLM else config.OPENAI_MODEL

    for attempt in range(config.LLM_MAX_RETRY):
        try:
            resp = await client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": PROMPT_SYSTEM},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.2,
                timeout=30,
            )
            raw = resp.choices[0].message.content
            if not raw:
                continue
            result = json.loads(raw)
            result["_raw"] = raw
            result["content_hash"] = content_hash

            # 路径白名单校验 + 模糊匹配
            sp = result.get("suggested_path")
            if sp:
                result["suggested_path"] = _validate_path(sp)
            else:
                result["suggested_path"] = None

            # 确保数值字段合法
            result["importance_scale"] = _clamp(result.get("importance_scale"), 1, 10)
            result["cleanup_score"]   = _clamp(result.get("cleanup_score"), 0, 10)

            return result

        except (json.JSONDecodeError, KeyError):
            print(f"[LLM] JSON 解析失败（第{attempt+1}次），重试...")
            await asyncio.sleep(1)
        except (APIError, Exception) as e:
            print(f"[LLM] API 错误：{e}")
            if attempt == config.LLM_MAX_RETRY - 1:
                return None
            await asyncio.sleep(2)

    return None


def _validate_path(candidate: str) -> str | None:
    """路径白名单校验：精确匹配 → 模糊匹配 → None"""
    candidate = candidate.strip().strip("/")
    # 精确匹配
    if candidate in FOLDER_WHITELIST:
        return candidate
    # 模糊匹配：找包含 candidate 关键片段最多的白名单路径
    cand_parts = set(candidate.lower().replace("/", " ").split())
    best_score = 0
    best_path = None
    for wp in FOLDER_WHITELIST:
        wp_parts = set(wp.lower().replace("/", " ").split())
        score = len(cand_parts & wp_parts)
        if score > best_score:
            best_score = score
            best_path = wp
    return best_path if best_score > 0 else None


def _clamp(val, lo, hi):
    try:
        v = int(val)
        return max(lo, min(hi, v))
    except Exception:
        return lo
