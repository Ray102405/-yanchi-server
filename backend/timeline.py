"""
时间线 · 回忆视图 / 精选 / 搜索
============================
"""
from __future__ import annotations

import json, re
from pathlib import Path

from fastapi import APIRouter, HTTPException

import sys as _sys
from config import log, MEMORY_DIR
from models import SearchRequest, TimelineAction, TimelineContentRequest

router = APIRouter()

# ── 精选文件 ──────────────────────────────────────
HIGHLIGHTS_FILE = MEMORY_DIR / "yanchi-highlights.json"


def load_highlights() -> set[str]:
    if HIGHLIGHTS_FILE.exists():
        return set(json.loads(HIGHLIGHTS_FILE.read_text("utf-8")))
    return set()

def _save_highlights(hs: set[str]):
    HIGHLIGHTS_FILE.write_text(json.dumps(sorted(hs), ensure_ascii=False, indent=2), "utf-8")

def read_preview(path: Path, max_len: int = 150) -> str:
    try:
        text = path.read_text("utf-8")
        text = re.sub(r"(?s)^---\s*.*?---\s*", "", text).strip()
        return text[:max_len].replace("\n", " ").strip()
    except:
        return ""


# ── 路由：时间线 ──────────────────────────────────
@router.get("/api/timeline")
async def get_timeline():
    highlights = load_highlights()
    chats, notes = [], []

    chat_patterns = [
        MEMORY_DIR / "yanchi-chats",
        MEMORY_DIR,
    ]
    seen = set()
    for base in chat_patterns:
        if not base.exists():
            continue
        for f in sorted(base.rglob("*.md"), reverse=True):
            rel = f.relative_to(MEMORY_DIR).as_posix()
            if not any(k in rel.lower() for k in ["聊天", "对话", "chat", "conversation"]):
                if base == MEMORY_DIR:
                    continue
            if rel in seen:
                continue
            seen.add(rel)
            chats.append({
                "id": rel, "date": f.stem[:10],
                "title": f.stem, "preview": read_preview(f),
                "highlighted": rel in highlights,
            })

    for sid, msgs in _sys.modules['session'].sessions.items():
        date_str = ""
        try:
            parts = sid.split("_")
            if len(parts) >= 2:
                ts = int(parts[1], 36) if parts[1] else 0
                if ts:
                    date_str = __import__("datetime").datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        except Exception:
            pass
        title = ""
        for m in msgs:
            if m.get("role") == "user":
                title = m["content"][:50]
                break
        cid = f"session_{sid}"
        if cid not in seen:
            seen.add(cid)
            chats.append({
                "id": f"session_{sid}",
                "date": date_str,
                "title": title or "会话",
                "preview": f"共 {len(msgs)} 条消息",
                "highlighted": False,
                "session": True,
            })

    note_sources = [
        ("yanchi-today-note.md", "📝 今日笔记"),
        ("yanchi-auto-memory.md", "🧠 自动记忆"),
    ]
    for fname, label in note_sources:
        fp = MEMORY_DIR / fname
        if fp.exists():
            notes.append({
                "id": fname, "date": "",
                "title": label, "preview": read_preview(fp),
                "highlighted": fname in highlights,
            })

    notes_dir = MEMORY_DIR / "yanchi-notes"
    if notes_dir.exists():
        for f in sorted(notes_dir.rglob("*.md"), reverse=True):
            rel = f.relative_to(MEMORY_DIR).as_posix()
            notes.append({
                "id": rel, "date": f.stem[:10],
                "title": f"📓 {f.stem}",
                "preview": read_preview(f),
                "highlighted": rel in highlights,
            })

    discuss_dir = MEMORY_DIR / "yanchi-book-discussions"
    discussions = []
    if discuss_dir.exists():
        for f in sorted(discuss_dir.rglob("*.md"), reverse=True):
            rel = f.relative_to(MEMORY_DIR).as_posix()
            lines = f.read_text("utf-8").split("\n")
            title = "读书讨论"
            date = ""
            for line in lines:
                if line.startswith("# 一起看"):
                    title = f"📚 {line.strip('# ')}"
                if line.startswith("## "):
                    date = line[3:13]
            discussions.append({
                "id": rel,
                "date": date,
                "title": title,
                "preview": read_preview(f, 150),
                "highlighted": rel in highlights,
            })

    highlighted = []
    for hid in highlights:
        entry = None
        for c in chats:
            if c["id"] == hid: entry = c; break
        for n in notes:
            if n["id"] == hid: entry = n; break
        for d in discussions:
            if d["id"] == hid: entry = d; break
        if entry:
            highlighted.append(entry)

    return {"chats": chats, "notes": notes, "discussions": discussions, "highlights": highlighted}


# ── 路由：切换高亮 ─────────────────────────────────
@router.post("/api/timeline/highlight")
async def toggle_highlight(req: TimelineAction):
    hs = load_highlights()
    if req.id in hs:
        hs.remove(req.id)
    else:
        hs.add(req.id)
    _save_highlights(hs)
    return {"highlighted": req.id in hs}


# ── 路由：删除条目 ─────────────────────────────────
@router.delete("/api/timeline/entry")
async def delete_timeline_entry(req: TimelineAction):
    for candidate in [
        MEMORY_DIR / req.id,
        MEMORY_DIR / "yanchi-chats" / req.id,
        MEMORY_DIR / "yanchi-notes" / req.id,
        MEMORY_DIR / "yanchi-book-discussions" / req.id,
        MEMORY_DIR / "archive" / req.id,
    ]:
        full = candidate.resolve()
        if full.exists() and str(full).startswith(str(MEMORY_DIR.resolve())):
            full.unlink()
            hs = load_highlights()
            hs.discard(req.id)
            _save_highlights(hs)
            log.info(f"  <- Timeline entry deleted: {req.id}")
            return {"deleted": True}
    raise HTTPException(404, "entry not found")


# ── 路由：条目内容 ─────────────────────────────────
@router.post("/api/timeline/content")
async def get_timeline_content(req: TimelineContentRequest):
    if req.id.startswith("session_"):
        sid = req.id[len("session_"):]
        msgs = _sys.modules['session'].sessions.get(sid)
        if msgs:
            lines = []
            for m in msgs:
                role = "乐乐" if m.get("role") == "user" else "砚迟"
                content = m.get("content", "")
                ts = m.get("timestamp", "")
                lines.append(f"**{role}**" + (f" ({ts})" if ts else ""))
                lines.append(content)
                lines.append("")
            return {"id": req.id, "content": "\n".join(lines)}

    for candidate in [
        MEMORY_DIR / req.id,
        MEMORY_DIR / "yanchi-chats" / req.id,
        MEMORY_DIR / "yanchi-notes" / req.id,
        MEMORY_DIR / "yanchi-book-discussions" / req.id,
        MEMORY_DIR / "archive" / req.id,
    ]:
        full = candidate.resolve()
        if full.exists() and str(full).startswith(str(MEMORY_DIR.resolve())):
            content = full.read_text("utf-8")
            return {"id": req.id, "content": content}
    raise HTTPException(404, "entry not found")


# ── 路由：搜索 ────────────────────────────────────
@router.post("/api/search")
async def search_history(req: SearchRequest):
    query = req.query.strip().lower()
    if not query:
        raise HTTPException(400, "query is empty")

    results = []
    chat_dir = MEMORY_DIR / "yanchi-chats"

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
                            "source": "chat",
                        })
            except:
                pass

    if req.scope in ("all", "memory"):
        for f in sorted(MEMORY_DIR.rglob("*.md")):
            rel = f.relative_to(MEMORY_DIR).as_posix()
            if rel.startswith("yanchi-chats/"):
                continue
            try:
                lines = f.read_text("utf-8").splitlines()
                for i, line in enumerate(lines, 1):
                    if query in line.lower():
                        results.append({
                            "file": rel, "line": i,
                            "text": line.strip()[:150],
                            "source": "memory",
                        })
            except:
                pass

    if req.scope in ("all", "sessions"):
        for sid, msgs in _sys.modules['session'].sessions.items():
            for mi, msg in enumerate(msgs):
                content = (msg.get("content") or "").lower()
                if query in content:
                    results.append({
                        "file": f"session/{sid[:12]}",
                        "line": mi + 1,
                        "text": (msg.get("content") or "")[:150],
                        "source": "session",
                        "role": msg.get("role", ""),
                    })

    results = results[:100]
    return {"results": results, "count": len(results), "query": req.query}
