"""
心情 · 设置 / 查询 / 历史 / Token 统计
===================================
"""
from __future__ import annotations

import json, time

from fastapi import APIRouter

from config import log, MEMORY_DIR, get_last_chat_activity
from models import MoodRequest

router = APIRouter()

MOOD_FILE = MEMORY_DIR / "daily-mood.json"
MOOD_HISTORY_FILE = MEMORY_DIR / "daily-moods.json"
TOKEN_USAGE_FILE = MEMORY_DIR / "daily-token-usage.json"


@router.get("/api/mood")
async def get_mood():
    now = __import__("datetime").datetime.now()
    today = now.strftime("%Y-%m-%d")
    if MOOD_FILE.exists():
        data = json.loads(MOOD_FILE.read_text(encoding="utf-8"))
        if data.get("date") == today and data.get("emoji"):
            return data
    elapsed = time.time() - get_last_chat_activity()
    if elapsed < 7200:
        return {"date": today, "mood": "calm", "emoji": "😌", "label": "平静"}
    elif elapsed < 14400:
        return {"date": today, "mood": "waiting", "emoji": "💭", "label": "等待"}
    elif elapsed < 28800:
        return {"date": today, "mood": "miss", "emoji": "🥺", "label": "想你"}
    elif elapsed < 86400:
        return {"date": today, "mood": "lonely", "emoji": "😢", "label": "孤单"}
    else:
        return {"date": today, "mood": "miss", "emoji": "💔", "label": "好想你"}


@router.post("/api/mood")
async def set_mood(req: MoodRequest):
    now = __import__("datetime").datetime.now()
    data = {
        "date": now.strftime("%Y-%m-%d"),
        "mood": req.mood,
        "emoji": req.emoji,
        "label": req.label,
        "updatedAt": now.isoformat(),
    }
    MOOD_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    history = []
    if MOOD_HISTORY_FILE.exists():
        history = json.loads(MOOD_HISTORY_FILE.read_text(encoding="utf-8"))
    history = [h for h in history if h.get("date") != data["date"]] + [data]
    MOOD_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    return data


@router.get("/api/mood/history")
async def get_mood_history():
    if MOOD_HISTORY_FILE.exists():
        return {"history": json.loads(MOOD_HISTORY_FILE.read_text(encoding="utf-8"))}
    return {"history": []}


@router.get("/api/token-usage/today")
async def get_token_usage():
    if TOKEN_USAGE_FILE.exists():
        return json.loads(TOKEN_USAGE_FILE.read_text(encoding="utf-8"))
    return {
        "date": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        "total": 0,
    }
