"""
砚迟 · FastAPI 后端入口
====================
"""
from __future__ import annotations

import base64, json, os, re

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

import config  # for mutable runtime state
from config import (
    log, MEMORY_DIR, SETTINGS_FILE, PROJECT_DIR, PORT,
    RELATIONSHIP_START, AVAILABLE_MODELS,
    get_current_model, set_current_model,
    _save_settings, _mask_key,
)
from models import ModelSwitchRequest, SettingsData, AvatarRequest

# ── 导入各模块路由 ──────────────────────────────────
from session import router as session_router, _load_sessions
from chat import router as chat_router
from memory import router as memory_router
from proactive import router as proactive_router
from mood import router as mood_router
from timeline import router as timeline_router
from books import router as books_router
from calendar_data import router as calendar_router
from au_data import router as au_router

# ── FastAPI 应用 ──────────────────────────────────
app = FastAPI(title="砚迟")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(proactive_router)
app.include_router(mood_router)
app.include_router(timeline_router)
app.include_router(books_router)
app.include_router(calendar_router)
app.include_router(au_router)


# ── PWA 静态资源 ──────────────────────────────────
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

@app.get("/icon-{size}.png")
async def app_icon(size: str):
    ICON_SIZES = {"192", "512"}
    if size not in ICON_SIZES:
        raise HTTPException(404)
    path = PROJECT_DIR / f"icon-{size}.png"
    if path.exists():
        return FileResponse(path, media_type="image/png")
    raise HTTPException(404)

@app.get("/")
async def index():
    html_path = PROJECT_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(
            html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    raise HTTPException(404)

# 健康检查
@app.get("/health")
async def health():
    return {"status": "ok", "provider": "deepseek", "model": get_current_model()}


# ── 模型切换 ──────────────────────────────────────
@app.get("/api/model")
async def get_model():
    return {"model": get_current_model(), "available": AVAILABLE_MODELS}

@app.post("/api/model")
async def set_model(req: ModelSwitchRequest):
    if req.model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"不支持的模型，可选: {', '.join(AVAILABLE_MODELS)}")
    set_current_model(req.model)
    log.info(f"  <- Model switched to: {get_current_model()}")
    return {"model": get_current_model()}


# ── 系统设置 ──────────────────────────────────────
@app.get("/api/settings")
async def get_settings():
    loc = ""
    thinking = None
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            loc = data.get("weather_location", "")
            thinking = data.get("thinking_mode", None)
        except Exception:
            pass
    return {
        "api_key": _mask_key(config.API_KEY),
        "base_url": config.BASE_URL,
        "model": get_current_model(),
        "qwen_api_key": _mask_key(config.QWEN_API_KEY),
        "qwen_base_url": config.QWEN_BASE_URL,
        "qwen_vl_model": config.QWEN_VL_MODEL,
        "weather_location": loc,
        "thinking_mode": thinking if thinking is not None else False,
        "available_models": ["deepseek-v4-flash", "deepseek-v4-pro", "claude-sonnet-4-6", "claude-haiku-4-5-20251001", "gpt-4o", "gpt-4o-mini"],
    }

@app.put("/api/settings")
async def save_settings(req: SettingsData):
    data = {k: v for k, v in req.dict(exclude_none=True).items()}
    saved = _save_settings(data)
    return {"saved": True, "api_key": _mask_key(saved.get("api_key", "")), "model": saved.get("model", "")}


# ── 头像存储 ──────────────────────────────────────
AVATAR_DIR = MEMORY_DIR / "avatars"

@app.post("/api/avatar/{avatar_type}")
async def set_avatar(avatar_type: str, req: AvatarRequest):
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
    if avatar_type not in ("ai", "user"):
        raise HTTPException(400, "avatar_type must be 'ai' or 'user'")
    for f in sorted(AVATAR_DIR.glob(f"avatar-{avatar_type}.*")):
        return FileResponse(f)
    raise HTTPException(404, "no avatar set")


# ── 首页「今天」模块 ────────────────────────────────
WEATHER_ZH = {
    "Sunny": "晴", "Clear": "晴",
    "Partly cloudy": "多云", "Cloudy": "阴",
    "Overcast": "阴天", "Rain": "雨",
    "Light rain": "小雨", "Heavy rain": "大雨",
    "Light drizzle": "小雨", "Patchy rain possible": "可能有雨",
    "Snow": "雪", "Light snow": "小雪", "Heavy snow": "大雪",
    "Fog": "雾", "Mist": "薄雾",
    "Smoky haze": "烟霾", "Haze": "霾",
    "Thunder": "雷阵雨", "Thundery outbreaks possible": "可能有雷阵雨",
    "Blizzard": "暴风雪", "Freezing fog": "冻雾",
    "Hail": "冰雹", "Sleet": "雨夹雪",
}

@app.get("/api/home")
async def get_home_data():
    now = __import__("datetime").datetime.now()
    today = now.date()
    days_together = (today - RELATIONSHIP_START).days
    today_str = today.strftime("%Y-%m-%d")

    from persona import _get_today_note
    note_text = _get_today_note(today_str)

    weather_desc = None
    weather_city = None
    try:
        loc = ""
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                loc = data.get("weather_location", "")
            except Exception:
                pass
        city = loc.strip()
        url = f"https://wttr.in/{__import__('urllib').parse.quote(city)}?format=j1&lang=zh" if city else "https://wttr.in/?format=j1&lang=zh"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            wdata = resp.json()
            cc = wdata.get("current_condition", [{}])[0]
            desc = cc.get("weatherDesc", [{}])[0].get("value", "")
            temp = cc.get("temp_C", "")
            # wttr.in 的 lang=zh 不一定稳定，取不到中文就用映射表兜底
            if desc:
                stripped = desc.strip()
                # 先试 lang_zh（有的话最可靠）
                zh = None
                if cc.get("lang_zh"):
                    zh = cc["lang_zh"][0].get("value", "").strip()
                if zh and any('一' <= c <= '鿿' for c in zh):
                    desc = zh
                elif stripped in WEATHER_ZH:
                    desc = WEATHER_ZH[stripped]
                else:
                    log.warning(f"  [weather] unknown description: {repr(desc)} (stripped: {repr(stripped)})")
                    desc = stripped
            weather_desc = f"{desc} {temp}°C" if desc else f"{temp}°C"
            if city:
                weather_city = city
            else:
                area = wdata.get("nearest_area", [{}])[0]
                region = area.get("region", [{}])[0].get("value", "")
                weather_city = region or None
    except Exception as e:
        log.warning(f"  [weather] fetch failed: {e}")

    return {
        "daysTogether": days_together,
        "startDate": "2026-06-12",
        "todayNote": note_text[:300] if note_text else None,
        "hasTodayNote": bool(note_text),
        "weather": weather_desc,
        "weatherCity": weather_city,
    }


# ── 入口 ──────────────────────────────────────────
_load_sessions()

if __name__ == "__main__":
    import uvicorn
    HOST = os.environ.get("YANCHI_HOST", "0.0.0.0")
    log.info(f"砚迟 FastAPI 后端 → http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
