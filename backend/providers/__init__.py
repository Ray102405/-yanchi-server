"""
ContextProvider 协议 · 可插拔的提示词注入系统
=========================================
协议定义 + 注册表 + assemble 入口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class BuildContext:
    """所有 provider 共享的上下文数据包。

    字段按需惰性求值——未涉及的 provider 不感知。
    book_data 专供 BOOK_PROVIDERS 使用，由书籍路由预处理后传入。
    """
    input_text: str = ""
    anchor: str = ""
    session_id: str = ""
    history: list[dict] | None = None
    file_texts: list[str] | None = None
    book_data: dict | None = None  # 书籍讨论专用：title/chapter/content/衔接


class ContextProvider(Protocol):
    """提示词注入协议。

    - priority: 越大越靠前（静态人格 100 > 每日 70 > 场景 40 > 记忆 20）
    - should_inject(ctx) → bool: 是否注入本轮
    - build(ctx) → str: 注入内容（空字符串 = 跳过）
    """
    id: str
    priority: int
    use_cache_control: bool = False

    def should_inject(self, ctx: BuildContext) -> bool:
        ...

    def build(self, ctx: BuildContext) -> str:
        ...


# ── 主聊天 PROVIDERS 注册表 ────────────────────────
PROVIDERS: list[Any] = []


def assemble(ctx: BuildContext) -> list[dict]:
    """遍历 PROVIDERS → priority 降序 → should_inject → build → system messages"""
    msgs: list[dict] = []
    for p in sorted(PROVIDERS, key=lambda x: x.priority, reverse=True):
        if p.should_inject(ctx):
            content = p.build(ctx)
            if content.strip():
                msg: dict = {"role": "system", "content": content}
                if getattr(p, "use_cache_control", False):
                    msg["cache_control"] = {"type": "ephemeral"}
                msgs.append(msg)
    return msgs


# ── 书籍讨论 BOOK_PROVIDERS 注册表 ─────────────────
BOOK_PROVIDERS: list[Any] = []


def assemble_book(ctx: BuildContext) -> list[dict]:
    """独立注册表，由 books.py 讨论路由遍历（不污染主链缓存）。"""
    msgs: list[dict] = []
    for p in sorted(BOOK_PROVIDERS, key=lambda x: x.priority, reverse=True):
        if p.should_inject(ctx):
            content = p.build(ctx)
            if content.strip():
                msgs.append({"role": "system", "content": content})
    return msgs


# ── 惰性加载各 provider（在底部执行，确保 PROVIDERS 先就绪）─
from . import static_persona  # noqa: E402, F811
from . import daily_context    # noqa: E402, F811
from . import au               # noqa: E402, F811
from . import scenario         # noqa: E402, F811
from . import intimacy          # noqa: E402, F811
from . import memory_query     # noqa: E402, F811
from . import book_discussion  # noqa: E402, F811
from . import calendar         # noqa: E402, F811
