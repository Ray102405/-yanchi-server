"""
配置 · 路径 / API / 设置管理
=======================
所有模块从这里导入配置和共享运行时状态。
"""
from __future__ import annotations

import os, json, logging, time
from pathlib import Path
from typing import Optional

# ── 日志 ──────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("yanchi")

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
PENDING_MEMORY_FILE = MEMORY_DIR / "yanchi-pending-memories.json"

# Claude 记忆目录（用户可能在 Claude Code 里写今日笔记）
_CLAUDE_MEMORY_DIR = HOME / ".claude/projects/C--Users-Ray/memory/yanchi"

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

# ── 运行时设置（用户通过 UI 修改，存 settings.json）─────
SETTINGS_FILE = MEMORY_DIR / "settings.json"
SETTINGS_KEYS = {
    "api_key": API_KEY,
    "base_url": BASE_URL,
    "model": _MODEL_DEFAULT,
    "qwen_api_key": QWEN_API_KEY,
    "qwen_base_url": QWEN_BASE_URL,
    "qwen_vl_model": QWEN_VL_MODEL,
    "weather_location": "",
    "thinking_mode": False,
}

# ── 共享运行时状态 ─────────────────────────────────
_last_activity_file = MEMORY_DIR / "last-activity.json"

def _load_last_activity() -> float:
    """从磁盘恢复上次活跃时间"""
    try:
        if _last_activity_file.exists():
            return json.loads(_last_activity_file.read_text("utf-8"))
    except Exception:
        pass
    return 0.0

def _save_last_activity(val: float) -> None:
    try:
        _last_activity_file.write_text(json.dumps(val), "utf-8")
    except Exception:
        pass

_last_chat_activity: float = _load_last_activity()  # 最近一次聊天时间

def get_last_chat_activity() -> float:
    return _last_chat_activity

def set_last_chat_activity(val: float) -> None:
    global _last_chat_activity
    _last_chat_activity = val
    _save_last_activity(val)

def get_current_model() -> str:
    return _current_model

def set_current_model(model: str) -> None:
    global _current_model
    _current_model = model

# ── 特性开关 ────────────────────────────────────
USE_PROVIDER_SYSTEM: bool = True  # True = 用 providers/ 模块注入；False = 回退旧函数

# ── 关系时间线 ──────────────────────────────────
RELATIONSHIP_START = __import__("datetime").date(2026, 6, 12)

# ── 设置管理函数 ────────────────────────────────

def _load_settings():
    """从磁盘加载用户设置，覆盖启动配置。"""
    global API_KEY, BASE_URL, API_URL, _current_model, _MODEL_DEFAULT
    global QWEN_API_KEY, QWEN_BASE_URL, QWEN_VL_MODEL
    if not SETTINGS_FILE.exists():
        return
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if data.get("api_key"): API_KEY = data["api_key"]; _MODEL_DEFAULT = data.get("model", _MODEL_DEFAULT); _current_model = _MODEL_DEFAULT
        if data.get("base_url"): BASE_URL = data["base_url"]; API_URL = f"{BASE_URL}/messages"
        if data.get("qwen_api_key"): QWEN_API_KEY = data["qwen_api_key"]
        if data.get("qwen_base_url"): QWEN_BASE_URL = data["qwen_base_url"]
        if data.get("qwen_vl_model"): QWEN_VL_MODEL = data["qwen_vl_model"]
        log.info("  [OK] Loaded user settings from settings.json")
    except Exception as e:
        log.warning(f"  [FAIL] settings.json: {e}")

def _save_settings(data: dict) -> dict:
    """保存用户设置到磁盘并即时生效（合并模式，不覆写未涉及的字段）。"""
    global API_KEY, BASE_URL, API_URL, _current_model
    global QWEN_API_KEY, QWEN_BASE_URL, QWEN_VL_MODEL
    existing = {}
    if SETTINGS_FILE.exists():
        try:
            existing = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    for k, v in data.items():
        if k in ("api_key", "qwen_api_key") and not v:
            continue
        existing[k] = v
    safe = {k: existing.get(k, SETTINGS_KEYS[k]) for k in SETTINGS_KEYS}
    if safe.get("api_key"): API_KEY = safe["api_key"]
    if safe.get("base_url"): BASE_URL = safe["base_url"]; API_URL = f"{BASE_URL}/messages"
    if safe.get("model"): _current_model = safe["model"]
    if safe.get("qwen_api_key"): QWEN_API_KEY = safe["qwen_api_key"]
    if safe.get("qwen_base_url"): QWEN_BASE_URL = safe["qwen_base_url"]
    if safe.get("qwen_vl_model"): QWEN_VL_MODEL = safe["qwen_vl_model"]
    SETTINGS_FILE.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("  <- Settings saved")
    return safe

def _mask_key(key: str) -> str:
    """脱敏显示密钥：只留前8位"""
    if not key or len(key) < 12:
        return ""
    return key[:8] + "..." + key[-4:]

# 启动时加载用户配置
_load_settings()
