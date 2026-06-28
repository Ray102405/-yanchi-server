"""
日历 · 日程管理
============
数据层（calendar.json CRUD）+ API 路由。
"""
from __future__ import annotations

import json, time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import log, MEMORY_DIR


# ── 数据文件 ──────────────────────────────────────
CALENDAR_FILE = MEMORY_DIR / "calendar.json"


# ── 数据层 ────────────────────────────────────────
def _load_all() -> list[dict]:
    if not CALENDAR_FILE.exists():
        return []
    try:
        return json.loads(CALENDAR_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def _save_all(entries: list[dict]):
    CALENDAR_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def _generate_id() -> str:
    return f"cal_{int(time.time() * 1000)}"

def get_all() -> list[dict]:
    return _load_all()

def add(title: str, date: str, type_: str = "custom",
        recurring: bool = False, note: str = "") -> dict:
    entries = _load_all()
    entry = {
        "id": _generate_id(),
        "title": title,
        "date": date,
        "type": type_,
        "recurring": recurring,
        "note": note,
    }
    entries.append(entry)
    _save_all(entries)
    log.info(f"  <- Calendar added: {title} @ {date}")
    return entry

def delete(entry_id: str) -> bool:
    entries = _load_all()
    before = len(entries)
    entries = [e for e in entries if e["id"] != entry_id]
    if len(entries) == before:
        return False
    _save_all(entries)
    log.info(f"  <- Calendar deleted: {entry_id}")
    return True

def get_upcoming(days: int = 7) -> list[dict]:
    """返回未来 N 天内的日程（含今天）。"""
    today = __import__("datetime").date.today()
    entries = _load_all()
    results = []
    for e in entries:
        try:
            d = __import__("datetime").date.fromisoformat(e["date"])
        except (ValueError, TypeError):
            continue
        diff = (d - today).days
        if 0 <= diff < days:
            results.append({**e, "_days_from_now": diff})
    results.sort(key=lambda x: x["_days_from_now"])
    return results


# ── 请求模型 ──────────────────────────────────────
class CalendarCreateRequest(BaseModel):
    title: str
    date: str  # ISO date
    type: str = "custom"
    recurring: bool = False
    note: str = ""


# ── 路由 ──────────────────────────────────────────
router = APIRouter()


@router.get("/api/calendar")
async def list_calendar():
    return {"entries": get_all(), "count": len(get_all())}


@router.post("/api/calendar")
async def create_calendar(req: CalendarCreateRequest):
    if not req.title.strip():
        raise HTTPException(400, "title is required")
    try:
        __import__("datetime").date.fromisoformat(req.date)
    except (ValueError, TypeError):
        raise HTTPException(400, "date must be ISO format (YYYY-MM-DD)")
    entry = add(req.title, req.date, req.type, req.recurring, req.note)
    return entry


@router.delete("/api/calendar/{entry_id}")
async def delete_calendar(entry_id: str):
    if not delete(entry_id):
        raise HTTPException(404, "entry not found")
    return {"deleted": True}


@router.get("/api/calendar/upcoming")
async def upcoming_calendar(days: int = 7):
    return {"entries": get_upcoming(days), "count": len(get_upcoming(days))}
