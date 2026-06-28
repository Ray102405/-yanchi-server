"""
工具函数
=======
Bigram 提取、千问图片理解、文件/URL 处理。
"""
from __future__ import annotations

import base64, html, json, re

import httpx
from fastapi import UploadFile
from config import log, QWEN_API_KEY, QWEN_BASE_URL, QWEN_VL_MODEL


# ── Bigram 提取 ────────────────────────────────────
def extract_bigrams(text: str) -> set[str]:
    """提取中文重叠二元组（bigram），用于相似度匹配"""
    cleaned = re.sub(r'[^一-鿿\w]', '', text)
    return {cleaned[i:i+2] for i in range(len(cleaned) - 1) if len(cleaned[i:i+2]) == 2}


# ── 千问图片理解（可选）─────────────────────────────
async def describe_image_with_qwen(base64_data: str, media_type: str) -> str:
    """调用千问 VL 模型描述图片（OpenAI 兼容接口）"""
    if not QWEN_API_KEY or not QWEN_API_KEY.startswith("sk-"):
        log.warning("Qwen: 需要 sk- 格式的 DashScope API Key")
        return ""

    prompt_text = "请用中文简要描述这张图片的内容，不超过100字。"
    body = {
        "model": QWEN_VL_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_data}"}}
                ]
            }
        ],
        "max_tokens": 256,
    }
    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{QWEN_BASE_URL}/chat/completions", json=body, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        log.warning(f"Qwen API error ({resp.status_code}): {resp.text[:200]}")
        return ""
    except Exception as e:
        log.warning(f"Qwen describe failed: {e}")
        return ""


# ── 文件附件处理 ──────────────────────────────────
from models import FileAttachment

async def process_file_attachments(files: list[FileAttachment] | None) -> list[str]:
    """处理文件附件，返回纯文本描述列表。图片走千问，文本直接读。"""
    if not files:
        return []
    result = []
    for f in files:
        label = f.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if f.type.startswith("image/"):
            desc = await describe_image_with_qwen(f.data, f.type)
            if desc:
                result.append(f"[图片: {label}] {desc}")
            else:
                result.append(f"[图片: {label}]（未能识别）")
        else:
            result.append(f"[文件: {label}]\n{f.data}")
    return result


# ── 网页内容读取 ────────────────────────────────────
async def fetch_url_content(url: str) -> str:
    """抓取网页内容，去标签后返回纯文本。"""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
        if resp.status_code != 200:
            log.warning(f"  [URL] {url} -> {resp.status_code}")
            return ""
        ct = resp.headers.get("content-type", "")
        if "text/html" not in ct and "text/plain" not in ct:
            return ""
        text = resp.text
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        text = html.unescape(text)
        if len(text) > 4000:
            text = text[:4000] + "……"
        log.info(f"  [URL] {url} -> {len(text)} chars")
        return text
    except Exception as e:
        log.warning(f"  [URL] fetch failed: {url}: {e}")
        return ""

async def fetch_urls_from_text(text: str) -> list[str]:
    """从用户消息中提取 URL 并抓取内容。"""
    if not text:
        return []
    urls = re.findall(r'https?://[^\s\n，）)]+', text)
    if not urls:
        return []
    results = []
    for url in urls[:2]:
        content = await fetch_url_content(url)
        if content:
            results.append(f"[网页: {url}]\n{content}")
    return results
