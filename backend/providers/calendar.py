"""
CalendarProvider
==================
日程提醒注入——今日/近期事项 + 纪念日整数天提醒。
priority=60，和 daily_context 同属「按天稳定」层，带 cache_control。
"""
from __future__ import annotations

import time

from providers import PROVIDERS, BuildContext

from config import RELATIONSHIP_START
from calendar_data import get_upcoming, _load_all as _cal_load

# ── 纪念日里程碑：整 X 天触发 ─────────────────────
_MILESTONE_DAYS = {7, 14, 100, 500, 1000}

# 标题自动加动词：以这些字开头→已有动词，否则加"有"
_VERB_PREFIXES = {"要", "有", "去", "在", "交", "做", "写", "见",
                  "学", "上", "打", "吃", "买", "看", "拿", "到",
                  "回", "来", "开", "考", "面", "约"}


def _fmt_title(title: str) -> str:
    """为日程标题加自然动词前缀，避免「乐乐今天机器视觉考试」缺动词。"""
    if title and title[0] in _VERB_PREFIXES:
        return title
    return "有" + title


def _is_milestone(days: int) -> bool:
    """检查天数是否为里程碑（含整月、整年、特殊数字）。"""
    if days <= 0:
        return False
    return (
        days in _MILESTONE_DAYS
        or days % 30 == 0
        or days % 365 == 0
    )


def _milestone_text(days: int) -> str:
    if days % 365 == 0:
        years = days // 365
        if years == 1:
            return "今天是在一起的一周年。"
        return f"今天是在一起的{years}周年。"
    return f"今天是在一起的第{days}天。"


def _recurring_events_today() -> list[dict]:
    """检查今天是否命中某个 recurring 事件的月-日。"""
    today = __import__("datetime").date.today()
    results = []
    for e in _cal_load():
        if not e.get("recurring"):
            continue
        try:
            d = __import__("datetime").date.fromisoformat(e["date"])
        except (ValueError, TypeError):
            continue
        if d.month == today.month and d.day == today.day:
            results.append(e)
    return results


# ── Provider ──────────────────────────────────────
class CalendarProvider:
    id = "calendar"
    priority = 60
    use_cache_control = True

    _cache: dict[str, tuple[str, float]] = {}
    _ttl = 60  # seconds, 与 daily_context 一致

    def should_inject(self, ctx: BuildContext) -> bool:
        upcoming = get_upcoming(7)
        if upcoming:
            return True
        # 纪念日
        today = __import__("datetime").date.today()
        days = (today - RELATIONSHIP_START).days
        if _is_milestone(days):
            return True
        # 周期性事件
        if _recurring_events_today():
            return True
        return False

    def build(self, ctx: BuildContext) -> str:
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        now = time.time()
        cached = self._cache.get(today)
        if cached and now - cached[1] < self._ttl:
            return cached[0]

        parts: list[str] = []

        # ── 近期日程 ──────────────────────────────
        upcoming = get_upcoming(7)
        recurring_today = _recurring_events_today()
        if upcoming or recurring_today:
            parts.append("=== 📅 日程提醒 ===")

            for e in sorted(upcoming, key=lambda x: x.get("_days_from_now", 0)):
                days_from = e.get("_days_from_now", 0)
                msg = _fmt_title(e["title"])
                if days_from == 0:
                    parts.append(f"乐乐今天{msg}。")
                elif days_from == 1:
                    parts.append(f"乐乐明天{msg}。")
                else:
                    parts.append(f"乐乐{days_from}天后{msg}。")

            for e in recurring_today:
                parts.append(f"乐乐今天{_fmt_title(e['title'])}。")

            parts.append("")

        # ── 纪念日里程碑 ──────────────────────────
        today_date = __import__("datetime").date.today()
        days = (today_date - RELATIONSHIP_START).days
        if _is_milestone(days):
            # 如果前面已有日程提醒，共用 header，否则加 header
            if not parts:
                parts.append("=== 📅 日程提醒 ===")
            parts.append(_milestone_text(days))
            parts.append("")

        content = "\n".join(parts).strip()
        self._cache[today] = (content, now)
        return content


# ── 自注册 ────────────────────────────────────────
PROVIDERS.append(CalendarProvider())
