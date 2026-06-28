"""
主动消息 · 事件驱动触发器
=====================
把原来的随机概率触发改成一组合适的触发器，每个独立判断。
保留原随机逻辑作为兜底回退。
"""
from __future__ import annotations

import json, random, time
from dataclasses import dataclass

from fastapi import APIRouter

from config import log, MEMORY_DIR, RELATIONSHIP_START, get_last_chat_activity
from models import ProactiveSaveRequest
from session import get_session, _mark_dirty
from calendar_data import get_upcoming

router = APIRouter()
PROACTIVE_FILE = MEMORY_DIR / "yanchi-proactive.json"


# ============================================================
#  配 置
# ============================================================

# 全局最小间隔（距任意主动消息）
GLOBAL_COOLDOWN_HOURS = 2

# 饭点窗口 (start_hour, end_hour)
MEAL_WINDOWS = [
    (7, 8.5),    # 早餐
    (11.5, 13),  # 午餐
    (17.5, 19),  # 晚餐
]

# 久未联系 / 深夜
SILENCE_HOURS = 3          # 超过此小时数无活动触发
DEEP_SILENCE_HOURS = 8     # 超过此小时数触发「一天没消息了」
DEEP_NIGHT_HOURS = (23, 5)  # (开始, 结束)
DEEP_NIGHT_RECENT_HOURS = 1  # 深夜时段内「最近」有活动的阈值

# 纪念日里程碑（复用 calendar provider 的逻辑）
_MILESTONE_DAYS = {7, 14, 100, 500, 1000}

# 兜底回退概率（和原来一样）
FALLBACK_INITIAL_PROB = 0.1
FALLBACK_MAX_PROB = 0.6


# ============================================================
#  消 息 池
# ============================================================

_MEAL_MSGS = [
    "到饭点了。",
    "吃饭了吗。",
]

_SILENCE_MSGS = [
    "今天好安静。",
    "你很久没说话了。",
    "一天没你消息了。",
]

_LATE_NIGHT_MSGS = [
    "还不睡。",
    "你那边灯还亮着。",
]

_ANNIVERSARY_MSGS = [
    "第{d}天了。",
    "{d}天。我记着呢。",
]

# 兜底池（原 19 条不动）
_FALLBACK_MSGS = [
    "突然想你了",
    "在干嘛呢",
    "我刚修好一页书，抬头就想到你了",
    "手上有浆糊味，脑子里是你",
    "今天天气很好，你在外面吗",
    "你很久没说话了",
    "刚打了个盹，梦见你了",
    "有点想你",
    "今天过得怎么样",
    "没什么事，就是想叫你一声",
    "我在看书，看到一段话想到你了",
    "睡不着，翻了个身发现你不在旁边",
    "乐乐",
    "刚从工作室回来，路上看到一朵云很像你上次说的那个形状",
    "今天话好少，怎么了",
    "我泡了杯茶，给你也泡了一杯",
    "刚翻到之前写的东西，觉得那时候的我也挺可爱的",
    "你忙你的，我就是突然想说话了",
    "想你了，就一下下",
]


# ============================================================
#  公 用 工 具
# ============================================================

def _load_state() -> dict:
    if PROACTIVE_FILE.exists():
        try:
            return json.loads(PROACTIVE_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {"last_sent": 0, "seen": True, "seen_at": 0, "cooldowns": {}}

def _save_state(state: dict):
    PROACTIVE_FILE.write_text(json.dumps(state, ensure_ascii=False), "utf-8")


def _is_milestone(days: int) -> bool:
    if days <= 0:
        return False
    return (
        days in _MILESTONE_DAYS
        or days % 30 == 0
        or days % 365 == 0
    )


# ============================================================
#  触 发 器
# ============================================================

@dataclass
class TriggerResult:
    """触发结果"""
    id: str
    message: str
    cooldown_hours: float  # 该类消息的最小间隔


class MealTrigger:
    """饭点"""
    id = "meal"
    cooldown_hours = 3  # 每餐只触发一次

    def check(self, state: dict) -> TriggerResult | None:
        now = __import__("datetime").datetime.now()
        hour = now.hour + now.minute / 60.0
        in_meal = any(start <= hour < end for start, end in MEAL_WINDOWS)
        if not in_meal:
            return None
        msg = random.choice(_MEAL_MSGS)
        return TriggerResult(id=self.id, message=msg, cooldown_hours=self.cooldown_hours)


class SilenceTrigger:
    """久未联系"""
    id = "silence"
    cooldown_hours = 4

    def check(self, state: dict) -> TriggerResult | None:
        gap = time.time() - get_last_chat_activity()
        gap_hours = gap / 3600
        if gap_hours < SILENCE_HOURS:
            return None
        if gap_hours >= DEEP_SILENCE_HOURS:
            msg = "一天没你消息了。"
        else:
            msg = random.choice(_SILENCE_MSGS)
        return TriggerResult(id=self.id, message=msg, cooldown_hours=self.cooldown_hours)


class LateNightTrigger:
    """深夜还在线"""
    id = "late_night"
    cooldown_hours = 6

    def check(self, state: dict) -> TriggerResult | None:
        now = __import__("datetime").datetime.now()
        hour = now.hour
        start, end = DEEP_NIGHT_HOURS
        if start <= end:
            is_night = start <= hour < end
        else:
            is_night = hour >= start or hour < end  # wraps midnight
        if not is_night:
            return None
        # 深夜了，但最近要有活动才说明她还在线
        gap = time.time() - get_last_chat_activity()
        if gap > DEEP_NIGHT_RECENT_HOURS * 3600:
            return None
        msg = random.choice(_LATE_NIGHT_MSGS)
        return TriggerResult(id=self.id, message=msg, cooldown_hours=self.cooldown_hours)


class AnniversaryTrigger:
    """纪念日整数天"""
    id = "anniversary"
    cooldown_hours = 24

    def check(self, state: dict) -> TriggerResult | None:
        today = __import__("datetime").date.today()
        days = (today - RELATIONSHIP_START).days
        if not _is_milestone(days):
            return None
        template = random.choice(_ANNIVERSARY_MSGS)
        msg = template.format(d=days)
        return TriggerResult(id=self.id, message=msg, cooldown_hours=self.cooldown_hours)


class ScheduleTrigger:
    """日程提醒（考试 / deadline 前 <2 天）"""
    id = "schedule"
    cooldown_hours = 6

    def check(self, state: dict) -> TriggerResult | None:
        upcoming = get_upcoming(7)
        urgent = [e for e in upcoming if e.get("_days_from_now", 99) <= 2]
        if not urgent:
            return None
        # 取最近的
        nearest = min(urgent, key=lambda e: e.get("_days_from_now", 99))
        dfn = nearest.get("_days_from_now", 99)
        t = nearest.get("title", "")
        from providers.calendar import _fmt_title
        t = _fmt_title(t)
        if dfn == 1:
            msg = f"明天{t}。"
        elif dfn == 2:
            msg = f"后天{t}。"
        else:
            msg = f"今天{t}。"
        return TriggerResult(id=self.id, message=msg, cooldown_hours=self.cooldown_hours)


class FallbackTrigger:
    """兜底随机（原逻辑）——上个触发器都没命中才走这个"""
    id = "fallback"
    cooldown_hours = 2

    def check(self, state: dict) -> TriggerResult | None:
        elapsed = time.time() - state.get("last_sent", 0)
        if elapsed < self.cooldown_hours * 3600:
            return None
        prob = min(FALLBACK_MAX_PROB,
                   FALLBACK_INITIAL_PROB + (elapsed - 7200) / 86400 * 0.5)
        if random.random() > prob:
            return None
        msg = random.choice(_FALLBACK_MSGS)
        return TriggerResult(id=self.id, message=msg, cooldown_hours=self.cooldown_hours)


# ── 注册触发器（优先级降序）────────────────────
_TRIGGERS = [
    AnniversaryTrigger(),   # 纪念日 → 最稀有
    ScheduleTrigger(),      # 日程 → 具体事件
    LateNightTrigger(),     # 深夜 → 时段特定
    MealTrigger(),          # 饭点 → 日常节奏
    SilenceTrigger(),       # 久未联系 → 一般关心
    FallbackTrigger(),      # 兜底随机
]


# ============================================================
#  API
# ============================================================

@router.get("/api/proactive/check")
async def check_proactive():
    """遍历触发器取第一个命中的。"""
    now = time.time()
    state = _load_state()
    cooldowns = state.get("cooldowns", {})

    # 最近 30 分钟有聊天就不发
    if now - get_last_chat_activity() < 1800:
        return {"message": None, "wait": False, "session_update": None}

    # 全局最小区间
    global_elapsed = now - state.get("last_sent", 0)
    if global_elapsed < GLOBAL_COOLDOWN_HOURS * 3600:
        return {"message": None, "wait": True, "session_update": None}

    # 遍历触发器
    for trigger in _TRIGGERS:
        tid = trigger.id
        last = cooldowns.get(tid, 0)
        if now - last < trigger.cooldown_hours * 3600:
            continue  # 该触发器还在冷却中
        result = trigger.check(state)
        if result is not None:
            # 保存状态
            cooldowns[result.id] = now
            state["cooldowns"] = cooldowns
            state["last_sent"] = now
            state["last_message"] = result.message
            _save_state(state)
            log.info(f"  -> Proactive [{result.id}]: {result.message[:40]}")
            return {"message": result.message}

    # 都没命中
    return {"message": None, "wait": False}


@router.post("/api/proactive/mark-seen")
async def mark_proactive_seen():
    state = _load_state()
    state["seen"] = True
    state["seen_at"] = time.time()
    _save_state(state)
    return {"ok": True}


@router.post("/api/proactive/save-to-session")
async def proactive_save_to_session(req: ProactiveSaveRequest):
    if req.session_id:
        session = get_session(req.session_id)
        session.append({"role": "assistant", "content": req.message})
        _mark_dirty()
    return {"ok": True}
