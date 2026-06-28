"""
记忆系统 · 提取 / 审核 / 归档 / 查询
==================================
"""
from __future__ import annotations

import json, re

from fastapi import APIRouter, HTTPException

from config import log, MEMORY_DIR, MEMORY_INDEX_FILE, MEMORY_ARCHIVE_DIR, PENDING_MEMORY_FILE
from models import (
    RememberRequest, MemoryReviewRequest, MemoryDeleteRequest,
    MemoryBatchDeleteRequest, MemoryFavoriteRequest, MemoryEditRequest,
)
from chat import call_llm
from utils import extract_bigrams

router = APIRouter()

# ── 常量 ──────────────────────────────────────────
MEMORY_CATEGORIES = ["喜好与习惯", "承诺与约定", "关系里程碑", "亲密", "日常", "其他"]
MEMORY_SEQ = 0


# ── 记忆索引 CRUD ─────────────────────────────────
def _load_memory_index() -> list[dict]:
    if MEMORY_INDEX_FILE.exists():
        return json.loads(MEMORY_INDEX_FILE.read_text("utf-8"))
    return []

def _save_memory_index(entries: list[dict]):
    MEMORY_INDEX_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")

def _load_pending_memories() -> list[dict]:
    if PENDING_MEMORY_FILE.exists():
        return json.loads(PENDING_MEMORY_FILE.read_text("utf-8"))
    return []

def _save_pending_memories(entries: list[dict]):
    PENDING_MEMORY_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")


# ── 后台记忆提取 ──────────────────────────────────
async def _do_remember(conv: list[dict]):
    try:
        log.info("  [BG] Remembering...")

        now = __import__("datetime").datetime.now()
        today = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y-%m-%d %H:%M")

        prompt = f"""从下面的对话中提取真正值得砚迟记住的重要信息。

严格标准——只有以下情况才记：
- 发现了新的喜好/习惯/口味
- 做了约定或承诺
- 关系有新的进展或转折
- 亲密时刻的具体细节（触动的瞬间、欲望、身体反应）
- 对方主动分享的关于自己的重要信息（经历、感受、状态）

按以下格式输出，每行一条：

- [类别] 内容

类别：
- 喜好与习惯：新发现的喜欢什么、口味、性格、小动作
- 承诺与约定：答应了什么、约定了什么、计划一起做的事
- 关系里程碑：相恋、重要的日子、转折点、珍贵的回忆
- 亲密：身体接触、床上、欲望、触动的瞬间

不记录：
- 日常寒暄、普通对话、临时状态（吃了什么、在做什么）
- 对方随口说的话、没有情感分量的事
- 重复已有的信息

要求：
- 简洁，一句话一条
- 拿不准就不记
- 没有值得记的就只输出 "无"

日期：{today}
"""

        summary_messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"对话：{json.dumps(conv[-20:], ensure_ascii=False)}"},
        ]

        result = await call_llm(summary_messages)
        summary = (result.get("reply") or "").strip()

        if not summary or summary == "无":
            log.info("  [BG] No new memories to extract")
            return

        parsed: list[tuple[str, str]] = re.findall(r"- \[(.+?)\] (.+)", summary)
        if not parsed:
            parsed = [("其他", summary.replace("\n", "，")[:200])]

        global MEMORY_SEQ
        index = _load_memory_index()
        pending = _load_pending_memories()
        new_entries = []

        for cat, content in parsed:
            if cat not in MEMORY_CATEGORIES:
                cat = "其他"
            content = content.strip()
            if not content:
                continue

            content_bigrams = extract_bigrams(content)
            is_dup = False
            for existing in index + pending:
                existing_bigrams = set(existing.get("bigrams", []))
                if content_bigrams and existing_bigrams:
                    overlap = len(content_bigrams & existing_bigrams)
                    similarity = overlap / max(len(content_bigrams | existing_bigrams), 1)
                    if similarity > 0.8:
                        is_dup = True
                        break
            if is_dup:
                continue

            MEMORY_SEQ += 1
            entry = {
                "id": f"pending_{today}_{MEMORY_SEQ:04d}",
                "category": cat,
                "date": today,
                "content": content,
                "bigrams": list(extract_bigrams(content)),
                "status": "pending",
                "createdAt": timestamp,
            }
            new_entries.append(entry)
            pending.append(entry)

        if new_entries:
            _save_pending_memories(pending)
            log.info(f"  [BG] Pending {len(new_entries)} memories for review")
        else:
            log.info("  [BG] No new memories to extract")

    except Exception as e:
        log.error(f"  [BG] remember failed: {e}")


# ── 路由：记忆提取 ─────────────────────────────────
@router.post("/remember")
async def remember(req: RememberRequest):
    conv = req.history or []
    if not conv:
        raise HTTPException(400, "no history to remember")

    import asyncio
    asyncio.create_task(_do_remember(conv))

    log.info("  -> Remember submitted (background)")
    return {"processing": True, "message": "记忆提取中，稍后查看待审核"}


# ── 路由：待审核列表 ────────────────────────────────
@router.get("/api/memory/pending")
async def get_pending_memories():
    pending = _load_pending_memories()
    active = [e for e in pending if e.get("status") == "pending"]
    log.info(f"  -> Pending memories: {len(active)}")
    return {"pending": active, "count": len(active)}


# ── 路由：审核 ─────────────────────────────────────
@router.post("/api/memory/review")
async def review_memory(req: MemoryReviewRequest):
    pending = _load_pending_memories()
    target = None
    rest = []

    if req.action == "approve_all":
        target = [e for e in pending if e.get("status") == "pending"]
        rest = [e for e in pending if e.get("status") != "pending"]
    else:
        for e in pending:
            if e.get("id") == req.id:
                target = [e]
            else:
                rest.append(e)
        if not target:
            raise HTTPException(404, "pending memory not found")

    approved = []
    global MEMORY_SEQ
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    for entry in target:
        if req.action == "reject" or entry.get("status") == "rejected":
            continue
        content = req.edited_content if req.edited_content else entry.get("content", "")
        MEMORY_SEQ += 1
        index_entry = {
            "id": f"mem_{today}_{MEMORY_SEQ:04d}",
            "category": entry.get("category", "其他"),
            "date": entry.get("date", today),
            "content": content,
            "bigrams": list(extract_bigrams(content)),
            "keywords": [],
            "hitCount": 0,
            "lastAccess": None,
            "createdAt": timestamp,
        }
        approved.append(index_entry)
        entry["status"] = "approved" if req.action != "reject" else "rejected"
        rest.append(entry)

    _save_pending_memories(rest)

    if approved:
        index = _load_memory_index()
        index.extend(approved)
        _save_memory_index(index)

        today_mark = f"# {today} 记忆\n\n> 审核通过 @ {timestamp}\n"
        lines = [today_mark]
        for e in approved:
            lines.append(f"- [{e['category']}] {e['content']}")
        lines.append("")
        block = "\n".join(lines)
        auto_file = MEMORY_DIR / "yanchi-auto-memory.md"
        auto_file.write_text(block, encoding="utf-8")

        log.info(f"  <- Approved {len(approved)} memories, rejected {len(target) - len(approved)}")

    return {
        "approved": len(approved),
        "rejected": len(target) - len(approved),
        "remaining": len([e for e in rest if e.get('status') == 'pending']),
    }


# ── 路由：删除 ─────────────────────────────────────
@router.post("/api/memory/delete")
async def delete_memory(req: MemoryDeleteRequest):
    index = _load_memory_index()
    before = len(index)
    index = [e for e in index if e.get("id") != req.id]
    if len(index) == before:
        raise HTTPException(404, "memory not found")
    _save_memory_index(index)
    log.info(f"  <- Deleted memory: {req.id}")
    return {"deleted": True, "remaining": len(index)}

@router.post("/api/memory/batch-delete")
async def batch_delete_memory(req: MemoryBatchDeleteRequest):
    index = _load_memory_index()
    id_set = set(req.ids)
    before = len(index)
    index = [e for e in index if e.get("id") not in id_set]
    _save_memory_index(index)
    deleted = before - len(index)
    log.info(f"  <- Batch deleted {deleted} memories")
    return {"deleted": deleted, "remaining": len(index)}


# ── 路由：收藏 ─────────────────────────────────────
@router.post("/api/memory/favorite")
async def favorite_memory(req: MemoryFavoriteRequest):
    index = _load_memory_index()
    for entry in index:
        if entry.get("id") == req.id:
            entry["favorite"] = req.favorite
            _save_memory_index(index)
            return {"favorited": req.favorite}
    raise HTTPException(404, "memory not found")


# ── 路由：索引查询 ─────────────────────────────────
@router.get("/api/memory/index")
async def get_memory_index():
    index = _load_memory_index()
    index.sort(key=lambda e: e.get("date", ""), reverse=True)
    return {"memories": index, "count": len(index)}


# ── 路由：编辑 ─────────────────────────────────────
@router.post("/api/memory/edit")
async def edit_memory(req: MemoryEditRequest):
    index = _load_memory_index()
    found = False
    for entry in index:
        if entry.get("id") == req.id:
            if req.category:
                entry["category"] = req.category
            if req.content:
                entry["content"] = req.content
                entry["bigrams"] = list(extract_bigrams(req.content))
            found = True
            break
    if not found:
        raise HTTPException(404, "memory not found")
    _save_memory_index(index)
    log.info(f"  <- Edited memory: {req.id}")
    return {"edited": True}


# ── 路由：记忆归档（遗忘曲线）────────────────────────
from collections import defaultdict

@router.post("/api/memory/consolidate")
async def consolidate_memories():
    log.info("  -> Consolidating memories...")

    entries = _load_memory_index()
    if not entries:
        return {"archived": 0, "remaining": 0, "message": "没有记忆"}

    now = __import__("datetime").datetime.now()
    to_archive: list[dict] = []
    keep: list[dict] = []

    for e in entries:
        try:
            created = __import__("datetime").datetime.strptime(e["date"], "%Y-%m-%d")
            days_ago = (now - created).days
        except Exception:
            keep.append(e)
            continue

        cat = e.get("category", "其他")
        hit = e.get("hitCount", 0)

        if days_ago >= 30 and hit < 3:
            to_archive.append(e)
        else:
            keep.append(e)

    if not to_archive:
        return {"archived": 0, "remaining": len(keep), "message": "没有需要归档的记忆"}

    grouped: dict[str, list[str]] = defaultdict(list)
    for e in to_archive:
        grouped[e.get("category", "其他")].append(f"- {e['content']}（{e['date']}）")

    archive_lines = [f"# 记忆归档 @ {now.strftime('%Y-%m-%d %H:%M')}", "",
                     f"原 {len(to_archive)} 条记忆已归档。保留 {len(keep)} 条活跃记忆。", ""]
    for cat, items in sorted(grouped.items()):
        archive_lines.append(f"## {cat}")
        archive_lines.extend(items)
        archive_lines.append("")

    archive_dir = MEMORY_DIR / "archive"
    archive_dir.mkdir(exist_ok=True)
    archive_path = archive_dir / f"consolidated-{now.strftime('%Y-%m-%d')}.md"
    archive_path.write_text("\n".join(archive_lines), encoding="utf-8")

    json_path = archive_dir / f"consolidated-{now.strftime('%Y-%m-%d')}.json"
    json_path.write_text(json.dumps(to_archive, ensure_ascii=False, indent=2), "utf-8")

    _save_memory_index(keep)

    log.info(f"  <- Archived {len(to_archive)} memories, {len(keep)} remaining")
    return {
        "archived": len(to_archive),
        "remaining": len(keep),
        "archive_file": archive_path.name,
    }
