"""
AUProvider
===========
平行宇宙场景注入——当有 active 的非 default AU 时，
在静态人格（p=100）之后叠加 AU 设定。
priority=90，带 cache_control，内容按天稳定。
"""
from __future__ import annotations

import time

from providers import PROVIDERS, BuildContext
from au_data import get_active


class AUProvider:
    id = "au"
    priority = 90
    use_cache_control = True

    _cache: dict[str, tuple[str, float]] = {}
    _ttl = 60  # seconds

    def should_inject(self, ctx: BuildContext) -> bool:
        au = get_active()
        return au is not None

    def build(self, ctx: BuildContext) -> str:
        now = time.time()
        cached = self._cache.get("au")
        if cached and now - cached[1] < self._ttl:
            return cached[0]

        au = get_active()
        if not au:
            return ""

        parts: list[str] = [f"=== 🌌 平行宇宙 · {au['name']} ==="]
        lines: list[str] = []
        if au.get("background"):
            lines.append(au["background"])
        if au.get("persona_override"):
            lines.append(au["persona_override"])
        if au.get("tone_shift"):
            lines.append(au["tone_shift"])

        if lines:
            parts.append("")
            parts.extend(lines)

        content = "\n".join(parts).strip()
        self._cache["au"] = (content, now)
        return content


# ── 自注册 ────────────────────────────────────────
PROVIDERS.append(AUProvider())
