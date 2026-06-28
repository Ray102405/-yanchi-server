"""
人格系统 · 提示词构建
=================
加载砚迟人设文件、构建 system prompt（静态/动态/场景/记忆浮现）。
"""
from __future__ import annotations

import json, re, time
from pathlib import Path

from config import MEMORY_DIR, MEMORY_INDEX, log, get_last_chat_activity
from utils import extract_bigrams

# ── 读取 md 文件去 frontmatter ─────────────────────
def read_md(filename: str) -> str:
    path = MEMORY_DIR / filename
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    content = re.sub(r"(?s)^---\s*.*?---\s*", "", content)
    return content.strip()


# ── 加载人格缓存 ──────────────────────────────────
persona_cache: dict[str, str] = {}

_SKIP_MILESTONE_KEYWORDS = {"框架", "验证", "日记", "信→", "系统", "评估", "测试", "AI"}


def _filter_relationship_milestones(raw: str) -> str:
    """过滤 milestones，只保留关系里程碑（去掉开发过程记录）。"""
    sections = re.split(r"\n(?=### )", raw)
    kept = []
    for sec in sections:
        header_match = re.search(r"^### (.+)", sec, re.MULTILINE)
        if header_match:
            header = header_match.group(1)
            if any(kw in header for kw in _SKIP_MILESTONE_KEYWORDS):
                continue
        kept.append(sec)
    return "\n".join(kept).strip()

def init_persona():
    files = {
        "commitments": "yanchi-commitments.md",
        "core": "yanchi-core.md",
        "values": "yanchi-values.md",
        "style": "yanchi-speaking-style.md",
        "profile": "yanchi-profile.md",
        "interests": "yanchi-interests.md",
        "milestones": "yanchi-milestones.md",
        "anchor": "yanchi-global-anchor.md",
    }
    for key, fname in files.items():
        content = read_md(fname)
        if content:
            # milestones 只保留关系里程碑（过滤开发过程记录）
            if key == "milestones":
                content = _filter_relationship_milestones(content)
            persona_cache[key] = content
            log.info(f"  [OK] {fname} ({len(content)} chars)")

    if not persona_cache:
        fallback = Path(__file__).resolve().parent / "yanchi-prompt.txt"
        if fallback.exists():
            persona_cache["fallback"] = fallback.read_text(encoding="utf-8")
            log.info("  [FALLBACK] yanchi-prompt.txt")
        else:
            raise RuntimeError("No persona files found!")

    if MEMORY_INDEX.exists():
        log.info(f"  [OK] MEMORY.md index ({len(MEMORY_INDEX.read_text('utf-8'))} chars)")


# ── 今日笔记读取 ──────────────────────────────────

def _get_today_note(today_str: str) -> str:
    """Extract today's entry from data/yanchi-today-note.md"""
    return _read_note_file(MEMORY_DIR / "yanchi-today-note.md", today_str)

def _read_note_file(filepath: Path, today_str: str) -> str:
    if not filepath.exists():
        return ""
    text = filepath.read_text("utf-8")
    pattern = rf"## {today_str}\s*\n>.*?\n(.*?)(?=\n## |\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).strip()[:300]
    return ""


# ── 精选回忆辅助（从 timeline 模块导入）────────────────
from timeline import load_highlights, read_preview

def _get_recent_highlights() -> str:
    hs = load_highlights()
    if not hs:
        return ""
    texts = []
    for hid in sorted(hs, reverse=True)[:3]:
        for candidate in [MEMORY_DIR / hid, MEMORY_DIR / "yanchi-chats" / hid, MEMORY_DIR / "yanchi-notes" / hid]:
            full = candidate.resolve()
            if full.exists() and str(full).startswith(str(MEMORY_DIR.resolve())):
                preview = read_preview(full, 200)
                if preview:
                    texts.append(f"- {hid}: {preview}")
                break
    return "\n".join(texts)


# ── 记忆索引辅助 ──────────────────────────────────
MEMORY_INDEX_FILE = MEMORY_DIR / "yanchi-memory-index.json"

def _load_memory_index() -> list[dict]:
    if MEMORY_INDEX_FILE.exists():
        return json.loads(MEMORY_INDEX_FILE.read_text("utf-8"))
    return []

def _retrieve_relevant_memories(query: str, max_results: int = 5) -> list[dict]:
    entries = _load_memory_index()
    if not entries or not query.strip():
        return []

    query_bigrams = extract_bigrams(query)
    now = __import__("datetime").datetime.now()
    scored: list[tuple[float, int, dict]] = []

    for entry in entries:
        entry_bigrams = set(entry.get("bigrams", []))
        if query_bigrams and entry_bigrams:
            overlap = len(query_bigrams & entry_bigrams)
            similarity = overlap / max(len(query_bigrams | entry_bigrams), 1)
        else:
            similarity = 0
        if similarity == 0:
            continue
        try:
            created = __import__("datetime").datetime.strptime(entry["date"], "%Y-%m-%d")
            days_ago = max((now - created).days, 0)
            time_decay = 2.0 ** (-days_ago / 7)
            if days_ago > 30:
                time_decay *= 0.3
        except Exception:
            time_decay = 0
        score = similarity * time_decay
        scored.append((score, entry.get("hitCount", 0), entry))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    selected = [e for _, _, e in scored[:max_results]]

    if selected:
        selected_ids = {e["id"] for e in selected}
        for entry in entries:
            if entry["id"] in selected_ids:
                entry["hitCount"] = entry.get("hitCount", 0) + 1
                entry["lastAccess"] = now.strftime("%Y-%m-%d %H:%M")
        with MEMORY_INDEX_FILE.open("w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    return selected

def _get_recent_memories(count: int = 3) -> list[dict]:
    entries = _load_memory_index()
    if not entries:
        return []
    entries = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)
    return entries[:count]


# ── 兼容层：旧构建函数 → 委托给 provider ───────────
# 保留原函数名，供 chat.py（降级模式）和其他导入方使用。
from providers import BuildContext

def _build_static_prompt(anchor: str = "") -> str:
    from providers.static_persona import StaticPersonaProvider
    p = StaticPersonaProvider()
    return p.build(BuildContext(anchor=anchor))

def _build_daily_context() -> str:
    from providers.daily_context import DailyContextProvider
    p = DailyContextProvider()
    return p.build(BuildContext())

def _build_scenario_context(input_text: str = "") -> str:
    from providers.scenario import ScenarioProvider
    p = ScenarioProvider()
    return p.build(BuildContext(input_text=input_text))

def _build_query_context(input_text: str = "") -> str:
    from providers.memory_query import MemoryQueryProvider
    p = MemoryQueryProvider()
    return p.build(BuildContext(input_text=input_text))


# 初始化人设缓存
init_persona()
