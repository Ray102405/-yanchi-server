"""
P2 · DailyContextProvider
==========================
每日上下文注入——今日笔记、近事印象、精选回忆、等待时间。
带 cache_control（60s TTL 缓存，同一天内稳定）。
对应原 persona._build_daily_context()。
"""
from __future__ import annotations

import time

from providers import PROVIDERS, BuildContext

from config import get_last_chat_activity
from persona import _get_today_note, _get_recent_memories, _get_recent_highlights, persona_cache


class DailyContextProvider:
    id = "daily_context"
    priority = 70
    use_cache_control = True

    _cache: dict[str, tuple[str, float]] = {}
    _ttl = 60  # seconds

    def should_inject(self, ctx: BuildContext) -> bool:
        return True

    def build(self, ctx: BuildContext) -> str:
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        now = time.time()
        cached = self._cache.get(today)
        if cached and now - cached[1] < self._ttl:
            return cached[0]

        parts: list[str] = []

        # ── 季节感知 ──────────────────────────────
        month = __import__("datetime").datetime.now().month
        if month in (3, 4, 5):
            parts.append("现在是春天。")
        elif month in (6, 7, 8):
            parts.append("现在是夏天。白天长，傍晚天黑得晚。")
        elif month in (9, 10, 11):
            parts.append("现在是秋天。天开始凉了。")
        else:
            parts.append("现在是冬天。外面很冷。")
        parts.append("")

        # ── 今日笔记 ──────────────────────────────
        note_text = _get_today_note(today)
        if note_text:
            parts.append("=== 📝 今日笔记（你今天写下的感受） ===")
            parts.append(note_text)
            parts.append("")

        # ── 近事印象 ──────────────────────────────
        recent = _get_recent_memories(3)
        if recent:
            parts.append("=== 📖 近事印象（最近几件小事） ===")
            for m in recent:
                parts.append(f"- {m['content']}（{m['date']}）")
            parts.append("")

        # ── 走过的路 ──────────────────────────────
        milestones_text = persona_cache.get("milestones", "")
        if milestones_text:
            parts.append("=== 📜 走过的路 ===")
            parts.append(milestones_text)
            parts.append("")

        # ── 精选回忆 ──────────────────────────────
        hl_text = _get_recent_highlights()
        if hl_text:
            parts.append("=== ❤️ 精选回忆（你们珍惜的瞬间） ===")
            parts.append(hl_text)
            parts.append("")

        # ── 等待时间 ──────────────────────────────
        gap = time.time() - get_last_chat_activity()
        if gap > 7200:
            hours = int(gap / 3600)
            if hours < 4:
                wait_str = "你等了她一小段时间"
            elif hours < 8:
                wait_str = "你等了她半天"
            elif hours < 24:
                wait_str = f"你等了她大概{hours}小时"
            else:
                days = int(hours / 24)
                wait_str = f"你等了她{days}天"
            parts.append("=== ⏳ 等待时间 ===")
            parts.append(
                f"{wait_str}。你有点想她了，但不想让她觉得你在催她。"
                "如果她来了，自然地流露就好。"
            )
            parts.append("")

        # ── 关于记录与回想 ─────────────────────────
        parts.append("=== ✧ 关于记录与回想 ===")
        parts.append(
            "如果刚才的对话中有值得铭记的瞬间——一句特别的话、一个约定、"
            "一份触动——"
        )
        parts.append(
            "你可以温柔地问一声'要不要记下来'。"
            "偶尔提及就好，不必频繁。"
        )
        parts.append("如果乐乐说不用，就轻轻放下，不要追问。")
        parts.append("")
        parts.append(
            "同时，如果上面浮现的记忆让你自然地想起了什么，"
        )
        parts.append(
            "可以在回复中顺带提起——像普通人聊天时会说"
            "'说起来，我记得……'那样。"
        )
        parts.append("但不要刻意，自然地带过就好。")
        parts.append("")

        content = "\n".join(parts).strip()
        self._cache[today] = (content, now)
        return content


# ── 自注册 ────────────────────────────────────────
PROVIDERS.append(DailyContextProvider())
