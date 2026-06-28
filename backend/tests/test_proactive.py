"""
单元测试 · proactive 触发器
============================
mock 时间/活跃信号/日程数据，验证各触发器边界条件。
"""
from __future__ import annotations

import time
import datetime
from unittest.mock import patch, MagicMock

import pytest


# ── MealTrigger ──────────────────────────────────

class TestMealTrigger:
    def test_outside_meal_window(self, freeze_datetime):
        """15:00 不在饭点窗口"""
        with freeze_datetime(2026, 6, 28, 15, 0, 0):
            from proactive import MealTrigger
            t = MealTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is None

    def test_breakfast_window(self, freeze_datetime):
        """7:30 在早餐窗口"""
        with freeze_datetime(2026, 6, 28, 7, 30, 0):
            from proactive import MealTrigger
            t = MealTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is not None
            assert "饭点" in result.message or "吃饭" in result.message

    def test_lunch_window(self, freeze_datetime):
        """12:00 在午餐窗口"""
        with freeze_datetime(2026, 6, 28, 12, 0, 0):
            from proactive import MealTrigger
            t = MealTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is not None

    def test_dinner_window(self, freeze_datetime):
        """18:00 在晚餐窗口"""
        with freeze_datetime(2026, 6, 28, 18, 0, 0):
            from proactive import MealTrigger
            t = MealTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is not None

    def test_window_edge_start(self, freeze_datetime):
        """7:00 早餐开始边界"""
        with freeze_datetime(2026, 6, 28, 7, 0, 0):
            from proactive import MealTrigger
            t = MealTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is not None

    def test_window_edge_end(self, freeze_datetime):
        """8:29 早餐结束边界内"""
        with freeze_datetime(2026, 6, 28, 8, 29, 0):
            from proactive import MealTrigger
            t = MealTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is not None

    def test_window_just_past(self, freeze_datetime):
        """8:31 刚过早餐窗口"""
        with freeze_datetime(2026, 6, 28, 8, 31, 0):
            from proactive import MealTrigger
            t = MealTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is None


# ── SilenceTrigger ───────────────────────────────

class TestSilenceTrigger:
    def test_recent_activity_skips(self):
        """1小时内有活跃 → 跳过"""
        with patch("proactive.get_last_chat_activity", return_value=time.time() - 3600):
            from proactive import SilenceTrigger
            t = SilenceTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is None

    def test_silence_3h_triggers(self):
        """刚好 3 小时 → 触发短消息（不带"一天"）"""
        with (
            patch("proactive.get_last_chat_activity", return_value=time.time() - 3 * 3600),
            patch("random.choice", return_value="你很久没说话了。"),
        ):
            from proactive import SilenceTrigger
            t = SilenceTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is not None
            assert "一天" not in result.message

    def test_deep_silence_8h_triggers(self):
        """10 小时 → 触发"一天没你消息" """
        with patch("proactive.get_last_chat_activity", return_value=time.time() - 10 * 3600):
            from proactive import SilenceTrigger
            t = SilenceTrigger()
            result = t.check({"last_sent": 0, "cooldowns": {}})
            assert result is not None
            assert "一天" in result.message


# ── LateNightTrigger ─────────────────────────────

class TestLateNightTrigger:
    def test_daytime_skips(self, freeze_datetime):
        """14:00 → 不触发"""
        with freeze_datetime(2026, 6, 28, 14, 0, 0):
            with patch("proactive.get_last_chat_activity", return_value=time.time() - 600):
                from proactive import LateNightTrigger
                t = LateNightTrigger()
                result = t.check({"last_sent": 0, "cooldowns": {}})
                assert result is None

    def test_late_night_no_recent_activity_skips(self, freeze_datetime):
        """凌晨 1 点，但 2 小时没活动 → 跳过"""
        with freeze_datetime(2026, 6, 29, 1, 0, 0):
            with patch("proactive.get_last_chat_activity", return_value=time.time() - 7200):
                from proactive import LateNightTrigger
                t = LateNightTrigger()
                result = t.check({"last_sent": 0, "cooldowns": {}})
                assert result is None

    def test_late_night_with_recent_activity(self, freeze_datetime):
        """凌晨 1 点，10 分钟前有活动 → 触发"""
        with freeze_datetime(2026, 6, 29, 1, 0, 0):
            with patch("proactive.get_last_chat_activity", return_value=time.time() - 600):
                from proactive import LateNightTrigger
                t = LateNightTrigger()
                result = t.check({"last_sent": 0, "cooldowns": {}})
                assert result is not None
                assert "睡" in result.message or "灯" in result.message

    def test_midnight_boundary(self, freeze_datetime):
        """0:00 应该触发（23-5 区间）"""
        with freeze_datetime(2026, 6, 29, 0, 0, 0):
            with patch("proactive.get_last_chat_activity", return_value=time.time() - 600):
                from proactive import LateNightTrigger
                t = LateNightTrigger()
                result = t.check({"last_sent": 0, "cooldowns": {}})
                assert result is not None

    def test_5am_boundary(self, freeze_datetime):
        """5:00 已过深夜区间"""
        with freeze_datetime(2026, 6, 29, 5, 0, 0):
            with patch("proactive.get_last_chat_activity", return_value=time.time() - 600):
                from proactive import LateNightTrigger
                t = LateNightTrigger()
                result = t.check({"last_sent": 0, "cooldowns": {}})
                assert result is None


# ── AnniversaryTrigger ───────────────────────────

def test_anniversary_30th_day_triggers():
    """第 30 天 → 触发包含 30 的消息。

    不 patch date.today（C 类型不可写），而是把 RELATIONSHIP_START
    设为 30 天前，使得 (today - RELATIONSHIP_START).days == 30。
    """
    from proactive import AnniversaryTrigger
    t = AnniversaryTrigger()
    thirty_days_ago = datetime.date.today() - datetime.timedelta(days=30)
    with patch("proactive.RELATIONSHIP_START", thirty_days_ago):
        result = t.check({"last_sent": 0, "cooldowns": {}})
        assert result is not None
        assert "30" in result.message


def test_anniversary_non_milestone_skips():
    """非里程碑 → 跳过"""
    from proactive import AnniversaryTrigger
    t = AnniversaryTrigger()
    # 16 天前 → today - 16 = day 16
    sixteen_days_ago = datetime.date.today() - datetime.timedelta(days=16)
    with patch("proactive.RELATIONSHIP_START", sixteen_days_ago):
        result = t.check({"last_sent": 0, "cooldowns": {}})
        assert result is None


def test_anniversary_oneyear_triggers():
    """一周年 → 触发周年消息"""
    from proactive import AnniversaryTrigger
    t = AnniversaryTrigger()
    one_year_ago = datetime.date.today() - datetime.timedelta(days=365)
    with patch("proactive.RELATIONSHIP_START", one_year_ago):
        result = t.check({"last_sent": 0, "cooldowns": {}})
        assert result is not None


# ── ScheduleTrigger ──────────────────────────────

class TestScheduleTrigger:
    @patch("proactive.get_upcoming", return_value=[])
    def test_no_urgent_events_skips(self, _):
        from proactive import ScheduleTrigger
        t = ScheduleTrigger()
        result = t.check({"last_sent": 0, "cooldowns": {}})
        assert result is None

    @patch("proactive.get_upcoming", return_value=[
        {"title": "考试", "_days_from_now": 3, "id": "1"},
    ])
    def test_event_3_days_away_skips(self, _):
        """>2 天前的日程不算 urgent"""
        from proactive import ScheduleTrigger
        t = ScheduleTrigger()
        result = t.check({"last_sent": 0, "cooldowns": {}})
        assert result is None

    @patch("proactive.get_upcoming", return_value=[
        {"title": "考试", "_days_from_now": 1, "id": "1"},
    ])
    def test_event_tomorrow_triggers(self, _):
        from proactive import ScheduleTrigger
        t = ScheduleTrigger()
        result = t.check({"last_sent": 0, "cooldowns": {}})
        assert result is not None
        assert "明天" in result.message

    @patch("proactive.get_upcoming", return_value=[
        {"title": "去医院复查", "_days_from_now": 2, "id": "1"},
    ])
    def test_event_day_after_tomorrow_triggers(self, _):
        from proactive import ScheduleTrigger
        t = ScheduleTrigger()
        result = t.check({"last_sent": 0, "cooldowns": {}})
        assert result is not None
        assert "后天" in result.message


# ── FallbackTrigger ──────────────────────────────

class TestFallbackTrigger:
    def test_recently_sent_skips(self):
        """刚发过（< cooldown）→ 跳过"""
        from proactive import FallbackTrigger
        t = FallbackTrigger()
        result = t.check({"last_sent": time.time() - 600, "cooldowns": {}})
        assert result is None

    def test_cooldown_passed_probability_low(self):
        """冷却已过但概率没命中 → 跳过"""
        from proactive import FallbackTrigger
        t = FallbackTrigger()
        with patch("random.random", return_value=0.9):
            result = t.check({"last_sent": time.time() - 7200 * 3, "cooldowns": {}})
            assert result is None

    def test_cooldown_passed_probability_hit(self):
        """冷却已过 + 概率命中 → 返回消息"""
        from proactive import FallbackTrigger
        t = FallbackTrigger()
        with patch("random.random", return_value=0.01):
            result = t.check({"last_sent": time.time() - 7200 * 3, "cooldowns": {}})
            assert result is not None
            assert result.message


# ── 冷却机制 ─────────────────────────────────────

class TestCooldown:
    def test_same_trigger_blocked_by_cooldown(self, freeze_datetime):
        """MealTrigger 本身不检查 cd——冷却在 check_proactive 层做，
        这里验证 trigger 在饭点总会触发（不管 state 里的 cooldown）。"""
        with freeze_datetime(2026, 6, 28, 12, 0, 0):
            from proactive import MealTrigger
            t = MealTrigger()
            # 即使 state 说有 1 分钟前触发了，trigger.check 仍会返回结果
            state = {"last_sent": 0, "cooldowns": {"meal": time.time() - 60}}
            result = t.check(state)
            assert result is not None  # trigger 层不拦
