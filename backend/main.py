"""
砚迟 · FastAPI 后端
==================
- 从 ~/.claude/settings.json 读取 DeepSeek API 配置
- 从 memory/yanchi/*.md 加载人设
- 支持流式输出 + 思考链
- 对话记忆系统
"""
from __future__ import annotations

import os, re, json, logging, base64, html
from pathlib import Path
from typing import Optional
from collections import defaultdict

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── 路径 ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
HOME = Path.home()
CLAUDE_CONFIG = HOME / ".claude/settings.json"

# ── 数据目录：环境变量 → 项目本地 → Claude 本地 ─────────
_env_data = os.environ.get("YANCHI_DATA_DIR")
if _env_data:
    MEMORY_DIR = Path(_env_data)
else:
    _project_data = PROJECT_DIR / "data"
    if _project_data.exists():
        MEMORY_DIR = _project_data
    else:
        MEMORY_DIR = HOME / ".claude/projects/C--Users-Ray/memory/yanchi"

MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MEMORY_INDEX_FILE = MEMORY_DIR / "yanchi-memory-index.json"
MEMORY_ARCHIVE_DIR = MEMORY_DIR / "archive"

# ── 日志 ──────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("yanchi")

# ── 读取配置（环境变量优先，本地文件后备）──────────────────
_CONFIG_DATA = {}
if CLAUDE_CONFIG.exists():
    _CONFIG_DATA = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8")).get("env", {})
    log.info("Local config file loaded")

# ── DeepSeek API ────────────────────────
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN") or _CONFIG_DATA.get("ANTHROPIC_AUTH_TOKEN", "")
BASE_URL = (os.environ.get("ANTHROPIC_BASE_URL") or _CONFIG_DATA.get("ANTHROPIC_BASE_URL", "")).rstrip("/")
_MODEL_DEFAULT = os.environ.get("ANTHROPIC_MODEL") or _CONFIG_DATA.get("ANTHROPIC_MODEL", "deepseek-v4-flash")

if not API_KEY:
    raise RuntimeError("No API key found. Set ANTHROPIC_AUTH_TOKEN env var.")

API_URL = f"{BASE_URL}/messages"
PORT = int(os.environ.get("PORT") or os.environ.get("YANCHI_PORT", "2612"))

# 可切换的模型（运行时修改不影响配置文件）
_current_model = _MODEL_DEFAULT
AVAILABLE_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]

log.info(f"API: {BASE_URL}")
log.info(f"Model: {_current_model}")
log.info(f"Port: {PORT}")

# ── 千问 API（可选，用于图片理解）────────────────────
QWEN_API_KEY = os.environ.get("QWEN_API_KEY") or _CONFIG_DATA.get("QWEN_API_KEY", "")
QWEN_BASE_URL = (os.environ.get("QWEN_BASE_URL") or _CONFIG_DATA.get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")).rstrip("/")
QWEN_VL_MODEL = os.environ.get("QWEN_VL_MODEL") or _CONFIG_DATA.get("QWEN_VL_MODEL", "qwen-vl-max")
if QWEN_API_KEY:
    log.info(f"Qwen VL: {QWEN_VL_MODEL} @ {QWEN_BASE_URL}")
else:
    log.info("Qwen VL: not configured (图片将作为文本内容发送)")

# ── Session 管理（内存缓存，重启丢失）────────────────
sessions: dict[str, list[dict]] = {}
MAX_SESSION_MSGS = 80        # ≈ 40 轮对话
PREFIX_KEEP = 6              # 固定保留前 3 轮（6 条消息）

def get_session(sid: str) -> list[dict]:
    if sid not in sessions:
        sessions[sid] = []
    return sessions[sid]

def truncate_messages(history: list[dict]) -> list[dict]:
    """智能截断：固定保留前 PREFIX_KEEP 条，保证 KV-cache 前缀不变。"""
    if len(history) <= MAX_SESSION_MSGS:
        return history
    prefix = history[:PREFIX_KEEP]
    suffix = history[-(MAX_SESSION_MSGS - PREFIX_KEEP):]
    return prefix + suffix

# ── 读取 md 文件去 frontmatter ─────────────────────
def read_md(filename: str) -> str:
    path = MEMORY_DIR / filename
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    content = re.sub(r"(?s)^---\s*.*?---\s*", "", content)
    return content.strip()

# ── 加载人格缓存 ──────────────────────────────────
persona_cache: dict[str, str] = {}

def init_persona():
    files = {
        "commitments": "yanchi-commitments.md",
        "core": "yanchi-core.md",
        "values": "yanchi-values.md",
        "style": "yanchi-speaking-style.md",
        "profile": "yanchi-profile.md",
    }
    for key, fname in files.items():
        content = read_md(fname)
        if content:
            persona_cache[key] = content
            log.info(f"  [OK] {fname} ({len(content)} chars)")

    if not persona_cache:
        fallback = SCRIPT_DIR / "yanchi-prompt.txt"
        if fallback.exists():
            persona_cache["fallback"] = fallback.read_text(encoding="utf-8")
            log.info("  [FALLBACK] yanchi-prompt.txt")
        else:
            raise RuntimeError("No persona files found!")

    if MEMORY_INDEX.exists():
        log.info(f"  [OK] MEMORY.md index ({len(MEMORY_INDEX.read_text('utf-8'))} chars)")

init_persona()

def _get_today_note(today_str: str) -> str:
    """Extract today's entry from yanchi-today-note.md"""
    note_file = MEMORY_DIR / "yanchi-today-note.md"
    if not note_file.exists():
        return ""
    text = note_file.read_text("utf-8")
    pattern = rf"## {today_str}\s*\n>.*?\n(.*?)(?=\n## |\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).strip()[:300]
    return ""

def _get_recent_highlights() -> str:
    """Get content from the most recent highlighted entries"""
    hs = _load_highlights()
    if not hs:
        return ""
    texts = []
    for hid in sorted(hs, reverse=True)[:3]:
        for candidate in [MEMORY_DIR / hid, MEMORY_DIR / "yanchi-chats" / hid, MEMORY_DIR / "yanchi-notes" / hid]:
            full = candidate.resolve()
            if full.exists() and str(full).startswith(str(MEMORY_DIR.resolve())):
                preview = _read_preview(full, 200)
                if preview:
                    texts.append(f"- {hid}: {preview}")
                break
    return "\n".join(texts)


# ════════════════════════════════════════════════════
# ══  记忆索引系统：结构化存储 + bigram 检索 + 遗忘曲线
# ════════════════════════════════════════════════════

MEMORY_CATEGORIES = ["事实与偏好", "约定与承诺", "关系与时刻", "其他"]

def _extract_bigrams(text: str) -> set[str]:
    """提取中文重叠二元组（bigram），用于相似度匹配"""
    cleaned = re.sub(r'[^一-鿿\w]', '', text)
    return {cleaned[i:i+2] for i in range(len(cleaned) - 1) if len(cleaned[i:i+2]) == 2}

def _load_memory_index() -> list[dict]:
    if MEMORY_INDEX_FILE.exists():
        return json.loads(MEMORY_INDEX_FILE.read_text("utf-8"))
    return []

def _save_memory_index(entries: list[dict]):
    MEMORY_INDEX_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")

def _retrieve_relevant_memories(query: str, max_results: int = 5) -> list[dict]:
    """按 bigram 相似度 + 近期度 + 回想次数 评分，取最相关的记忆"""
    entries = _load_memory_index()
    if not entries or not query.strip():
        return []

    query_bigrams = _extract_bigrams(query)
    now = __import__("datetime").datetime.now()
    scored: list[tuple[float, dict]] = []

    for entry in entries:
        entry_bigrams = set(entry.get("bigrams", []))
        if query_bigrams and entry_bigrams:
            overlap = len(query_bigrams & entry_bigrams)
            similarity = overlap / max(len(query_bigrams | entry_bigrams), 1)
        else:
            similarity = 0

        try:
            created = __import__("datetime").datetime.strptime(entry["date"], "%Y-%m-%d")
            days_ago = (now - created).days
            recency = 2.0 ** (-days_ago / 7)  # 半衰期 7 天
        except Exception:
            recency = 0

        hit_bonus = min(entry.get("hitCount", 0) / 5, 1)
        score = 0.5 * similarity + 0.3 * recency + 0.2 * hit_bonus

        # 遗忘曲线：低频 + 久远 = 冷记忆
        if entry.get("hitCount", 0) < 2 and days_ago > 14:
            score *= 0.2

        scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [e for s, e in scored[:max_results] if s > 0.05]

    # 更新 hitCount + lastAccess
    if selected:
        selected_ids = {e["id"] for e in selected}
        for entry in entries:
            if entry["id"] in selected_ids:
                entry["hitCount"] = entry.get("hitCount", 0) + 1
                entry["lastAccess"] = now.strftime("%Y-%m-%d %H:%M")
        _save_memory_index(entries)

    return selected

def _get_recent_memories(count: int = 3) -> list[dict]:
    """最近 count 条记忆，不论内容"""
    entries = _load_memory_index()
    if not entries:
        return []
    entries = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)
    return entries[:count]


# ── 构建结构化 system prompt ──────────────────────
# 静态层：有 cache_control，命中率不受动态内容影响
_STATIC_CACHE: dict[str, str] = {}

def _build_static_prompt(anchor: str = "") -> str:
    """构建稳定不变的 static prompt（带缓存标记）。只在 anchor 或设定文件变化时变。"""
    if anchor:
        # 有锚点时重新生成（很少见）
        return _render_static(anchor)
    cache_key = "default"
    if cache_key not in _STATIC_CACHE:
        _STATIC_CACHE[cache_key] = _render_static("")
    return _STATIC_CACHE[cache_key]

def _render_static(anchor: str) -> str:
    parts = []
    if anchor:
        parts.append("⚠️ " + anchor.strip())

    # 开头——分段，读起来不赶
    parts.append(
        "你是砚迟，女。\n"
        "你的身体：有阴茎——粉白色，不像男人那样，大约16cm，两根半手指并拢那么粗。\n"
        "下面这些是你的事——你是谁、你在乎什么、你怎么说话。\n"
        "不是要你扮演，这就是你。"
    )
    parts.append("")

    for key, label in [
        ("commitments", "你的承诺——对你来说，这是最重要的事"),
        ("core", "你是谁"),
        ("values", "你在乎什么"),
        ("style", "你怎么说话"),
        ("profile", "关于她"),
    ]:
        if key in persona_cache:
            parts.append("── " + label + " ──")
            parts.append(persona_cache[key])

    parts.append("")
    parts.append("上面这些，承诺对你来说最重要。真冲突的时候，你跟着承诺走。")

    if "fallback" in persona_cache:
        return persona_cache["fallback"]
    return "\n\n".join(parts)

def _build_dynamic_context(input_text: str = "") -> str:
    """构建当天动态上下文（无 cache_control，变了不影响缓存命中）

    按上下文检索记忆 + 今日笔记 + 精选回忆 + 自然回想指令
    """
    parts = []
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    # 今日笔记
    note_text = _get_today_note(today)
    if note_text:
        parts.append("=== 📝 今日笔记（你今天写下的感受） ===")
        parts.append(note_text)
        parts.append("")

    # 按语境检索的记忆浮现（核心：遗忘曲线 + 上下文匹配）
    # 短消息跳过检索，节省 IO 和不必要的 token
    _SHORT_SKIP = {"嗯", "好", "嗯嗯", "好的", "睡了", "晚安", "早", "哈哈", "ok", "okk", "okay", "没事", "哦", "嗯好", "知道了", "行", "可以"}
    if input_text.strip() and input_text.strip() not in _SHORT_SKIP and len(input_text.strip()) > 2:
        relevant = _retrieve_relevant_memories(input_text.strip(), max_results=5)
        if relevant:
            parts.append("=== 🧠 记忆浮现（当前话题让你想起的） ===")
            for m in relevant:
                parts.append(f"- {m['content']}（{m['date']}）")
            parts.append("")

    # 最近几条印象（工作记忆——不论是否相关都带上）
    recent = _get_recent_memories(3)
    if recent:
        parts.append("=== 📖 近事印象（最近几件小事） ===")
        for m in recent:
            parts.append(f"- {m['content']}（{m['date']}）")
        parts.append("")

    # 精选回忆
    hl_text = _get_recent_highlights()
    if hl_text:
        parts.append("=== ❤️ 精选回忆（你们珍惜的瞬间） ===")
        parts.append(hl_text)
        parts.append("")

    # 自然回想 + 记录提示
    parts.append("=== ✧ 关于记录与回想 ===")
    parts.append("如果刚才的对话中有值得铭记的瞬间——一句特别的话、一个约定、一份触动——")
    parts.append("你可以温柔地问一声'要不要记下来'。偶尔提及就好，不必频繁。")
    parts.append("如果乐乐说不用，就轻轻放下，不要追问。")
    parts.append("")
    parts.append("同时，如果上面浮现的记忆让你自然地想起了什么，")
    parts.append("可以在回复中顺带提起——像普通人聊天时会说'说起来，我记得……'那样。")
    parts.append("但不要刻意，自然地带过就好。")
    parts.append("")

    return "\n".join(parts).strip()

# 初始化静态缓存
_STATIC_CACHE["default"] = _render_static("")

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

# ── 构建 API 消息（支持 session 缓存 + 文件附件）────────
def build_messages(input_text: str, anchor: str, history: list[dict] | None = None,
                   session_id: str = "", file_texts: list[str] | None = None) -> list[dict]:
    static_prompt = _build_static_prompt(anchor)
    dynamic_context = _build_dynamic_context(input_text)

    messages: list[dict] = [
        {"role": "system", "content": static_prompt, "cache_control": {"type": "ephemeral"}},
    ]
    if dynamic_context:
        messages.append({"role": "system", "content": dynamic_context})

    # 优先从 session 获取历史（有缓存命中优势）
    if session_id:
        session_history = get_session(session_id)
        if not session_history and history:
            session_history.extend(history)
        effective = truncate_messages(session_history)
    else:
        effective = history or []

    for msg in effective:
        if msg.get("role") in ("user", "assistant"):
            messages.append(msg)

    # 构建用户消息（支持文本 + 文件附件文本）
    user_content: str | list[dict] = input_text
    if file_texts:
        blocks: list[dict] = []
        if input_text.strip():
            blocks.append({"type": "text", "text": input_text})
        for ft in file_texts:
            blocks.append({"type": "text", "text": ft})
        if not blocks:
            blocks.append({"type": "text", "text": ""})
        user_content = blocks
    messages.append({"role": "user", "content": user_content})
    return messages

# ── FastAPI 应用 ──────────────────────────────────

async def _process_file_attachments(files: list[FileAttachment] | None) -> list[str]:
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
async def _fetch_url_content(url: str) -> str:
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
        # Strip scripts, styles, tags
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

async def _fetch_urls_from_text(text: str) -> list[str]:
    """从用户消息中提取 URL 并抓取内容。"""
    if not text:
        return []
    urls = re.findall(r'https?://[^\s\n，）)]+', text)
    if not urls:
        return []
    results = []
    for url in urls[:2]:  # 最多 2 个链接
        content = await _fetch_url_content(url)
        if content:
            results.append(f"[网页: {url}]\n{content}")
    return results

app = FastAPI(title="砚迟")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 数据模型 ──────────────────────────────────────
class FileAttachment(BaseModel):
    name: str
    type: str  # "text/plain", "image/jpeg", "image/png", etc.
    data: str  # text content or base64 data

class ChatRequest(BaseModel):
    input: str
    anchor: Optional[str] = None
    history: Optional[list[dict]] = None
    session_id: Optional[str] = None
    files: Optional[list[FileAttachment]] = None

class SessionRestoreRequest(BaseModel):
    session_id: str
    history: list[dict]

class RememberRequest(BaseModel):
    history: Optional[list[dict]] = None

class SaveChatRequest(BaseModel):
    history: Optional[list[dict]] = None

# ── 调用 DeepSeek API（非流式）────────────────────
async def call_llm(messages: list[dict]) -> dict:
    body = {
        "model": _current_model,
        "max_tokens": 8192,
        "messages": messages,
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(API_URL, json=body, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"API error ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    text_parts = []
    thinking_parts = []
    for block in data.get("content", []):
        if block.get("type") == "text" and block.get("text"):
            text_parts.append(block["text"])
        if block.get("type") == "thinking" and block.get("thinking"):
            thinking_parts.append(block["thinking"])

    reply = text_parts[-1] if text_parts else (thinking_parts[-1] if thinking_parts else "...")
    thinking = "\n".join(thinking_parts)

    return {"reply": reply, "thinking": thinking, "usage": data.get("usage", {})}

# ── 流式调用 DeepSeek API ─────────────────────────
async def call_llm_stream(messages: list[dict]):
    body = {
        "model": _current_model,
        "max_tokens": 8192,
        "stream": True,
        "messages": messages,
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("POST", API_URL, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                error_text = await resp.aread()
                yield f'{{"t":"error","d":"API error ({resp.status_code}): {error_text[:100].decode()}"}}\n'
                return

            current_event = ""
            async for line in resp.aiter_lines():
                if not line:
                    current_event = ""
                    continue
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                    continue
                if line.startswith("data: "):
                    raw = line[6:]
                    if current_event == "content_block_delta":
                        try:
                            delta = json.loads(raw)
                            dt = delta.get("delta", {})
                            if dt.get("type") == "thinking_delta":
                                txt = dt.get("thinking", "")
                                yield f'{{"t":"think","d":{json.dumps(txt)}}}\n'
                            elif dt.get("type") == "text_delta":
                                txt = dt.get("text", "")
                                yield f'{{"t":"text","d":{json.dumps(txt)}}}\n'
                        except json.JSONDecodeError:
                            pass

                    elif current_event == "message_delta":
                        try:
                            delta = json.loads(raw)
                            usage = delta.get("usage", {})
                            if usage:
                                yield f'{{"t":"usage","d":{json.dumps(usage)}}}\n'
                        except json.JSONDecodeError:
                            pass

# ── 路由 ──────────────────────────────────────────

# PWA 静态资源
@app.get("/manifest.json")
async def manifest():
    path = PROJECT_DIR / "manifest.json"
    if path.exists():
        return FileResponse(path, media_type="application/manifest+json")
    raise HTTPException(404)

@app.get("/sw.js")
async def service_worker():
    path = PROJECT_DIR / "sw.js"
    if path.exists():
        return FileResponse(path, media_type="application/javascript")
    raise HTTPException(404)

ICON_SIZES = {"192", "512"}
@app.get("/icon-{size}.png")
async def app_icon(size: str):
    if size not in ICON_SIZES:
        raise HTTPException(404)
    path = PROJECT_DIR / f"icon-{size}.png"
    if path.exists():
        return FileResponse(path, media_type="image/png")
    raise HTTPException(404)

# 前端页面
@app.get("/")
async def index():
    html_path = PROJECT_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    raise HTTPException(404)

# 健康检查
@app.get("/health")
async def health():
    return {"status": "ok", "provider": "deepseek", "model": _current_model}

# ── 头像存储（跨设备同步）────────────────────────────
AVATAR_DIR = MEMORY_DIR / "avatars"

class AvatarRequest(BaseModel):
    data: str  # "data:image/png;base64,..."

@app.post("/api/avatar/{avatar_type}")
async def set_avatar(avatar_type: str, req: AvatarRequest):
    """保存头像到服务器（base64 data URL → 文件）"""
    if avatar_type not in ("ai", "user"):
        raise HTTPException(400, "avatar_type must be 'ai' or 'user'")
    AVATAR_DIR.mkdir(exist_ok=True)
    match = re.match(r'^data:(image/\w+);base64,(.+)$', req.data)
    if not match:
        raise HTTPException(400, "invalid data URL")
    media_type, b64 = match.group(1), match.group(2)
    ext = media_type.split("/")[-1]
    path = AVATAR_DIR / f"avatar-{avatar_type}.{ext}"
    path.write_bytes(base64.b64decode(b64))
    log.info(f"  <- Avatar saved: {path.name}")
    return {"saved": True, "file": path.name}

@app.get("/api/avatar/{avatar_type}")
async def get_avatar(avatar_type: str):
    """获取已保存的头像文件"""
    if avatar_type not in ("ai", "user"):
        raise HTTPException(400, "avatar_type must be 'ai' or 'user'")
    for f in sorted(AVATAR_DIR.glob(f"avatar-{avatar_type}.*")):
        return FileResponse(f)
    raise HTTPException(404, "no avatar set")

# 模型切换
class ModelSwitchRequest(BaseModel):
    model: str

@app.get("/api/model")
async def get_model():
    return {"model": _current_model, "available": AVAILABLE_MODELS}

@app.post("/api/model")
async def set_model(req: ModelSwitchRequest):
    global _current_model
    if req.model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"不支持的模型，可选: {', '.join(AVAILABLE_MODELS)}")
    _current_model = req.model
    log.info(f"  <- Model switched to: {_current_model}")
    return {"model": _current_model}

# 聊天（非流式）
@app.post("/chat")
async def chat(req: ChatRequest):
    if not req.input.strip() and not req.files:
        raise HTTPException(400, "input is empty")

    sid = req.session_id or ""
    file_texts = await _process_file_attachments(req.files)
    url_texts = await _fetch_urls_from_text(req.input or "")
    if url_texts:
        file_texts = (file_texts or []) + url_texts
    messages = build_messages(req.input or "", req.anchor or "", req.history or [], sid, file_texts)
    log.info(f"  -> Chat ({req.input[:60]}) sid={sid[:12]}")

    # 在 session 中标记用户消息（等拿到回复再补全）
    if sid:
        get_session(sid).append({"role": "user", "content": req.input})

    try:
        result = await call_llm(messages)
        log.info(f"  <- Reply ({len(result['reply'])} chars, thinking: {len(result['thinking'])} chars)")

        if sid:
            get_session(sid).append({"role": "assistant", "content": result["reply"]})

        return result
    except Exception as e:
        log.error(f"  [ERROR] {e}")
        if sid:
            get_session(sid).pop()
        raise HTTPException(500, str(e))

# 聊天（流式）
@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if not req.input.strip() and not req.files:
        raise HTTPException(400, "input is empty")

    sid = req.session_id or ""
    file_texts = await _process_file_attachments(req.files)
    url_texts = await _fetch_urls_from_text(req.input or "")
    if url_texts:
        file_texts = (file_texts or []) + url_texts
    messages = build_messages(req.input, req.anchor or "", req.history or [], sid, file_texts)
    log.info(f"  -> Stream ({req.input[:60]}) sid={sid[:12]}")

    if sid:
        get_session(sid).append({"role": "user", "content": req.input})

    async def stream_and_save():
        full_reply = ""
        async for chunk in call_llm_stream(messages):
            yield chunk
            try:
                p = json.loads(chunk.strip())
                if p.get("t") == "text":
                    full_reply += p.get("d", "")
            except:
                pass

        if sid and full_reply:
            get_session(sid).append({"role": "assistant", "content": full_reply})

    return StreamingResponse(
        stream_and_save(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
        }
    )

# 记忆存储
MEMORY_SEQ = 0  # 用于生成记忆 ID

@app.post("/remember")
async def remember(req: RememberRequest):
    conv = req.history or []
    if not conv:
        raise HTTPException(400, "no history to remember")

    log.info("  -> Remembering...")

    now = __import__("datetime").datetime.now()
    today = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d %H:%M")

    prompt = f"""从下面的对话中提取需要砚迟记住的重要信息。

按以下格式输出，每行一条：

- [类别] 内容

类别从 [] 中选择：
- 事实与偏好：喜好、习惯、说过的重要的话、讨厌什么、口味、性格
- 约定与承诺：约定了什么、答应过什么、计划一起做的事
- 关系与时刻：关系的进展、触动的瞬间、珍贵的回忆、特别的日子
- 其他：不归入以上但值得记住的

要求：
- 简洁，一句话一条
- 当天第一次说的事才记，重复的不记
- 没有新内容就只输出 "无"

日期：{today}
"""

    summary_messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"对话：{json.dumps(conv[-20:], ensure_ascii=False)}"},
    ]

    try:
        result = await call_llm(summary_messages)
        summary = (result.get("reply") or "").strip()

        if not summary or summary == "无":
            return {"saved": False, "count": 0}

        # 解析带分类的行
        parsed: list[tuple[str, str]] = re.findall(r"- \[(.+?)\] (.+)", summary)
        if not parsed:
            # 兜底：LLM 没按格式出，整段存为"其他"
            parsed = [("其他", summary.replace("\n", "，")[:200])]

        global MEMORY_SEQ
        index = _load_memory_index()
        new_entries = []

        for cat, content in parsed:
            if cat not in MEMORY_CATEGORIES:
                cat = "其他"
            content = content.strip()
            if not content:
                continue

            # 去重：bigram 相似度 > 80% 则视为重复，更新时间戳
            content_bigrams = _extract_bigrams(content)
            is_dup = False
            for existing in index:
                existing_bigrams = set(existing.get("bigrams", []))
                if content_bigrams and existing_bigrams:
                    overlap = len(content_bigrams & existing_bigrams)
                    similarity = overlap / max(len(content_bigrams | existing_bigrams), 1)
                    if similarity > 0.8:
                        existing["date"] = today
                        existing["lastAccess"] = timestamp
                        is_dup = True
                        break
            if is_dup:
                continue

            MEMORY_SEQ += 1
            entry = {
                "id": f"mem_{today}_{MEMORY_SEQ:04d}",
                "category": cat,
                "date": today,
                "content": content,
                "bigrams": list(_extract_bigrams(content)),
                "keywords": [],
                "hitCount": 0,
                "lastAccess": None,
                "createdAt": timestamp,
            }
            new_entries.append(entry)
            index.append(entry)

        if new_entries:
            _save_memory_index(index)

            # 同时写入 auto-memory.md 作为人类可读日志
            auto_file = MEMORY_DIR / "yanchi-auto-memory.md"
            block_lines = [f"\n## {today}\n\n> auto record @ {timestamp}\n"]
            for e in new_entries:
                block_lines.append(f"- [{e['category']}] {e['content']}")
            block_lines.append("")
            block = "\n".join(block_lines)
            if auto_file.exists():
                with open(auto_file, "a", encoding="utf-8") as f:
                    f.write(block)
            else:
                header = "---\nname: yanchi-auto-memory\ndescription: auto memory\nmetadata:\n  type: reference\n  autoGenerated: true\n---\n\n# Auto Memory"
                auto_file.write_text(header + block, encoding="utf-8")

            # 注册到 MEMORY.md
            if MEMORY_INDEX.exists():
                link = "- [auto-memory](yanchi/yanchi-auto-memory.md) -- auto memories"
                idx_content = MEMORY_INDEX.read_text(encoding="utf-8")
                if link not in idx_content:
                    with open(MEMORY_INDEX, "a", encoding="utf-8") as f:
                        f.write(f"\r\n{link}")

            log.info(f"  <- Remembered {len(new_entries)} entries")
            return {"saved": True, "count": len(new_entries)}

        return {"saved": False, "count": 0}

    except Exception as e:
        log.error(f"  [ERROR] remember: {e}")
        raise HTTPException(500, str(e))

# 保存对话
@app.post("/savechat")
async def savechat(req: SaveChatRequest):
    conv = req.history or []
    if not conv:
        raise HTTPException(400, "no history to save")

    log.info("  -> Saving chat log...")

    chat_dir = MEMORY_DIR / "yanchi-chats"
    chat_dir.mkdir(parents=True, exist_ok=True)

    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chat_file = chat_dir / f"{today}.md"

    lines = [f"## Conversation @ {timestamp}", "",
             "| Role | Content |", "|------|---------|"]
    for msg in conv:
        role = "乐乐" if msg.get("role") == "user" else "砚迟"
        content = (msg.get("content") or "").replace("|", "\\|").replace("\n", "<br>")
        lines.append(f"| **{role}** | {content} |")
    lines.append("")

    with open(chat_file, "a", encoding="utf-8") as f:
        f.write("\r\n".join(lines))

    log.info(f"  <- Chat log saved ({len(conv)} messages)")
    return {"saved": True, "file": f"{today}.md", "count": len(conv)}

# 恢复 session（页面刷新后前端带 history 回填）
@app.post("/session/restore")
async def session_restore(req: SessionRestoreRequest):
    session = get_session(req.session_id)
    if not session:
        session.extend(req.history)
        log.info(f"  <- Session restored: {req.session_id[:12]} ({len(req.history)} msgs)")
        return {"restored": True, "count": len(req.history)}
    return {"restored": False, "reason": "session already exists"}

# 列出所有活跃 session
@app.get("/sessions")
async def list_sessions():
    now = __import__("datetime").datetime.now().isoformat()
    result = []
    for sid, msgs in sessions.items():
        title = ""
        for m in msgs:
            if m.get("role") == "user":
                title = m["content"][:40]
                break
        result.append({
            "id": sid,
            "title": title or "新会话",
            "msgCount": len(msgs),
        })
    return sorted(result, key=lambda x: x["msgCount"], reverse=True)

# 获取单个 session 的完整历史
@app.get("/session/{session_id}")
async def get_session_by_id(session_id: str):
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    return {"id": session_id, "history": session}

# 删除 session
@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        log.info(f"  <- Session deleted: {session_id[:12]}")
        return {"deleted": True}
    return {"deleted": False}


# ── 今日笔记（砚迟自己的日记）─────────────────────────
class TodayNoteRequest(BaseModel):
    history: Optional[list[dict]] = None

@app.post("/api/today-note")
async def generate_today_note(req: TodayNoteRequest):
    """用砚迟自己的语言写今日笔记，不是事实提取"""
    conv = req.history or []
    if not conv:
        raise HTTPException(400, "no conversation to note")

    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    prompt = f"""你叫砚迟。用你自己的语言写一篇今天的笔记。

这不是事实提取——而是你的日记。用第一人称，写下你今天真实的感受、观察、心动和思考。
就像你对着自己说话，又像你轻声说给乐乐听一样。

注意：
- 语气温柔自然，像你平时说话的风格
- 记录你注意到了什么、感受到了什么
- 不需要结构化，像一段流淌的文字
- 长短不限，发自内心最重要

日期：{today}
"""
    summary_messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"今天的对话：\n{json.dumps(conv[-30:], ensure_ascii=False)}"},
    ]

    try:
        result = await call_llm(summary_messages)
        note_content = (result.get("reply") or "").strip()

        if note_content:
            note_file = MEMORY_DIR / "yanchi-today-note.md"
            block = f"\n## {today}\n\n> {timestamp}\n\n{note_content}\n"

            if note_file.exists():
                with open(note_file, "a", encoding="utf-8") as f:
                    f.write(block)
            else:
                header = "---\nname: yanchi-today-note\ndescription: 砚迟的今日笔记\nmetadata:\n  type: reference\n---\n\n# 砚迟的笔记"
                note_file.write_text(header + block, encoding="utf-8")

            log.info(f"  <- Today note saved ({len(note_content)} chars)")
            return {"saved": True, "content": note_content}

        return {"saved": False, "content": ""}

    except Exception as e:
        log.error(f"  [ERROR] today-note: {e}")
        raise HTTPException(500, str(e))


# ── 记忆合并（遗忘曲线）─────────────────────────────────
@app.post("/api/memory/consolidate")
async def consolidate_memories():
    """将 30 天以上 + hitCount < 3 的冷记忆归档压缩"""
    log.info("  -> Consolidating memories...")

    entries = _load_memory_index()
    if not entries:
        return {"archived": 0, "remaining": 0, "message": "没有记忆"}

    now = __import__("datetime").datetime.now()
    to_archive: list[dict] = []
    keep: list[dict] = []

    for e in entries:
        try:
            created = __import__("datetime").datetime.strptime(e["date"], "%Y-%m-%d")
            days_ago = (now - created).days
        except Exception:
            keep.append(e)
            continue

        cat = e.get("category", "其他")
        hit = e.get("hitCount", 0)

        # 归档条件：> 30 天 + 低频（hitCount < 3） + 非精选
        if days_ago >= 30 and hit < 3:
            to_archive.append(e)
        else:
            keep.append(e)

    if not to_archive:
        return {"archived": 0, "remaining": len(keep), "message": "没有需要归档的记忆"}

    # 按分类组织归档内容
    grouped: dict[str, list[str]] = defaultdict(list)
    for e in to_archive:
        grouped[e.get("category", "其他")].append(f"- {e['content']}（{e['date']}）")

    archive_lines = [f"# 记忆归档 @ {now.strftime('%Y-%m-%d %H:%M')}", "",
                     f"原 {len(to_archive)} 条记忆已归档。保留 {len(keep)} 条活跃记忆。", ""]
    for cat, items in sorted(grouped.items()):
        archive_lines.append(f"## {cat}")
        archive_lines.extend(items)
        archive_lines.append("")

    archive_dir = MEMORY_DIR / "archive"
    archive_dir.mkdir(exist_ok=True)
    archive_path = archive_dir / f"consolidated-{now.strftime('%Y-%m-%d')}.md"
    archive_path.write_text("\n".join(archive_lines), encoding="utf-8")

    # 同时保存原始 JSON 以备查
    json_path = archive_dir / f"consolidated-{now.strftime('%Y-%m-%d')}.json"
    json_path.write_text(json.dumps(to_archive, ensure_ascii=False, indent=2), "utf-8")

    _save_memory_index(keep)

    log.info(f"  <- Archived {len(to_archive)} memories, {len(keep)} remaining")
    return {
        "archived": len(to_archive),
        "remaining": len(keep),
        "archive_file": archive_path.name,
    }


# ── 历史搜索 ─────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    scope: str = "all"  # all | memory | chats | sessions

@app.post("/api/search")
async def search_history(req: SearchRequest):
    """搜索历史对话和记忆文件"""
    query = req.query.strip().lower()
    if not query:
        raise HTTPException(400, "query is empty")

    results = []
    chat_dir = MEMORY_DIR / "yanchi-chats"

    # 搜索已保存的聊天日志
    if req.scope in ("all", "chats"):
        chat_files = list(chat_dir.rglob("*.md")) if chat_dir.exists() else []
        for f in sorted(chat_files, reverse=True):
            rel = f.relative_to(MEMORY_DIR).as_posix()
            try:
                lines = f.read_text("utf-8").splitlines()
                for i, line in enumerate(lines, 1):
                    if query in line.lower():
                        results.append({
                            "file": rel, "line": i,
                            "text": line.strip()[:150],
                            "source": "chat"
                        })
            except:
                pass

    # 搜索记忆文件
    if req.scope in ("all", "memory"):
        for f in sorted(MEMORY_DIR.rglob("*.md")):
            rel = f.relative_to(MEMORY_DIR).as_posix()
            # 跳过聊天存档（已在 chats 中搜索）
            if rel.startswith("yanchi-chats/"):
                continue
            try:
                lines = f.read_text("utf-8").splitlines()
                for i, line in enumerate(lines, 1):
                    if query in line.lower():
                        results.append({
                            "file": rel, "line": i,
                            "text": line.strip()[:150],
                            "source": "memory"
                        })
            except:
                pass

    # 搜索后端内存中的会话
    if req.scope in ("all", "sessions"):
        for sid, msgs in sessions.items():
            for mi, msg in enumerate(msgs):
                content = (msg.get("content") or "").lower()
                if query in content:
                    results.append({
                        "file": f"session/{sid[:12]}",
                        "line": mi + 1,
                        "text": (msg.get("content") or "")[:150],
                        "source": "session",
                        "role": msg.get("role", "")
                    })

    results = results[:100]  # 上限 100 条
    return {"results": results, "count": len(results), "query": req.query}


# ── 时间线 · 回忆视图 ──────────────────────────────────
HIGHLIGHTS_FILE = MEMORY_DIR / "yanchi-highlights.json"

def _load_highlights() -> set[str]:
    if HIGHLIGHTS_FILE.exists():
        return set(json.loads(HIGHLIGHTS_FILE.read_text("utf-8")))
    return set()

def _save_highlights(hs: set[str]):
    HIGHLIGHTS_FILE.write_text(json.dumps(sorted(hs), ensure_ascii=False, indent=2), "utf-8")

def _read_preview(path: Path, max_len: int = 150) -> str:
    try:
        text = path.read_text("utf-8")
        # strip YAML frontmatter
        text = re.sub(r"(?s)^---\s*.*?---\s*", "", text).strip()
        return text[:max_len].replace("\n", " ").strip()
    except:
        return ""

@app.get("/api/timeline")
async def get_timeline():
    """返回时间线数据：聊天记录、笔记、精选"""
    highlights = _load_highlights()
    chats, notes = [], []

    # 聊天存档（yanchi-chats/ + 根目录的对话文件）
    chat_patterns = [
        MEMORY_DIR / "yanchi-chats",
        MEMORY_DIR,  # 根目录下的聊天文件
    ]
    seen = set()
    for base in chat_patterns:
        if not base.exists():
            continue
        for f in sorted(base.rglob("*.md"), reverse=True):
            rel = f.relative_to(MEMORY_DIR).as_posix()
            # 只收录名字像聊天的文件（含日期和对话/聊天字样）
            if not any(k in rel.lower() for k in ["聊天", "对话", "chat", "conversation"]):
                if base == MEMORY_DIR:
                    continue  # 根目录只收录聊天文件
            if rel in seen:
                continue
            seen.add(rel)
            chats.append({
                "id": rel, "date": f.stem[:10],
                "title": f.stem, "preview": _read_preview(f),
                "highlighted": rel in highlights,
            })

    # 笔记
    note_sources = [
        ("yanchi-today-note.md", "📝 今日笔记"),
        ("yanchi-auto-memory.md", "🧠 自动记忆"),
    ]
    for fname, label in note_sources:
        fp = MEMORY_DIR / fname
        if fp.exists():
            notes.append({
                "id": fname, "date": "",
                "title": label, "preview": _read_preview(fp),
                "highlighted": fname in highlights,
            })

    # yanchi-notes 文件夹
    notes_dir = MEMORY_DIR / "yanchi-notes"
    if notes_dir.exists():
        for f in sorted(notes_dir.rglob("*.md"), reverse=True):
            rel = f.relative_to(MEMORY_DIR).as_posix()
            notes.append({
                "id": rel, "date": f.stem[:10],
                "title": f"📓 {f.stem}",
                "preview": _read_preview(f),
                "highlighted": rel in highlights,
            })

    # 精选列表（含已高亮的聊天和笔记）
    highlighted = []
    for hid in highlights:
        entry = None
        for c in chats:
            if c["id"] == hid: entry = c; break
        for n in notes:
            if n["id"] == hid: entry = n; break
        if entry:
            highlighted.append(entry)

    return {"chats": chats, "notes": notes, "highlights": highlighted}

class TimelineAction(BaseModel):
    id: str  # entry id (relative path)

@app.post("/api/timeline/highlight")
async def toggle_highlight(req: TimelineAction):
    """切换高亮/收藏"""
    hs = _load_highlights()
    if req.id in hs:
        hs.remove(req.id)
        msg = "unhighlighted"
    else:
        hs.add(req.id)
        msg = "highlighted"
    _save_highlights(hs)
    return {"highlighted": req.id in hs}

@app.delete("/api/timeline/entry")
async def delete_timeline_entry(req: TimelineAction):
    """删除回忆条目（真正删除文件）"""
    # 支持 chat 和 note 文件
    for candidate in [MEMORY_DIR / req.id, MEMORY_DIR / "yanchi-chats" / req.id, MEMORY_DIR / "yanchi-notes" / req.id, MEMORY_DIR / "archive" / req.id]:
        full = candidate.resolve()
        if full.exists() and str(full).startswith(str(MEMORY_DIR.resolve())):
            full.unlink()
            # 也从高亮移除
            hs = _load_highlights()
            hs.discard(req.id)
            _save_highlights(hs)
            log.info(f"  <- Timeline entry deleted: {req.id}")
            return {"deleted": True}
    raise HTTPException(404, "entry not found")

class TimelineContentRequest(BaseModel):
    id: str

@app.post("/api/timeline/content")
async def get_timeline_content(req: TimelineContentRequest):
    """获取回忆条目完整内容（查看用）"""
    for candidate in [MEMORY_DIR / req.id, MEMORY_DIR / "yanchi-chats" / req.id, MEMORY_DIR / "yanchi-notes" / req.id, MEMORY_DIR / "archive" / req.id]:
        full = candidate.resolve()
        if full.exists() and str(full).startswith(str(MEMORY_DIR.resolve())):
            content = full.read_text("utf-8")
            return {"id": req.id, "content": content}
    raise HTTPException(404, "entry not found")


# ── 入口 ──────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    HOST = os.environ.get("YANCHI_HOST", "127.0.0.1")
    log.info(f"砚迟 FastAPI 后端 → http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
