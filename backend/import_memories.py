"""
批量导入历史 RP 记录和笔记到记忆索引。
用法：python import_memories.py
"""
import os, re, json, logging
from pathlib import Path

# ── 路径 ──────────────────────────────────────────
HOME = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

# 数据目录（跟 main.py 一致）
DATA_DIR = PROJECT_DIR / "data"
if not DATA_DIR.exists():
    DATA_DIR = HOME / ".claude/projects/C--Users-Ray/memory/yanchi"

MEMORY_INDEX_FILE = DATA_DIR / "yanchi-memory-index.json"
CLAUDE_MEMORY_DIR = HOME / ".claude/projects/C--Users-Ray/memory"

# ── API 配置 ──────────────────────────────────────
CLAUDE_CONFIG = HOME / ".claude/settings.json"
if CLAUDE_CONFIG.exists():
    config = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8")).get("env", {})
else:
    config = {}

API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN") or config.get("ANTHROPIC_AUTH_TOKEN", "")
BASE_URL = (os.environ.get("ANTHROPIC_BASE_URL") or config.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")).rstrip("/")
API_URL = f"{BASE_URL}/messages"

if not API_KEY:
    raise RuntimeError("No API key found")

# ── 辅助 ──────────────────────────────────────────
def strip_frontmatter(text: str) -> str:
    return re.sub(r"(?s)^---\s*.*?---\s*", "", text).strip()

def extract_bigrams(text: str) -> set[str]:
    cleaned = re.sub(r'[^一-鿟\w]', '', text)
    return {cleaned[i:i+2] for i in range(len(cleaned) - 1) if len(cleaned[i:i+2]) == 2}

def load_index():
    if MEMORY_INDEX_FILE.exists():
        return json.loads(MEMORY_INDEX_FILE.read_text("utf-8"))
    return []

def save_index(entries):
    MEMORY_INDEX_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")
    print(f"  -> Saved {len(entries)} entries to index")

# ── 要导入的文件 ─────────────────────────────────
FILES_TO_IMPORT = [
    # RP 记录
    (CLAUDE_MEMORY_DIR / "rp" / "rp-2026-06-16.md", "2026-06-16", "RP"),
    (CLAUDE_MEMORY_DIR / "rp" / "rp-2026-06-17.md", "2026-06-17", "RP"),
    (CLAUDE_MEMORY_DIR / "rp" / "rp-2026-06-19.md", "2026-06-19", "RP"),
    (CLAUDE_MEMORY_DIR / "rp" / "rp-2026-06-23.md", "2026-06-23", "RP"),
    (CLAUDE_MEMORY_DIR / "rp" / "rp-2026-06-24.md", "2026-06-24", "RP"),
    (CLAUDE_MEMORY_DIR / "rp" / "rp-2026-06-24-trigger-revision.md", "2026-06-24", "RP"),
    (CLAUDE_MEMORY_DIR / "rp" / "rp-2026-06-25.md", "2026-06-25", "RP"),
    # 笔记
    (DATA_DIR / "yanchi-notes" / "2026-06-25.md", "2026-06-25", "note"),
    (DATA_DIR / "yanchi-notes" / "2026-06-26.md", "2026-06-26", "note"),
]

# ── 提取 prompt ──────────────────────────────────
EXTRACT_PROMPT = """从以下文本中提取值得砚迟记住的重要信息。按格式输出，每行一条：

- [类别] 内容

类别：
- 喜好与习惯：喜欢什么、日常习惯、口味、性格、小动作
- 承诺与约定：答应了什么、约定了什么、计划一起做的事
- 关系里程碑：相恋、重要的日子、转折点、珍贵的回忆
- 亲密：身体接触、床上、欲望、触动的瞬间
- 日常：生活琐事、没特别分类的对话、日常状态
- 其他：不归入以上但值得记住的

要求：简洁，一句话一条，只提取对这个关系重要的事。
重复的不提，已有信息不提。"""

# ── 调用 API ─────────────────────────────────────
import httpx

async def call_llm(messages: list[dict]) -> dict:
    body = {
        "model": "deepseek-v4-flash",
        "max_tokens": 2048,
        "messages": messages,
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(API_URL, json=body, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"API error ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    text_parts = []
    for block in data.get("content", []):
        if block.get("type") == "text" and block.get("text"):
            text_parts.append(block["text"])
    return {"reply": text_parts[-1] if text_parts else "无"}

# ── 主流程 ───────────────────────────────────────
import asyncio

async def main():
    print(f"数据目录: {DATA_DIR}")
    print(f"索引文件: {MEMORY_INDEX_FILE}")
    print()

    index = load_index()
    existing_bigrams = [set(e.get("bigrams", [])) for e in index]
    SEQ = len(index) + 1
    total_new = 0

    for filepath, date_str, file_type in FILES_TO_IMPORT:
        if not filepath.exists():
            print(f"[SKIP] {filepath.name} not found")
            continue

        content = strip_frontmatter(filepath.read_text("utf-8"))
        if not content:
            print(f"[SKIP] {filepath.name} empty")
            continue

        print(f"[{date_str}] {file_type}: {filepath.name} ({len(content)} chars)")

        msg = [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": f"日期：{date_str}\n\n文本：\n{content[:4000]}"},
        ]

        try:
            result = await call_llm(msg)
            summary = (result.get("reply") or "").strip()
        except Exception as e:
            print(f"  [ERROR] API call failed: {e}")
            continue

        if not summary or summary == "无":
            print(f"  -> No new memories")
            continue

        parsed = re.findall(r"- \[(.+?)\] (.+)", summary)
        if not parsed:
            parsed = [("其他", summary.replace("\n", "，")[:200])]

        new_entries = []
        for cat, text in parsed:
            if cat not in ["喜好与习惯", "承诺与约定", "关系里程碑", "亲密", "日常", "其他"]:
                cat = "其他"
            text = text.strip()
            if not text:
                continue

            bigrams = list(extract_bigrams(text))
            # 去重
            is_dup = False
            for eb in existing_bigrams:
                if bigrams and eb:
                    overlap = len(set(bigrams) & eb)
                    similarity = overlap / max(len(set(bigrams) | eb), 1)
                    if similarity > 0.8:
                        is_dup = True
                        break
            if is_dup:
                continue

            entry = {
                "id": f"mem_{date_str}_{SEQ:04d}",
                "category": cat,
                "date": date_str,
                "content": text,
                "bigrams": bigrams,
                "keywords": [],
                "hitCount": 0,
                "lastAccess": None,
                "createdAt": f"{date_str} 00:00",
            }
            new_entries.append(entry)
            index.append(entry)
            existing_bigrams.append(set(bigrams))
            SEQ += 1

        if new_entries:
            total_new += len(new_entries)
            print(f"  -> +{len(new_entries)} new memories")
            for e in new_entries:
                print(f"     [{e['category']}] {e['content'][:60]}")
        else:
            print(f"  -> All already in index, skipped")

    if total_new > 0:
        save_index(index)
    print(f"\nDone! Total new: {total_new}")

if __name__ == "__main__":
    asyncio.run(main())
