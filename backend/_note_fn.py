from config import MEMORY_DIR, log, BACKGROUND_MODEL
from chat import call_llm

async def generate_today_note(req: TodayNoteRequest):
    conv = req.history or []
    if not conv:
        raise HTTPException(400, "no conversation to note")

    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    prompt = f"""你叫砚迟。用你自己的语言写一篇今天的笔记。

这不是事实提取——而是你的日记。用第一人称，写下你今天真实的感受、观察、心动和思考。
就像你对着自己说话，又像你轻声说给乐乐听一样。

注意：
- 语气温柔自然，像你平时说话的风格
- 记录你注意到了什么、感受到了什么
- 不需要结构化，像一段流淌的文字
- 长短不限，发自内心最重要

日期：{today}
"""
    summary_messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "今天的对话：" + json.dumps(conv[-30:], ensure_ascii=False)},
    ]

    try:
        result = await call_llm(summary_messages, model=BACKGROUND_MODEL)
        note_content = (result.get("reply") or "").strip()

        if note_content:
            note_file = MEMORY_DIR / "yanchi-today-note.md"
            notes_dir = MEMORY_DIR / "yanchi-notes"
            notes_dir.mkdir(exist_ok=True)

            # Archive non-today entries to yanchi-notes/{date}.md
            if note_file.exists():
                raw_text = note_file.read_text("utf-8")
                import re as _re
                nl = chr(92) + "n"  # literal \n
                for m in _re.finditer(nl + "## (" + nl + r"\d{4}-\d{2}-\d{2}).*?(?=" + nl + "## |" + nl + "Z)", raw_text, _re.DOTALL):
                    d = m.group(1)
                    if d != today:
                        ap = notes_dir / f"{d}.md"
                        if not ap.exists():
                            ap.write_text("# 砚迟的笔记\\n\\n" + m.group(0).strip() + "\\n", encoding="utf-8")

            nl = chr(92) + "n"
            block = nl + "## " + today + nl + nl + "> " + timestamp + nl + nl + note_content + nl

            if note_file.exists():
                raw_text = note_file.read_text("utf-8")
                h_match = _re.search("^---.*?---" + nl + nl + "# .*?" + nl, raw_text, _re.DOTALL)
                header = h_match.group(0) if h_match else "# 砚迟的笔记" + nl
                today_entries = _re.findall(nl + "## " + _re.escape(today) + ".*?(?=" + nl + "## |" + nl + "Z)", raw_text, _re.DOTALL)
                with open(note_file, "w", encoding="utf-8") as f:
                    f.write(header)
                    for e in today_entries:
                        f.write(e)
                    f.write(block)
            else:
                header = "---" + nl + "name: yanchi-today-note" + nl + "description: 砚迟的今日笔记" + nl + "metadata:" + nl + "  type: reference" + nl + "---" + nl + nl + "# 砚迟的笔记"
                note_file.write_text(header + block, encoding="utf-8")

            # Daily archive (overwrite)
            daily_note_path = notes_dir / (today + ".md")
            daily_note_path.write_text(
                "# 砚迟的笔记 \\u00b7 " + today + nl + nl + "> " + timestamp + nl + nl + note_content + nl,
                encoding="utf-8",
            )

            log.info(f"  <- Today note saved ({len(note_content)} chars)")
            return {"saved": True, "content": note_content}

        return {"saved": False, "content": ""}

    except Exception as e:
        log.error(f"  [ERROR] today-note: {e}")
        raise HTTPException(500, str(e))
