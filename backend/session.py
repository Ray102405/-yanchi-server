"""
会话管理 · Session CRUD
===================
内存 + 磁盘持久化的对话 session 管理。
"""
from __future__ import annotations

import json
import threading

from fastapi import APIRouter, HTTPException
from config import MEMORY_DIR, log
from models import SessionRestoreRequest

# ── Session 存储 ─────────────────────────────────
sessions: dict[str, list[dict]] = {}
MAX_SESSION_MSGS = 40        # ≈ 20 轮对话
PREFIX_KEEP = 6              # 固定保留前 3 轮（6 条消息），保护 KV-cache 前缀
SUFFIX_KEEP = 10             # 保留最近 5 轮（10 条消息）作为即时上下文
SESSION_FILE = MEMORY_DIR / "sessions.json"
_session_dirty = False
_save_lock = threading.Lock()  # 写锁：保护 json.dumps + 写盘 的原子性

router = APIRouter()

# ── 内部函数 ─────────────────────────────────────

def _load_sessions():
    """从磁盘加载持久化的 session 数据。"""
    global sessions
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            sessions.clear()
            sessions.update(data)
            log.info(f"  [OK] Restored {len(sessions)} sessions from disk")
            for sid in sessions:
                sessions[sid] = truncate_messages(sessions[sid])
        except Exception as e:
            log.warning(f"  [FAIL] Failed to load sessions: {e}")

def _save_sessions():
    """将 session 数据持久化到磁盘（写锁保护）。"""
    global _session_dirty
    with _save_lock:
        try:
            SESSION_FILE.write_text(
                json.dumps(sessions, ensure_ascii=False, indent=1),
                encoding="utf-8"
            )
            _session_dirty = False
        except Exception as e:
            log.warning(f"  [FAIL] Failed to save sessions: {e}")

def _mark_dirty():
    """标记 session 为脏，触发延迟保存。"""
    global _session_dirty
    if not _session_dirty:
        _session_dirty = True
        _save_sessions()

def get_session(sid: str) -> list[dict]:
    if sid not in sessions:
        sessions[sid] = []
        _mark_dirty()
    return sessions[sid]

def truncate_messages(history: list[dict]) -> list[dict]:
    """智能截断 + 关键信息提取。

    策略：
    1. 固定保留前 PREFIX_KEEP 条（KV-cache 前缀保护）
    2. 保留最近 SUFFIX_KEEP 条（即时上下文）
    3. 中间部分提取用户的关键问题/话题，丢弃冗余的助理回复
    """
    if len(history) <= MAX_SESSION_MSGS:
        return history

    prefix = history[:PREFIX_KEEP]
    suffix = history[-SUFFIX_KEEP:]
    middle = history[PREFIX_KEEP:-SUFFIX_KEEP]

    # 从中间部分提取关键内容：保留用户消息 + 包含重要关键词的助理回复
    _KEYWORDS = {"记得", "承诺", "约定", "喜欢", "爱", "重要",
                 "想", "要", "答应", "好", "嗯", "不要", "别"}

    extracted: list[dict] = []
    for msg in middle:
        content = (msg.get("content") or "").strip()
        if msg.get("role") == "user":
            if content:
                extracted.append(msg)
        else:
            if any(kw in content for kw in _KEYWORDS):
                compressed = content[:200]
                extracted.append({"role": "assistant", "content": compressed})

    # 提取的内容也设上限，只保留最近的 N 条关键信息
    MAX_EXTRACTED = 12
    if len(extracted) > MAX_EXTRACTED:
        extracted = extracted[-MAX_EXTRACTED:]

    return prefix + extracted + suffix


# ── 路由 ─────────────────────────────────────────

@router.post("/session/restore")
async def session_restore(req: SessionRestoreRequest):
    session = get_session(req.session_id)
    if not session:
        session.extend(req.history)
        _mark_dirty()
        log.info(f"  <- Session restored: {req.session_id[:12]} ({len(req.history)} msgs)")
        return {"restored": True, "count": len(req.history)}
    return {"restored": False, "reason": "session already exists"}

@router.get("/sessions")
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

@router.get("/session/{session_id}")
async def get_session_by_id(session_id: str):
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    return {"id": session_id, "history": session}

@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        _mark_dirty()
        log.info(f"  <- Session deleted: {session_id[:12]}")
        return {"deleted": True}
    return {"deleted": False}
