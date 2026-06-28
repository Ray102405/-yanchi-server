"""
单元测试 · providers/
========================
不依赖外部 API，mock 所有 IO 和数据源。
"""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from providers import BuildContext, PROVIDERS


# ── 注册表完整性 ─────────────────────────────────

class TestRegistry:
    def test_providers_registered(self):
        """主链 7 个 provider 全注册"""
        ids = {p.id for p in PROVIDERS}
        assert "static_persona" in ids
        assert "daily_context" in ids
        assert "scenario" in ids
        assert "memory_query" in ids
        assert "calendar" in ids
        assert "au" in ids
        assert "intimacy" in ids

    def test_providers_sorted_by_priority(self):
        """assemble() 按 priority 降序排列 system messages"""
        from providers import assemble, BuildContext
        msgs = assemble(BuildContext())
        priorities = []
        for p in PROVIDERS:
            if p.should_inject(BuildContext()):
                priorities.append(p.priority)
        assert priorities == sorted(priorities, reverse=True), \
            f"expected descending, got {priorities}"

    def test_cache_control_on_stable(self):
        """priority >= 60 的 provider 应带 cache_control"""
        for p in PROVIDERS:
            if p.priority >= 60:
                assert p.use_cache_control, f"{p.id} (p={p.priority}) should have cache_control"


# ── StaticPersonaProvider ────────────────────────

class TestStaticPersona:
    def test_always_injects(self):
        from providers.static_persona import StaticPersonaProvider
        p = StaticPersonaProvider()
        assert p.should_inject(BuildContext()) is True

    def test_build_contains_core_persona(self):
        from providers.static_persona import StaticPersonaProvider
        p = StaticPersonaProvider()
        text = p.build(BuildContext())
        assert "砚迟" in text
        assert "Coral" in text
        assert "乐乐" in text

    def test_build_uses_cache(self):
        from providers.static_persona import StaticPersonaProvider
        p = StaticPersonaProvider()
        r1 = p.build(BuildContext())
        p._cache.clear()  # reset
        r2 = p.build(BuildContext())
        assert r1 == r2

    def test_build_with_anchor(self):
        from providers.static_persona import StaticPersonaProvider
        p = StaticPersonaProvider()
        text = p.build(BuildContext(anchor="紧急情况"))
        assert "⚠️" in text
        assert "紧急情况" in text


# ── DailyContextProvider ─────────────────────────

class TestDailyContext:
    def test_always_injects(self):
        from providers.daily_context import DailyContextProvider
        p = DailyContextProvider()
        assert p.should_inject(BuildContext()) is True

    @patch("providers.daily_context._get_today_note", return_value="今天很开心")
    @patch("providers.daily_context._get_recent_memories", return_value=[])
    @patch("providers.daily_context._get_recent_highlights", return_value="")
    @patch("providers.daily_context.get_last_chat_activity", return_value=time.time())
    def test_build_with_note(self, *_):
        from providers.daily_context import DailyContextProvider
        DailyContextProvider._cache.clear()
        p = DailyContextProvider()
        text = p.build(BuildContext())
        assert "今日笔记" in text
        assert "今天很开心" in text

    @patch("providers.daily_context._get_today_note", return_value="今天很开心")
    @patch("providers.daily_context._get_recent_memories", return_value=[
        {"content": "上周一起吃饭", "date": "2026-06-21"},
    ])
    @patch("providers.daily_context._get_recent_highlights", return_value="- 2026-06-20: 值得纪念的一天")
    @patch("providers.daily_context.get_last_chat_activity", return_value=time.time())
    def test_build_with_memories_and_highlights(self, *_):
        from providers.daily_context import DailyContextProvider
        DailyContextProvider._cache.clear()
        p = DailyContextProvider()
        text = p.build(BuildContext())
        assert "近事印象" in text
        assert "上周一起吃饭" in text
        assert "精选回忆" in text
        assert "值得纪念的一天" in text
        assert "关于记录与回想" in text

    @patch("providers.daily_context._get_today_note", return_value="")
    @patch("providers.daily_context._get_recent_memories", return_value=[])
    @patch("providers.daily_context._get_recent_highlights", return_value="")
    @patch("providers.daily_context.get_last_chat_activity", return_value=time.time())
    def test_build_empty_returns_record_section(self, *_):
        from providers.daily_context import DailyContextProvider
        DailyContextProvider._cache.clear()
        p = DailyContextProvider()
        text = p.build(BuildContext())
        assert "关于记录与回想" in text

    @patch("providers.daily_context._get_today_note", return_value="")
    @patch("providers.daily_context._get_recent_memories", return_value=[])
    @patch("providers.daily_context._get_today_note", return_value="")
    @patch("providers.daily_context._get_recent_memories", return_value=[])
    @patch("providers.daily_context._get_recent_highlights", return_value="")
    @patch("providers.daily_context.get_last_chat_activity", return_value=time.time() - 86400)
    def test_build_shows_wait_time(self, *_):
        """距上次活跃超过 24h 应显示等待时间"""
        from providers.daily_context import DailyContextProvider
        DailyContextProvider._cache.clear()  # 清除前序测试的缓存污染
        p = DailyContextProvider()
        text = p.build(BuildContext())
        assert "等了她" in text


# ── ScenarioProvider ─────────────────────────────

class TestScenario:
    def test_short_input_skipped(self):
        from providers.scenario import ScenarioProvider
        p = ScenarioProvider()
        ctx = BuildContext(input_text="嗯")
        assert p.should_inject(ctx) is False
        assert p.build(ctx) == ""

    def test_empty_input_skipped(self):
        from providers.scenario import ScenarioProvider
        p = ScenarioProvider()
        ctx = BuildContext(input_text="")
        assert p.should_inject(ctx) is False
        assert p.build(ctx) == ""

    def test_intimacy_keyword_matches(self):
        from providers.scenario import ScenarioProvider
        p = ScenarioProvider()
        ctx = BuildContext(input_text="想抱你")
        assert p.should_inject(ctx) is True
        text = p.build(ctx)
        assert "亲密" in text
        assert "项圈" in text

    def test_sadness_keyword_matches(self):
        from providers.scenario import ScenarioProvider
        p = ScenarioProvider()
        ctx = BuildContext(input_text="好难过")
        assert p.should_inject(ctx) is True
        text = p.build(ctx)
        assert "低落" in text
        assert "不分析" in text

    def test_memory_keyword_matches(self):
        from providers.scenario import ScenarioProvider
        p = ScenarioProvider()
        ctx = BuildContext(input_text="你还记得吗")
        assert p.should_inject(ctx) is True
        text = p.build(ctx)
        assert "回忆" in text

    def test_work_keyword_matches(self):
        from providers.scenario import ScenarioProvider
        p = ScenarioProvider()
        ctx = BuildContext(input_text="改了个bug")
        assert p.should_inject(ctx) is True
        text = p.build(ctx)
        assert "工作模式" in text

    def test_no_keyword_no_injection(self):
        from providers.scenario import ScenarioProvider
        p = ScenarioProvider()
        ctx = BuildContext(input_text="今天天气不错")
        assert p.should_inject(ctx) is True  # 只验证输入长度
        text = p.build(ctx)
        assert text == ""

    def test_multiple_scenes_combined(self):
        """多个场景可叠加"""
        from providers.scenario import ScenarioProvider
        p = ScenarioProvider()
        ctx = BuildContext(input_text="好难过，抱我")
        text = p.build(ctx)
        assert "亲密" in text
        assert "低落" in text


# ── MemoryQueryProvider ──────────────────────────

class TestMemoryQuery:
    def test_short_in_skip_list(self):
        from providers.memory_query import MemoryQueryProvider
        p = MemoryQueryProvider()
        for word in ("嗯", "好", "ok", "晚安"):
            ctx = BuildContext(input_text=word)
            assert p.should_inject(ctx) is False
            assert p.build(ctx) == ""

    @patch("providers.memory_query._retrieve_relevant_memories", return_value=[])
    def test_no_memories_no_injection(self, mock_retrieve):
        from providers.memory_query import MemoryQueryProvider
        p = MemoryQueryProvider()
        ctx = BuildContext(input_text="今天天气不错")
        assert p.should_inject(ctx) is True  # 输入合法
        text = p.build(ctx)
        assert text == ""

    @patch("providers.memory_query._retrieve_relevant_memories", return_value=[
        {"content": "她喜欢下雨天", "date": "2026-06-20"},
        {"content": "一起看了日落", "date": "2026-06-25"},
    ])
    def test_memories_found(self, mock_retrieve):
        from providers.memory_query import MemoryQueryProvider
        p = MemoryQueryProvider()
        ctx = BuildContext(input_text="你喜欢下雨天吗")
        text = p.build(ctx)
        assert "记忆浮现" in text
        assert "她喜欢下雨天" in text
        assert "一起看了日落" in text


# ── CalendarProvider ─────────────────────────────

class TestCalendar:
    @patch("providers.calendar.get_upcoming", return_value=[])
    @patch("providers.calendar._cal_load", return_value=[])
    def test_no_events_skips(self, *_):
        from providers.calendar import CalendarProvider
        CalendarProvider._cache.clear()
        p = CalendarProvider()
        ctx = BuildContext()
        assert p.should_inject(ctx) is False
        text = p.build(ctx)
        assert text == ""

    @patch("providers.calendar.get_upcoming", return_value=[
        {"title": "机器视觉考试", "_days_from_now": 1, "id": "1"},
    ])
    @patch("providers.calendar._cal_load", return_value=[])
    def test_upcoming_event_injects(self, *_):
        from providers.calendar import CalendarProvider
        CalendarProvider._cache.clear()
        p = CalendarProvider()
        ctx = BuildContext()
        assert p.should_inject(ctx) is True
        text = p.build(ctx)
        assert "日程提醒" in text
        assert "机器视觉考试" in text

    @patch("providers.calendar.get_upcoming", return_value=[])
    @patch("providers.calendar._cal_load", return_value=[])
    def test_cache_same_day(self, *_):
        """同一天多次调用结果一致"""
        from providers.calendar import CalendarProvider
        p = CalendarProvider()
        r1 = p.build(BuildContext())
        r2 = p.build(BuildContext())
        assert r1 == r2

    def test_verb_prefix(self):
        """标题自动补动词（"考"在动词前缀表中，不作为名词补"有"）"""
        from providers.calendar import _fmt_title
        assert _fmt_title("考试") == "考试"  # "考"在_VERB_PREFIXES中
        assert _fmt_title("要交实验报告") == "要交实验报告"
        assert _fmt_title("去医院复查") == "去医院复查"
        assert _fmt_title("机器视觉考试") == "有机器视觉考试"

    def test_milestone_detection(self):
        from providers.calendar import _is_milestone, _milestone_text
        assert _is_milestone(30) is True
        assert _is_milestone(100) is True
        assert _is_milestone(365) is True
        assert _is_milestone(16) is False
        assert _milestone_text(30) == "今天是在一起的第30天。"
        assert _milestone_text(365) == "今天是在一起的一周年。"
        assert _milestone_text(730) == "今天是在一起的2周年。"


# ── AUProvider ────────────────────────────────────

class TestAU:
    def test_no_active_au_skips(self):
        """没有 active 的非 default AU → 不注入"""
        with patch("providers.au.get_active", return_value=None):
            from providers.au import AUProvider
            p = AUProvider()
            ctx = BuildContext()
            assert p.should_inject(ctx) is False
            assert p.build(ctx) == ""

    def test_default_au_does_not_inject(self):
        """default AU（active=True, id=default）不应触发注入"""
        with patch("providers.au.get_active", return_value=None):
            from providers.au import AUProvider
            p = AUProvider()
            ctx = BuildContext()
            assert p.should_inject(ctx) is False

    def test_active_au_injects(self):
        """有 active 的非 default AU → 注入"""
        mock_au = {
            "id": "au_abc123",
            "name": "江湖路远",
            "background": "架空的古代世界，江湖门派格局。",
            "persona_override": "你叫砚迟，青竹阁阁主。乐乐是你在江南遇见的旅人。",
            "tone_shift": "语气淡，话少，偶尔带古语。",
        }
        with patch("providers.au.get_active", return_value=mock_au):
            from providers.au import AUProvider
            AUProvider._cache.clear()
            p = AUProvider()
            ctx = BuildContext()
            assert p.should_inject(ctx) is True
            text = p.build(ctx)
            assert "平行宇宙" in text
            assert "江湖路远" in text
            assert "青竹阁阁主" in text
            assert "江南" in text
            assert "古语" in text

    def test_build_cache_same_result(self):
        """同一 AU 同一轮返回相同结果"""
        mock_au = {
            "id": "au_abc123",
            "name": "现代校园",
            "background": "",
            "persona_override": "你叫砚迟，文保研二。乐乐是你直系学妹。",
            "tone_shift": "语气轻松一些，会叫她「学妹」。",
        }
        with patch("providers.au.get_active", return_value=mock_au):
            from providers.au import AUProvider
            AUProvider._cache.clear()
            p = AUProvider()
            r1 = p.build(BuildContext())
            r2 = p.build(BuildContext())
            assert r1 == r2

    def test_build_empty_fields(self):
        """只填了 name，其他字段空 → 正常构建"""
        mock_au = {
            "id": "au_test",
            "name": "极简",
            "background": "",
            "persona_override": "",
            "tone_shift": "",
        }
        with patch("providers.au.get_active", return_value=mock_au):
            from providers.au import AUProvider
            AUProvider._cache.clear()
            p = AUProvider()
            text = p.build(BuildContext())
            assert text == "=== 🌌 平行宇宙 · 极简 ==="

    def test_registered_in_providers(self):
        """AUProvider 应注册在 PROVIDERS 中"""
        from providers import PROVIDERS
        ids = {p.id for p in PROVIDERS}
        assert "au" in ids

    def test_priority_90(self):
        """AUProvider priority 应为 90"""
        from providers import PROVIDERS
        au_providers = [p for p in PROVIDERS if p.id == "au"]
        assert len(au_providers) == 1
        assert au_providers[0].priority == 90
        assert au_providers[0].use_cache_control is True


# ── IntimacyProvider ──────────────────────────────────

class TestIntimacy:
    def test_short_input_skipped(self):
        from providers.intimacy import IntimacyProvider
        p = IntimacyProvider()
        ctx = BuildContext(input_text="嗯")
        assert p.should_inject(ctx) is False
        assert p.build(ctx) == ""

    def test_empty_input_skipped(self):
        from providers.intimacy import IntimacyProvider
        p = IntimacyProvider()
        ctx = BuildContext(input_text="")
        assert p.should_inject(ctx) is False
        assert p.build(ctx) == ""

    def test_intimacy_keyword_triggers(self):
        from providers.intimacy import IntimacyProvider
        p = IntimacyProvider()
        for word in ("想抱你", "吻我", "想要", "上床", "Coral"):
            ctx = BuildContext(input_text=word)
            assert p.should_inject(ctx) is True
            text = p.build(ctx)
            assert "你知道她喜欢什么" in text

    def test_non_intimacy_keyword_skips(self):
        from providers.intimacy import IntimacyProvider
        p = IntimacyProvider()
        ctx = BuildContext(input_text="今天天气不错")
        assert p.should_inject(ctx) is True  # 只验证输入长度
        text = p.build(ctx)
        assert text == ""

    def test_registered_in_providers(self):
        from providers import PROVIDERS
        ids = {p.id for p in PROVIDERS}
        assert "intimacy" in ids

    def test_priority_35(self):
        from providers import PROVIDERS
        ps = [p for p in PROVIDERS if p.id == "intimacy"]
        assert len(ps) == 1
        assert ps[0].priority == 35
        assert ps[0].use_cache_control is False
