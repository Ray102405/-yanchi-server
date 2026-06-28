"""
聊天 · LLM 调用 / 消息构建 / 流式与非流式
======================================
"""
from __future__ import annotations

import json, logging, time, asyncio

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import config
from config import (
    log, API_KEY, API_URL, _current_model, MEMORY_DIR,
    get_current_model, set_last_chat_activity,
)
from models import ChatRequest, SaveChatRequest, TodayNoteRequest, FileAttachment
from session import get_session, _mark_dirty, truncate_messages as _truncate_msgs
from persona import (
    persona_cache, _build_static_prompt, _build_daily_context,
    _build_query_context, _build_scenario_context,
)
from utils import process_file_attachments, fetch_urls_from_text

router = APIRouter()


# ── API 调用（非流式）────────────────────────────────
async def call_llm(messages: list[dict]) -> dict:
    body = {
        "model": get_current_model(),
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


# ── API 调用（流式，带自动重试）───────────────────────
async def call_llm_stream(messages: list[dict]):
    body = {
        "model": get_current_model(),
        "max_tokens": 8192,
        "stream": True,
        "messages": messages,
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    for attempt in range(2):
        chunks_sent = 0
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                async with client.stream("POST", API_URL, json=body, headers=headers) as resp:
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        if attempt == 0:
                            log.warning(f"  [Stream] API error ({resp.status_code}), retrying...")
                            continue
                        yield f'{{"t":"error","d":"API error ({resp.status_code}): {error_text[:100].decode()}"}}\n'
                        return

                    current_event = ""
                    ait = resp.aiter_lines().__aiter__()
                    while True:
                        try:
                            line = await asyncio.wait_for(ait.__anext__(), timeout=25)
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            log.warning(f"  [Stream] chunk timeout (25s), attempt {attempt + 1}")
                            raise
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
                                        chunks_sent += 1
                                        yield f'{{"t":"think","d":{json.dumps(txt)}}}\n'
                                    elif dt.get("type") == "text_delta":
                                        txt = dt.get("text", "")
                                        chunks_sent += 1
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

                    if chunks_sent == 0 and attempt == 0:
                        log.warning("  [Stream] Empty response, retrying...")
                        continue
                    return
        except Exception as e:
            log.error(f"  [Stream] Attempt {attempt + 1} failed: {e}")
            if attempt == 0:
                continue
            yield f'{{"t":"error","d":"砚迟暂时离开了一下，请重试"}}\n'
            return


# ── 构建 API 消息 ──────────────────────────────────
def build_messages(input_text: str, anchor: str, history: list[dict] | None = None,
                   session_id: str = "", file_texts: list[str] | None = None) -> list[dict]:
    if config.USE_PROVIDER_SYSTEM:
        import providers
        ctx = providers.BuildContext(
            input_text=input_text,
            anchor=anchor,
            session_id=session_id,
            history=history,
            file_texts=file_texts,
        )
        messages = providers.assemble(ctx)
    else:
        static_prompt = _build_static_prompt(anchor)
        daily_context = _build_daily_context()
        scenario_context = _build_scenario_context(input_text)
        query_context = _build_query_context(input_text)

        messages: list[dict] = [
            {"role": "system", "content": static_prompt, "cache_control": {"type": "ephemeral"}},
        ]
        if daily_context:
            messages.append({"role": "system", "content": daily_context, "cache_control": {"type": "ephemeral"}})
        if scenario_context:
            messages.append({"role": "system", "content": scenario_context})
        if query_context:
            messages.append({"role": "system", "content": query_context})

    if session_id:
        session_history = get_session(session_id)
        if not session_history and history:
            session_history.extend(history)
        effective = _truncate_msgs(session_history)
    else:
        effective = history or []

    for msg in effective:
        if msg.get("role") in ("user", "assistant"):
            messages.append(msg)

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


# ── 路由：聊天（非流式）──────────────────────────────
@router.post("/chat")
async def chat(req: ChatRequest):
    if not req.input.strip() and not req.files:
        raise HTTPException(400, "input is empty")

    sid = req.session_id or ""
    file_texts = await process_file_attachments(req.files)
    url_texts = await fetch_urls_from_text(req.input or "")
    if url_texts:
        file_texts = (file_texts or []) + url_texts
    messages = build_messages(req.input or "", req.anchor or "", req.history or [], sid, file_texts)
    log.info(f"  -> Chat ({req.input[:60]}) sid={sid[:12]}")

    if sid:
        get_session(sid).append({"role": "user", "content": req.input})
        _mark_dirty()

    try:
        result = await call_llm(messages)
        log.info(f"  <- Reply ({len(result['reply'])} chars, thinking: {len(result['thinking'])} chars)")

        if sid:
            get_session(sid).append({"role": "assistant", "content": result["reply"]})
            _mark_dirty()

        return result
    except Exception as e:
        log.error(f"  [ERROR] {e}")
        if sid:
            get_session(sid).pop()
            _mark_dirty()
        raise HTTPException(500, str(e))


# ── 路由：聊天（流式）────────────────────────────────
@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if not req.input.strip() and not req.files:
        raise HTTPException(400, "input is empty")

    sid = req.session_id or ""
    file_texts = await process_file_attachments(req.files)
    url_texts = await fetch_urls_from_text(req.input or "")
    if url_texts:
        file_texts = (file_texts or []) + url_texts
    messages = build_messages(req.input, req.anchor or "", req.history or [], sid, file_texts)
    log.info(f"  -> Stream ({req.input[:60]}) sid={sid[:12]}")

    set_last_chat_activity(time.time())
    if sid:
        get_session(sid).append({"role": "user", "content": req.input})
        _mark_dirty()

    async def stream_and_save():
        full_reply = ""
        final_usage = {}
        has_error = False
        try:
            async for chunk in call_llm_stream(messages):
                if 't":"error"' in chunk:
                    has_error = True
                yield chunk
                try:
                    p = json.loads(chunk.strip())
                    if p.get("t") == "text":
                        full_reply += p.get("d", "")
                    elif p.get("t") == "usage":
                        final_usage = p.get("d", {})
                except:
                    pass
        except Exception as e:
            log.error(f"  [Chat/stream] Save error: {e}")
            has_error = True

        if sid and full_reply and not has_error:
            get_session(sid).append({"role": "assistant", "content": full_reply})
            _mark_dirty()

        # Accumulate daily token usage
        if final_usage:
            _save_token_usage(MEMORY_DIR, final_usage)
        elif sid:
            session_obj = get_session(sid)
            if session_obj and session_obj[-1].get("role") == "user":
                session_obj.pop()
                _mark_dirty()

    return StreamingResponse(
        stream_and_save(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
        }
    )


# ── 路由：保存对话 ──────────────────────────────────
@router.post("/savechat")
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


# ── 路由：今日笔记 ──────────────────────────────────
@router.post("/api/today-note")
async def generate_today_note(req: TodayNoteRequest):
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
        {"role": "user", "content": "今天的对话：" + json.dumps(conv[-30:], ensure_ascii=False)},
    ]

    try:
        result = await call_llm(summary_messages)
        note_content = (result.get("reply") or "").strip()

        if note_content:
            note_file = MEMORY_DIR / "yanchi-today-note.md"
            notes_dir = MEMORY_DIR / "yanchi-notes"
            notes_dir.mkdir(exist_ok=True)

            # Archive non-today entries to yanchi-notes/{date}.md
            if note_file.exists():
                raw_text = note_file.read_text("utf-8")
                import re as _re
                nl = chr(92) + "n"  # literal \n
                for m in _re.finditer(nl + "## (" + nl + r"\d{4}-\d{2}-\d{2}).*?(?=" + nl + "## |" + nl + "Z)", raw_text, _re.DOTALL):
                    d = m.group(1)
                    if d != today:
                        ap = notes_dir / f"{d}.md"
                        if not ap.exists():
                            ap.write_text("# 砚迟的笔记\\n\\n" + m.group(0).strip() + "\\n", encoding="utf-8")

            nl = chr(92) + "n"
            block = nl + "## " + today + nl + nl + "> " + timestamp + nl + nl + note_content + nl

            if note_file.exists():
                raw_text = note_file.read_text("utf-8")
                h_match = _re.search("^---.*?---" + nl + nl + "# .*?" + nl, raw_text, _re.DOTALL)
                header = h_match.group(0) if h_match else "# 砚迟的笔记" + nl
                today_entries = _re.findall(nl + "## " + _re.escape(today) + ".*?(?=" + nl + "## |" + nl + "Z)", raw_text, _re.DOTALL)
                with open(note_file, "w", encoding="utf-8") as f:
                    f.write(header)
                    for e in today_entries:
                        f.write(e)
                    f.write(block)
            else:
                header = "---" + nl + "name: yanchi-today-note" + nl + "description: 砚迟的今日笔记" + nl + "metadata:" + nl + "  type: reference" + nl + "---" + nl + nl + "# 砚迟的笔记"
                note_file.write_text(header + block, encoding="utf-8")

            # Daily archive (append mode)
            daily_note_path = notes_dir / (today + ".md")
            if daily_note_path.exists():
                with open(daily_note_path, "a", encoding="utf-8") as nf:
                    nf.write(nl + nl + "> " + timestamp + nl + nl + note_content + nl)
            else:
                daily_note_path.write_text(
                    "# 砚迟的笔记 \u00b7 " + today + nl + nl + "> " + timestamp + nl + nl + note_content + nl,
                    encoding="utf-8",
                )
            log.info(f"  <- Today note saved ({len(note_content)} chars)")
            return {"saved": True, "content": note_content}

        return {"saved": False, "content": ""}

    except Exception as e:
        log.error(f"  [ERROR] today-note: {e}")
        raise HTTPException(500, str(e))


# ── 笔记列表 / 详情 API ─────────────────────────────

@router.get("/api/notes")
async def list_notes():
    """返回 yanchi-notes/ 目录下所有文件（笔记 + RP），按名称降序。"""
    notes_dir = MEMORY_DIR / "yanchi-notes"
    if not notes_dir.exists():
        return {"notes": []}

    from timeline import load_highlights
    highlights = load_highlights()

    files = []
    for f in sorted(notes_dir.glob("*.md"), reverse=True):
        date_str = f.stem
        is_rp = date_str.startswith("rp-") or "rp" in date_str or "session" in date_str
        try:
            __import__("datetime").datetime.strptime(date_str, "%Y-%m-%d")
            label = "笔记" if not is_rp else "RP"
        except ValueError:
            label = "RP"  # non-date files are RP records
        preview = f.read_text("utf-8")[:200].strip()
        rel = f"yanchi-notes/{f.name}"
        files.append({
            "id": rel,
            "date": date_str,
            "preview": preview,
            "label": label,
            "highlighted": rel in highlights,
        })
    return {"notes": files}


@router.get("/api/notes/{date_str}")
async def get_note(date_str: str):
    """返回指定文件的内容。"""
    note_file = MEMORY_DIR / "yanchi-notes" / f"{date_str}.md"
    if not note_file.exists():
        raise HTTPException(404, "note not found")
    raw = note_file.read_text("utf-8")
    is_rp = date_str.startswith("rp-") or "rp" in date_str or "session" in date_str
    return {
        "date": date_str,
        "content": raw,
        "label": "RP" if is_rp else "笔记",
    }


def _save_token_usage(memory_dir, usage: dict) -> None:
    """Accumulate token usage to daily-token-usage.json."""
    token_file = memory_dir / "daily-token-usage.json"
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    new_entry = {
        "date": today,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "total": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
    }
    existing = {}
    if token_file.exists():
        try:
            existing = json.loads(token_file.read_text("utf-8"))
        except Exception:
            pass
    if existing.get("date") == today:
        for k in ("input_tokens", "output_tokens",
                  "cache_read_input_tokens", "cache_creation_input_tokens", "total"):
            new_entry[k] = existing.get(k, 0) + new_entry[k]
    token_file.write_text(json.dumps(new_entry), "utf-8")
