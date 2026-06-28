"""
P4 · MemoryQueryProvider
==========================
记忆浮现注入——基于当前输入检索相关记忆。
最低优先级（每轮都变，不能打穿缓存）。
对应原 persona._build_query_context()。
"""
from __future__ import annotations

from providers import PROVIDERS, BuildContext

from persona import _retrieve_relevant_memories

# ── 短回复跳过名单 ────────────────────────────────
_SHORT_SKIP = {
    "嗯", "好", "嗯嗯", "好的", "睡了", "晚安", "早", "哈哈",
    "ok", "okk", "okay", "没事", "哦", "嗯好", "知道了", "行", "可以",
}


class MemoryQueryProvider:
    id = "memory_query"
    priority = 20
    use_cache_control = False

    def should_inject(self, ctx: BuildContext) -> bool:
        # 只做输入合法性过滤；build() 统一执行检索（避免 side-effect 重复）
        if not ctx.input_text.strip():
            return False
        stripped = ctx.input_text.strip()
        return stripped not in _SHORT_SKIP and len(stripped) > 2

    def build(self, ctx: BuildContext) -> str:
        if not ctx.input_text.strip():
            return ""
        stripped = ctx.input_text.strip()
        if stripped in _SHORT_SKIP or len(stripped) <= 2:
            return ""
        relevant = _retrieve_relevant_memories(stripped, max_results=5)
        if not relevant:
            return ""
        parts = ["=== 🧠 记忆浮现（当前话题让你想起的） ==="]
        for m in relevant:
            parts.append(f"- {m['content']}（{m['date']}）")
        return "\n".join(parts)


# ── 自注册 ────────────────────────────────────────
PROVIDERS.append(MemoryQueryProvider())
