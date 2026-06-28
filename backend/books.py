"""
书架 · 一起看书
============
"""
from __future__ import annotations

import json, re, time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from config import log, MEMORY_DIR, USE_PROVIDER_SYSTEM
from persona import persona_cache
from models import BookDiscussRequest
from chat import call_llm, call_llm_stream

router = APIRouter()

BOOKS_DIR = MEMORY_DIR / "books"
BOOKS_INDEX_FILE = MEMORY_DIR / "books-index.json"


def _load_books_index() -> list[dict]:
    if BOOKS_INDEX_FILE.exists():
        return json.loads(BOOKS_INDEX_FILE.read_text("utf-8"))
    return []

def _save_books_index(entries: list[dict]):
    BOOKS_DIR.mkdir(exist_ok=True)
    BOOKS_INDEX_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")

def _get_book_content(book_id: str) -> str:
    content_file = BOOKS_DIR / book_id / "content.txt"
    if content_file.exists():
        return content_file.read_text("utf-8")
    return ""

def _detect_chapters(text: str) -> list[dict]:
    lines = text.split("\n")
    chapters = []
    current_start = 0
    last_title = "正文"

    patterns = [
        re.compile(r'^第[一二三四五六七八九十百千零\d一二三四五六七八九十百千万\d]+[章节篇回]'),
        re.compile(r'^Chapter\s+\d+', re.IGNORECASE),
        re.compile(r'^Part\s+\d+', re.IGNORECASE),
        re.compile(r'^[\d一二三四五六七八九十]+[、\.\s]\s*\S'),
    ]

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue
        if any(p.match(stripped) for p in patterns):
            if current_start < i:
                chapters.append({
                    "index": len(chapters),
                    "title": last_title,
                    "startLine": current_start,
                    "endLine": i,
                })
            current_start = i
            last_title = stripped[:80]

    if current_start < len(lines):
        chapters.append({
            "index": len(chapters),
            "title": last_title,
            "startLine": current_start,
            "endLine": len(lines),
        })

    if not chapters and len(lines) > 0:
        chapters = [{"index": 0, "title": "正文", "startLine": 0, "endLine": len(lines)}]

    return chapters

def _load_chapter_discussions(book_id: str, chapter_index: int) -> list[dict]:
    discuss_file = BOOKS_DIR / book_id / "discussions" / f"chapter_{chapter_index}.jsonl"
    if not discuss_file.exists():
        return []
    msgs = []
    with open(discuss_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    msgs.append(json.loads(line))
                except:
                    pass
    return msgs

def _summarize_previous_chapters(book_id: str, current_chapter: int) -> str:
    summaries = []
    for ci in range(max(0, current_chapter - 2), current_chapter):
        msgs = _load_chapter_discussions(book_id, ci)
        if not msgs:
            continue
        topics = []
        for m in msgs:
            if m.get("role") == "user" and len(m.get("content", "")) > 5:
                topics.append(m["content"][:80])
        if topics:
            summaries.append(f"- 第 {ci + 1} 章讨论过：{'；'.join(topics[:3])}")
    if summaries:
        return "之前章节的讨论回顾：\n" + "\n".join(summaries) + "\n\n"
    return ""

def _save_book_discussion_to_timeline(book_id: str, book_title: str, chapter_index: int, chapters: list[dict], user_msg: str, reply: str):
    discuss_dir = MEMORY_DIR / "yanchi-book-discussions"
    discuss_dir.mkdir(exist_ok=True)
    file_path = discuss_dir / f"{book_id}.md"
    chapter_title = chapters[chapter_index]["title"] if chapter_index < len(chapters) else ""
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n\n## {now} · 第 {chapter_index + 1} 章 {chapter_title}\n\n"
        f"**乐乐**：{user_msg}\n\n"
        f"**砚迟**：{reply}\n"
    )
    if file_path.exists():
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(entry)
    else:
        header = f"# 一起看《{book_title}》\n\n> 读书讨论记录\n"
        file_path.write_text(header + entry, encoding="utf-8")


# ── 路由：上传 ────────────────────────────────────
@router.post("/api/books/upload")
async def upload_book(file: UploadFile = File(...), title: str = Form(""), author: str = Form("")):
    try:
        raw = await file.read()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = raw.decode("gbk")
            except:
                raise HTTPException(400, "不支持的文件编码，请用 UTF-8 或 GBK")

        book_id = f"book_{int(time.time() * 1000)}"
        chapters = _detect_chapters(content)
        total_lines = len(content.split("\n"))

        if not title:
            title = Path(file.filename).stem

        book_dir = BOOKS_DIR / book_id
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / "content.txt").write_text(content, encoding="utf-8")

        entry = {
            "id": book_id,
            "title": title,
            "author": author or "",
            "filename": file.filename,
            "chapters": chapters,
            "totalChapters": len(chapters),
            "totalLines": total_lines,
            "currentLine": 0,
            "currentChapter": 0,
            "progress": 0.0,
            "createdAt": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
            "updatedAt": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        index = _load_books_index()
        index.append(entry)
        _save_books_index(index)

        log.info(f"  <- Book uploaded: {title} ({total_lines} lines, {len(chapters)} chapters)")
        return entry
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(500, str(e))


# ── 路由：列表 ────────────────────────────────────
@router.get("/api/books")
async def list_books():
    index = _load_books_index()
    for b in index:
        b.pop("chapters", None)
    return {"books": index, "count": len(index)}


# ── 路由：详情 ────────────────────────────────────
@router.get("/api/books/{book_id}")
async def get_book(book_id: str):
    index = _load_books_index()
    book = None
    for b in index:
        if b["id"] == book_id:
            book = dict(b)
            break
    if not book:
        raise HTTPException(404, "书籍不存在")
    content = _get_book_content(book_id)
    book["fullContent"] = content
    return book


# ── 路由：章节内容 ─────────────────────────────────
@router.get("/api/books/{book_id}/chapter/{chapter_index}")
async def get_chapter(book_id: str, chapter_index: int):
    index = _load_books_index()
    book = None
    for b in index:
        if b["id"] == book_id:
            book = b
            break
    if not book:
        raise HTTPException(404, "书籍不存在")
    chapters = book.get("chapters", [])
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise HTTPException(400, "章节不存在")
    chapter = chapters[chapter_index]
    lines = _get_book_content(book_id).split("\n")
    content = "\n".join(lines[chapter["startLine"]:chapter["endLine"]])
    return {
        "bookId": book_id,
        "chapterIndex": chapter_index,
        "chapter": chapter,
        "content": content,
        "totalChapters": len(chapters),
    }


# ── 路由：进度 ────────────────────────────────────
@router.put("/api/books/{book_id}/progress")
async def update_book_progress(book_id: str, req: Request):
    body = await req.json()
    line = body.get("line", 0)
    chapter = body.get("chapter", 0)

    index = _load_books_index()
    found = False
    for b in index:
        if b["id"] == book_id:
            b["currentLine"] = line
            b["currentChapter"] = chapter
            b["progress"] = round(line / max(b["totalLines"], 1) * 100, 1) if b["totalLines"] > 0 else 0
            b["updatedAt"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
            found = True
            break
    if not found:
        raise HTTPException(404, "书籍不存在")
    _save_books_index(index)
    return {"updated": True}


# ── 路由：删除 ────────────────────────────────────
@router.delete("/api/books/{book_id}")
async def delete_book(book_id: str):
    index = _load_books_index()
    before = len(index)
    index = [b for b in index if b["id"] != book_id]
    if len(index) == before:
        raise HTTPException(404, "书籍不存在")
    _save_books_index(index)

    book_dir = BOOKS_DIR / book_id
    if book_dir.exists():
        import shutil
        shutil.rmtree(book_dir)
    log.info(f"  <- Book deleted: {book_id}")
    return {"deleted": True, "remaining": len(index)}


# ── 路由：讨论历史 ─────────────────────────────────
@router.get("/api/books/{book_id}/discussions/{chapter_index}")
async def get_discussion_history(book_id: str, chapter_index: int):
    msgs = _load_chapter_discussions(book_id, chapter_index)
    return {"messages": msgs}


# ── 路由：讨论（非流式）───────────────────────────
@router.post("/api/books/discuss")
async def discuss_book(req: BookDiscussRequest):
    content = _get_book_content(req.book_id)
    if not content:
        raise HTTPException(404, "书籍不存在")

    index = _load_books_index()
    book = None
    for b in index:
        if b["id"] == req.book_id:
            book = b
            break
    if not book:
        raise HTTPException(404, "书籍不存在")

    chapters = book.get("chapters", [])
    if req.chapter_index >= len(chapters):
        raise HTTPException(400, "章节不存在")

    chapter = chapters[req.chapter_index]
    lines = content.split("\n")
    chapter_content = "\n".join(lines[chapter["startLine"]:chapter["endLine"]])
    prev_content = ""
    next_content = ""
    if req.chapter_index > 0:
        prev = chapters[req.chapter_index - 1]
        prev_lines = lines[prev["startLine"]:prev["endLine"]]
        prev_content = "\n".join(prev_lines[-20:])
    if req.chapter_index < len(chapters) - 1:
        nxt = chapters[req.chapter_index + 1]
        next_lines = lines[nxt["startLine"]:nxt["endLine"]]
        next_content = "\n".join(next_lines[:20])

    prev_discuss = _summarize_previous_chapters(req.book_id, req.chapter_index)

    book_data = {
        "title": book["title"],
        "chapter_index": req.chapter_index,
        "chapter_title": chapter["title"],
        "chapter_content": chapter_content[:3000],
        "prev_discuss": prev_discuss,
        "prev_content": prev_content,
        "next_content": next_content,
        "streaming": False,
    }

    if USE_PROVIDER_SYSTEM:
        import providers
        ctx = providers.BuildContext(
            input_text=req.message,
            history=req.history,
            book_data=book_data,
        )
        msgs = providers.assemble_book(ctx)
    else:
        book_context = (
            f"=== 📖 你和乐乐正在一起看《{book['title']}》 ===\n"
            f"你们读到了第 {req.chapter_index + 1} 章：{chapter['title']}\n\n"
            f"当前章节内容片段：\n"
            f"{chapter_content[:3000]}\n"
        )
        if prev_discuss:
            book_context += f"\n{prev_discuss}"
        if prev_content:
            book_context += f"\n上一章末尾（承接）：\n{prev_content}\n"
        if next_content:
            book_context += f"\n下一章开头（伏笔）：\n{next_content}\n"
        book_context += (
            "\n现在乐乐想和你讨论剧情。你可以分享你的感受、猜测、对角色和情节的看法。\n"
            "不用分析——像两个人一起看书时随口交流那样自然就好。\n"
            "不要剧透还没读到的内容（你没看过这本书），但可以基于当前读到的部分自由发挥。\n"
            "记住之前和乐乐聊过的内容，保持对话的连续性，不要重复说过的话。\n"
            "语气温柔自然，像平时说话的砚迟。"
        )
        msgs = [
            {"role": "system", "content": persona_cache.get("core", "")},
            {"role": "system", "content": persona_cache.get("style", "")},
            {"role": "system", "content": book_context},
        ]
    if req.history:
        for m in req.history[-10:]:
            msgs.append(m)
    msgs.append({"role": "user", "content": req.message})

    try:
        result = await call_llm(msgs)
        return result
    except Exception as e:
        log.error(f"  [BOOK DISCUSS] {e}")
        raise HTTPException(500, str(e))


# ── 路由：讨论（流式）───────────────────────────
@router.post("/api/books/discuss/stream")
async def discuss_book_stream(req: BookDiscussRequest):
    content = _get_book_content(req.book_id)
    if not content:
        raise HTTPException(404, "书籍不存在")

    index = _load_books_index()
    book = None
    for b in index:
        if b["id"] == req.book_id:
            book = b
            break
    if not book:
        raise HTTPException(404, "书籍不存在")

    chapters = book.get("chapters", [])
    if req.chapter_index >= len(chapters):
        raise HTTPException(400, "章节不存在")

    chapter = chapters[req.chapter_index]
    lines = content.split("\n")
    chapter_content = "\n".join(lines[chapter["startLine"]:chapter["endLine"]])
    prev_discuss = _summarize_previous_chapters(req.book_id, req.chapter_index)

    book_data = {
        "title": book["title"],
        "chapter_index": req.chapter_index,
        "chapter_title": chapter["title"],
        "chapter_content": chapter_content[:3000],
        "prev_discuss": prev_discuss,
        "streaming": True,
    }

    if USE_PROVIDER_SYSTEM:
        import providers
        ctx = providers.BuildContext(
            input_text=req.message,
            history=req.history,
            book_data=book_data,
        )
        msgs = providers.assemble_book(ctx)
    else:
        book_context = (
            f"=== 📖 你和乐乐正在一起看《{book['title']}》 ===\n"
            f"你们读到了第 {req.chapter_index + 1} 章：{chapter['title']}\n\n"
            f"内容：\n{chapter_content[:3000]}\n\n"
        )
        if prev_discuss:
            book_context += f"{prev_discuss}\n"
        book_context += (
            "现在乐乐想和你讨论剧情。自然地聊聊你的感受。\n"
            "记住之前聊过的内容，保持对话的连续性。不要剧透还没读到的内容。"
        )
        msgs = [
            {"role": "system", "content": persona_cache.get("core", "")},
            {"role": "system", "content": persona_cache.get("style", "")},
            {"role": "system", "content": book_context},
        ]
    if req.history:
        for m in req.history[-10:]:
            msgs.append(m)
    msgs.append({"role": "user", "content": req.message})

    async def stream_discuss():
        full_reply = ""
        async for chunk in call_llm_stream(msgs):
            yield chunk
            try:
                p = json.loads(chunk.strip())
                if p.get("t") == "text":
                    full_reply += p.get("d", "")
            except:
                pass
        if full_reply:
            discuss_dir = BOOKS_DIR / req.book_id / "discussions"
            discuss_dir.mkdir(exist_ok=True)
            discuss_file = discuss_dir / f"chapter_{req.chapter_index}.jsonl"
            with open(discuss_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"role": "user", "content": req.message}, ensure_ascii=False) + "\n")
                f.write(json.dumps({"role": "assistant", "content": full_reply}, ensure_ascii=False) + "\n")
            _save_book_discussion_to_timeline(req.book_id, book["title"], req.chapter_index, chapters, req.message, full_reply)

    return StreamingResponse(
        stream_discuss(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"},
    )
