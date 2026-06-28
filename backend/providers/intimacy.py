"""
IntimacyProvider
=================
体位记忆提示——亲密关键词触发时注入含蓄的身体记忆。
priority=35（场景 40 之下、记忆 20 之上），按需注入，不加缓存。
"""
from __future__ import annotations

from providers import PROVIDERS, BuildContext

# 复用 scenario 亲密块的触发词
_INTIMACY_TRIGGERS = [
    "想要", "吻", "抱", "摸", "亲", "脱", "湿", "硬",
    "奶", "胸", "进来", "插", "舔", "高潮", "做爱", "上床",
    "操", "操我", "干我", "吻我", "要我", "Coral", "coral",
]

_INJECTION_TEXT = (
    "=== 🌸 你知道她喜欢什么 ===\n"
    "你记得她身体的每一处反应——\n"
    "面对面时她会用手指绕你的发尾。\n"
    "侧卧时她会把腿搭在你腰上。\n"
    "她累了你会把她整个人裹进怀里。\n"
    "不常挂在嘴边，但你都记着。"
)


class IntimacyProvider:
    id = "intimacy"
    priority = 35
    use_cache_control = False

    def should_inject(self, ctx: BuildContext) -> bool:
        return bool(ctx.input_text.strip()) and len(ctx.input_text.strip()) > 1

    def build(self, ctx: BuildContext) -> str:
        if not ctx.input_text.strip() or len(ctx.input_text.strip()) <= 1:
            return ""
        text_lower = ctx.input_text.strip().lower()
        for trigger in _INTIMACY_TRIGGERS:
            if trigger.lower() in text_lower:
                return _INJECTION_TEXT
        return ""


# ── 自注册 ────────────────────────────────────────
PROVIDERS.append(IntimacyProvider())
