# 砚迟 Session · 2026-06-29

## 完成

### 记忆提取分离模型
- `config.py` 新增 `BACKGROUND_MODEL = "deepseek-v4-flash"`，记忆提取/今日笔记等后台任务固定走此模型
- `chat.py` `call_llm()` 新增可选 `model` 参数，后台调用传 `BACKGROUND_MODEL`
- `memory.py` / `_note_fn.py` 同步

### 提取 prompt 人称修正
- 记忆提取 prompt 加「涉及砚迟时人称统一用「她」，不用「他」」

### RP 文件命名规范化
- 从 `rp-YYYY-MM-DD.md` → `YYYY-MM-DD-rp.md`（日期在前，按字母序与笔记正确穿插）
- `chat.py` 笔记列表/详情 API 适配新命名
- `import_memories.py` 文件路径同步

### 流式响应孤儿消息修复
- **根因**：`stream_and_save` 中 token 保存与 session 回滚共用 `if/elif`，流式出错但已收到 usage 数据时回滚被跳过
- **修复**：拆成三段独立逻辑：正常保存 / token 记录 / 错误回滚
- **验证**：清理 8 个 session 中的孤儿消息（最多一个从 35→20 条）

### 低风险记忆自动审核
- `AUTO_APPROVE_CATEGORIES = {"喜好与习惯", "承诺与约定", "日常"}`，提取时直接写索引
- `关系里程碑` / `亲密` / `其他` 继续走待审核

### 记忆 ID 重复修复
- **根因**：`MEMORY_SEQ` 重启后重置为 0，新提取可能与历史 ID 冲突
- **修复**：`_init_seq()` 启动时从现有索引恢复 SEQ
- **清理**：修复 3 个已有重复 ID

## 待办
- 流式偶尔卡住（回滚逻辑已修，继续观察）
- NEXT_PUBLIC_API_URL 环境中 weather_location 编码问题
