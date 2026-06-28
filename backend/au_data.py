"""
AU（平行宇宙）数据层 + API 路由
==============================
CRUD + 激活/删除，供 providers/au.py 和前端 API 共同使用。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from config import MEMORY_DIR, log
from models import AUCreateRequest

router = APIRouter()
AU_FILE = MEMORY_DIR / "au-settings.json"

DEFAULT_AU = {
    "id": "default",
    "name": "现代日常",
    "active": True,
    "background": "",
    "persona_override": "",
    "tone_shift": "",
}


# ── 数据 CRUD ──────────────────────────────────────


def _load_all() -> list[dict]:
    if AU_FILE.exists():
        try:
            return json.loads(AU_FILE.read_text("utf-8"))
        except Exception as e:
            log.warning(f"  [au] load error: {e}")
    # 首次创建，写入 default
    _save_all([dict(DEFAULT_AU)])
    return [dict(DEFAULT_AU)]


def _save_all(data: list[dict]):
    AU_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _ensure_default(data: list[dict]) -> list[dict]:
    """确保 default AU 存在且排在第一"""
    if not any(a["id"] == "default" for a in data):
        data.insert(0, dict(DEFAULT_AU))
    return data


def get_all() -> list[dict]:
    data = _load_all()
    return _ensure_default(data)


def get_active() -> dict | None:
    """返回当前激活的非 default AU，没有则返回 None"""
    for au in get_all():
        if au.get("active") and au["id"] != "default":
            return au
    return None


def activate(au_id: str) -> dict:
    """激活指定 AU，关闭其他所有"""
    data = _load_all()
    found = None
    for au in data:
        if au["id"] == au_id:
            au["active"] = True
            found = au
        else:
            au["active"] = False
    if not found:
        raise ValueError(f"AU '{au_id}' not found")
    _ensure_default(data)
    _save_all(data)
    return found


def add_au(
    name: str,
    background: str = "",
    persona_override: str = "",
    tone_shift: str = "",
) -> dict:
    data = _load_all()
    au_id = "au_" + uuid.uuid4().hex[:8]
    entry = {
        "id": au_id,
        "name": name,
        "active": False,
        "background": background,
        "persona_override": persona_override,
        "tone_shift": tone_shift,
    }
    data.append(entry)
    _save_all(data)
    return entry


def delete_au(au_id: str) -> bool:
    if au_id == "default":
        return False
    data = _load_all()
    new_data = [a for a in data if a["id"] != au_id]
    if len(new_data) == len(data):
        return False
    _ensure_default(new_data)
    _save_all(new_data)
    return True


# ── API 路由 ───────────────────────────────────────


@router.get("/api/au")
async def list_au():
    return {"aus": get_all()}


@router.post("/api/au")
async def create_au(req: AUCreateRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "AU 名称不能为空")
    au = add_au(
        name=name,
        background=(req.background or "").strip(),
        persona_override=(req.persona_override or "").strip(),
        tone_shift=(req.tone_shift or "").strip(),
    )
    return au


@router.put("/api/au/{au_id}/activate")
async def activate_au(au_id: str):
    try:
        return activate(au_id)
    except ValueError:
        raise HTTPException(404, f"AU '{au_id}' 不存在")


@router.delete("/api/au/{au_id}")
async def delete_au_endpoint(au_id: str):
    ok = delete_au(au_id)
    if not ok:
        raise HTTPException(400, "default AU 不可删除")
    return {"ok": True}
