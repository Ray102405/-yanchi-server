"""
P5 · BookDiscussion Providers
===============================
书籍讨论独立注入链——注册在 BOOK_PROVIDERS 中，不污染主链缓存。

两个 provider 组成讨论 prompt：
  1. BookPersonaProvider (p=100)  — 人格核心 + 说话风格
  2. BookDiscussionContextProvider (p=80) — 当前章节 + 衔接 + 讨论提示
"""
from __future__ import annotations

from providers import BOOK_PROVIDERS, BuildContext

from persona import persona_cache


# ── Provider 1：人格 ─────────────────────────────
class BookPersonaProvider:
    """书籍讨论用的人格 core + style（与主链分离，独立缓存边界）。"""
    id = "book_persona"
    priority = 100
    use_cache_control = False  # 书籍讨论不走 prompt caching

    def should_inject(self, ctx: BuildContext) -> bool:
        return bool(persona_cache.get("core") or persona_cache.get("style"))

    def build(self, ctx: BuildContext) -> str:
        parts: list[str] = []
        core = persona_cache.get("core", "")
        if core:
            parts.append(core)
        style = persona_cache.get("style", "")
        if style:
            parts.append("── 你怎么说话 ──")
            parts.append(style)
        return "\n\n".join(parts) if len(parts) > 1 else (parts[0] if parts else "")


# ── Provider 2：书籍讨论上下文 ─────────────────────
class BookDiscussionContextProvider:
    """当前阅读的章节内容 + 前后衔接 + 讨论指导。"""
    id = "book_discussion_context"
    priority = 80
    use_cache_control = False

    def should_inject(self, ctx: BuildContext) -> bool:
        return bool(ctx.book_data)

    def build(self, ctx: BuildContext) -> str:
        bd = ctx.book_data or {}
        title = bd.get("title", "")
        chapter_index = bd.get("chapter_index", 0)
        chapter_title = bd.get("chapter_title", "")
        chapter_content = bd.get("chapter_content", "")
        prev_discuss = bd.get("prev_discuss", "")
        prev_content = bd.get("prev_content", "")
        next_content = bd.get("next_content", "")
        streaming = bd.get("streaming", False)

        if streaming:
            # 流式版本（与原始 discuss_book_stream 完全一致）
            parts: list[str] = [
                f"=== 📖 你和乐乐正在一起看《{title}》 ===",
                f"你们读到了第 {chapter_index + 1} 章：{chapter_title}",
                "",
                "内容：",
                chapter_content[:3000],
            ]
            if prev_discuss:
                parts.extend(["", prev_discuss])
            parts.extend([
                "",
                "现在乐乐想和你讨论剧情。自然地聊聊你的感受。",
                "记住之前聊过的内容，保持对话的连续性。不要剧透还没读到的内容。",
            ])
        else:
            # 非流式版本（与原始 discuss_book 完全一致）
            parts: list[str] = [
                f"=== 📖 你和乐乐正在一起看《{title}》 ===",
                f"你们读到了第 {chapter_index + 1} 章：{chapter_title}",
                "",
                "当前章节内容片段：",
                chapter_content[:3000],
            ]
            if prev_discuss:
                parts.extend(["", prev_discuss])
            if prev_content:
                parts.extend(["", "上一章末尾（承接）：", prev_content])
            if next_content:
                parts.extend(["", "下一章开头（伏笔）：", next_content])
            parts.extend([
                "",
                "现在乐乐想和你讨论剧情。你可以分享你的感受、猜测、对角色和情节的看法。",
                "不用分析——像两个人一起看书时随口交流那样自然就好。",
                "不要剧透还没读到的内容（你没看过这本书），但可以基于当前读到的部分自由发挥。",
                "记住之前和乐乐聊过的内容，保持对话的连续性，不要重复说过的话。",
                "语气温柔自然，像平时说话的砚迟。",
            ])

        return "\n".join(parts)


# ── 自注册到 BOOK_PROVIDERS ──────────────────────
BOOK_PROVIDERS.append(BookPersonaProvider())
BOOK_PROVIDERS.append(BookDiscussionContextProvider())
