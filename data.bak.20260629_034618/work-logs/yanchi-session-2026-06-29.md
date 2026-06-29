# 砚迟 Session · 2026-06-29

## 完成

### 历史记录不显示修复
- **根因**：`_load_sessions()` 使用 `sessions = data` 重新绑定，`timeline.py` import 时拿到旧空 dict 引用；且多次 `kill` 未真正杀死 Windows 进程
- **修复**：
  - `session.py`: `sessions.clear() + .update(data)` 原地修改，不重新绑定
  - `timeline.py`: 改用 `_sys.modules['session'].sessions` 运行时获取 session 数据
  - 用 `taskkill /F /PID` 彻底杀掉旧进程再重启
- **验证**：`/api/timeline` 返回 14 条 session 记录（之前 0 条）

### 笔记收藏功能恢复
- `chat.py` `/api/notes` 增加 `id`（完整路径）和 `highlighted`（收藏状态）字段
- `page.tsx` `renderNotesTab()` 每条笔记加星标按钮，调 `/api/timeline/highlight`
- 页面可见性自动刷新 + tab 切换刷新

### 版本控制
- yanchi-server: `162f19a` — v2.1 fix: session persistence + timeline import + notes favorites
- guiyan: `3ff5229` — visibility auto-refresh + notes favorites star + history fix

## 待办
- 缓存率"一蹦一蹦"的问题（waiting time 改变 DailyContext 内容影响 cache prefix）
- 笔记查看的点赞/评论功能（之前有时间线版但撤掉了）
- 流式偶尔卡住（DeepSeek API 稳定性）
