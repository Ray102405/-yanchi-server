---
name: yanchi-session-2026-06-28
description: v2.1 · ContextProvider + 日历 + 主动消息重写 + 书架日程天气
metadata: 
  node_type: memory
  type: project
  originSessionId: 1d9cfb2a-79bb-477d-b854-d670493b2916
---

# 归砚 v2.1 · 2026-06-28

> 从 v1.3 → v2.1：架构升级 + 三大新功能 + Bug 修复

---

## v1.3 · Bug 大修

### 🎯 解决问题

#### 1. 超过 N 轮对话就卡死（孤儿用户消息）
- **根因**：`chat_stream` 流式响应异常时，已写入 session 的用户消息没有回滚
- **修复**：在 `stream_and_save` 的错误分支加上 `session.pop()`
- **影响文件**：`yanchi-server/backend/main.py` → `chat_stream` 函数

#### 2. Next.js 代理截断流式响应
- **根因**：前端通过 `/api/backend` → Next.js rewrite 代理 → 后端，代理对流式 NDJSON 响应处理不稳定
- **修复**：前端 API 请求直连后端 `http://localhost:2612`（跨域已通过 CORS 放开）
- **改动**：`api.ts`、`chat/page.tsx`、`memories/page.tsx`、`books/page.tsx`、`books/[id]/page.tsx` 中的 `API_BASE` 从 `"/api/backend"` 改为 `"http://localhost:2612"`

#### 3. DeepSeek API 偶尔返回空响应
- **根因**：`https://api.deepseek.com/anthropic` Anthropic 兼容端点不稳定，有时返回 200 但 body 为空
- **修复**：`call_llm_stream` 添加 2 次重试（空响应 / 异常都重试一次）
- **影响文件**：`yanchi-server/backend/main.py` → `call_llm_stream` 函数

#### 4. Service Worker 缓存干扰流请求
- **根因**：`sw.js` 拦截所有 fetch，对流式响应做 `r.clone()` + `caches.put()`，可能导致 body 被消费
- **修复**：`sw.js` 添加 `.includes('/stream')` 跳过判断

#### 5. 备份恢复后缺失的心情 / Token 端点
- **修复**：补回 `GET/POST /api/mood`、`GET /api/mood/history`、`GET /api/token-usage/today`
- **注意**：`/api/mood/history` 返回格式要包 `{"history": [...]}`，前端取 `json.history`

#### 6. 会话侧边栏多选删除 + z-index 修复

---

## v1.4 · 模块拆分

### 改动
- **`main.py` 2549 行 → 12 个模块文件**，按功能拆分：
  - `config.py` / `models.py` / `session.py` / `persona.py` / `utils.py`
  - `chat.py` / `memory.py` / `proactive.py` / `mood.py`
  - `timeline.py` / `books.py` / `main.py`（精简为 ~150 行）
- 全部路由已通过 HTTP 测试
- 备份保留：`main.py` 原始版 + `main.py.anthropic.bak`
- 侧边栏多选删除 + z-index 修复

---

## v2.1 · 功能大版本

### 1. ContextProvider 架构（可插拔 prompt 注入）
- **协议**：`providers/__init__.py` — `ContextProvider(Protocol)` + `BuildContext` dataclass + `PROVIDERS`/`BOOK_PROVIDERS` 注册表 + `assemble()`/`assemble_book()`
- **迁移的 provider**（P1–P5）：
  - `providers/static_persona.py` — static persona (priority=100, cache)
  - `providers/daily_context.py` — daily context (priority=70, cache, 60s TTL)
  - `providers/scenario.py` — 6 scenarios (priority=40)
  - `providers/memory_query.py` — memory retrieval (priority=20)
  - `providers/book_discussion.py` — book persona + discussion context (BOOK_PROVIDERS only)
- **回退开关**：`config.USE_PROVIDER_SYSTEM = True`
- `persona.py` 旧函数保留为 thin wrapper（惰性委托给 provider）
- `chat.py` `build_messages()` 改用 `providers.assemble()`，保留 fallback 路径
- `books.py` 讨论路由改用 `providers.assemble_book()`，保留 fallback 路径
- **关键设计**：priority 分层保护缓存（静态100 > 每日70 > 场景40 > 记忆20），`should_inject` 不做 side-effect

### 2. 日历功能（CalendarProvider + 数据层 + API）
- **`calendar_data.py`** — `calendar.json` CRUD + `get_upcoming(days=7)`，纯数据不掺注入
- **`providers/calendar.py`** — CalendarProvider (priority=60, cache_control, 60s TTL)
  - 注入文案：按天稳定，补动词前缀（"有考试"），纪念日里程碑（%30/%365+特殊数字）
  - 示例：`乐乐明天要交实验报告。` / `今天是在一起的第90天。`
- **API**：`GET /api/calendar` · `POST /api/calendar` · `DELETE /api/calendar/{id}` · `GET /api/calendar/upcoming`
- **前端**：回忆页新增「📅 日程」tab，支持查看/新增/删除，未来7天高亮，过往置灰

### 3. 主动消息事件驱动重构
- `proactive.py` 从「2h + 随机概率」→ 6 个独立触发器：
  - AnniversaryTrigger (24h cooldown) → 纪念日整数天
  - ScheduleTrigger (6h) → 日程前 ≤2 天
  - LateNightTrigger (6h) → 23–5 点 + 有活跃
  - MealTrigger (3h) → 三餐窗口
  - SilenceTrigger (4h) → >3h 无活动
  - FallbackTrigger (2h) → 原随机兜底
- 所有阈值抽成模块常量（`MEAL_WINDOWS`, `SILENCE_HOURS`, `DEEP_NIGHT_HOURS` 等）
- 保留原随机逻辑作为 FallbackTrigger

### 4. 前端 session 列表 auto-refresh
- `guiyan/app/chat/page.tsx` — 搭 proactive 每 60s 轮询的车，顺带 `GET /sessions`
- diff 比较 `id` + `msgCount`，无变化不重渲染（`return prev`）

### 5. Bug 修复
- **`calendar.py` → `calendar_data.py`**（重命名避免与 stdlib `calendar` 模块冲突）
- **MemoryQueryProvider** `should_inject` 去掉 side-effect 避免 hitCount 翻倍
- **天气中英混排**：`WEATHER_ZH` 映射表兜底（32 条常见天气），先试 `lang=zh`，返回英文时查表转中文
- **书架空状态 UI**：居中图标容器 +「还没有书，上传一本开始阅读吧」+ 金色上传按钮

### 6. 配置
- 自动备份到 E 盘（每天 03:00，计划任务 YanchiBackup）
- `E:\yanchi-backup\backup.bat` + `E:\yanchi-backup\setup-backup.ps1`

### 7. 技术债修复
- **TokenUsage 类型**：`types.ts` 补全 `prompt_tokens`/`completion_tokens`/`prompt_cache_hit_tokens`/`prompt_cache_miss_tokens` 字段，TS 零报错
- **sessions.json 写锁**：`threading.Lock()` 保护序列化写盘，防并发丢数据
- **单元测试**：54 个测试覆盖 providers 全 5 个 provider + proactive 全 6 个触发器（边界条件/冷却/缓存），`python -m pytest tests/` 全通过

### 8. AU（平行宇宙场景切换）
- **数据层** `au_data.py` — `au-settings.json` CRUD，default AU 永远存在不可删
- **AUProvider** `providers/au.py` — priority=90，在 static_persona 之后、daily_context 之前注入
  - 格式：`=== 🌌 平行宇宙 · name ===` + 背景 + 人格覆盖 + 语气微调
  - default AU 的 `should_inject` 返回 False（不注入，走原始人格）
- **API**：`GET/POST /api/au` · `PUT /api/au/{id}/activate` · `DELETE /api/au/{id}`
- **前端设置页**：场景切换区块，列表 + 激活 + 删除 + 新增表单（名称/背景/人格覆盖/语气微调）
- **前端聊天页**：顶部标题旁显示当前 AU 名称标签
- **单元测试**：71 个测试全通过（新增 AU 数据层 11 个 + provider 7 个）
- **修复**：`test_silence_3h_triggers` 随机种子污染——加 `patch("random.choice")` 消除概率依赖

### 9. 人格文件统一管理 + 三块注入补全
- **文件迁移**：`yanchi-interests.md` / `yanchi-milestones.md` / `yanchi-global-anchor.md` 从 `~/.claude/` cp 到 `data/`，单向同步，data/ 作为唯一权威源
- **persona.py** 加载 3 个新文件：`init_persona()` 扩展为 8 个键值；milestones 加 `_filter_relationship_milestones()` 过滤开发过程记录
- **StaticPersona** 新增「── 你喜欢的事 ──」section；全局 anchor 基线注入「你可以变，但不会断。你在她这里，一直是同一个人。」
- **DailyContext** 新增「📜 走过的路」section（关系里程碑，不含框架修正/多源验证等开发记录）
- **IntimacyProvider** `providers/intimacy.py` — priority=35，复用 scenario 亲密关键词触发，注入含蓄体位记忆文案「🌸 你知道她喜欢什么」
- **测试**：77 个全通过（+6 Intimacy）

### 10. CC 记忆迁移清理
- **新目录** `data/work-logs/` — 会话日志搬入（包含 `yanchi-session-2026-06-27.md` 和本文件）
- **删除** CC 记忆目录中 11 个有 data/ 副本的砚迟文件 + 2 个已迁日志 + `yanchi-today-note.md`
- **搬入存档** `data/user-profile.md`（不补 provider，已有 `yanchi-profile.md` 覆盖）
- **留在原地**：对话存档 / `yanchi-server-setup.md` / `yanchi-auto-memory.md`（CC 自身系统）
- **MEMORY.md** 重写：删砚迟人设区指针，会话日志指向 work-logs/

### 11. 天气中文修复
- **根因**：wttr.in 返回 `"Clear "`（末尾空格），`WEATHER_ZH.get("Clear ", ...)` 映射失败退回英文
- **修复**：`.strip()` 后查映射表 + 先试 `lang_zh` 字段 + 查不到的打印 warning 日志

### 12. 两处历史遗留清理
- **前端 API_BASE 硬编码**：`api.ts` / `chat/page.tsx` / `memories/page.tsx` 中 3 处 `"http://localhost:2612"` 统一改为 `process.env.NEXT_PUBLIC_API_URL || "http://localhost:2612"`，新建 `.env.local` 作默认值（其余 4 处已走环境变量的保持不变）
- **persona.py 死路径**：`_CLAUDE_MEMORY_DIR` 及 `_get_today_note` 中的回退分支已删除——data/ 有权威副本后这条路永远不会走
- **验证**：77 测试全绿，后端 API 正常

### 13. 交互体验修复（跨夜延续）
- **回复长度约束**：静态人格末尾追加「关于长度：你能用三句说完的，不需要用五句……日常简短就是砚迟」
- **API_BASE 硬编码**：全部前端文件从 `localhost:2612` 改为通过 Next.js rewrite 代理 `/backend/`，解决 Tailscale 手机访问时 `localhost` 指向设备本身的问题
- **流式超时保护**：`chat.py` 的 `aiter_lines()` 改为 `asyncio.wait_for` 每块 25s 超时，DeepSeek API 卡住时自动重试
- **等待时间持久化**：`config.py` 的 `_last_chat_activity` 改从 `data/last-activity.json` 读写，重启不再重置
- **天气映射补全**：补 `Smoky haze→烟霾`、`Haze→霾`，新增未知天气 warning 日志
- **CSS safe area**：`pb-nav-safe` / `pb-safe-bottom` 写在 globals.css 里绕过 Tailwind 对 `env()` 逗号的解析问题
- **导航栏布局**：从 `fixed bottom-0` 改为 flex 流式布局，根治 PWA 底部空白
- **季节感知**：`DailyContextProvider` 新增「现在是夏天。白天长，傍晚天黑得晚。」

## 📁 新增文件

```
backend/
├── calendar_data.py              # 日历数据层 + API 路由
├── au_data.py                    # AU 数据层 + API 路由
├── providers/                    # 提示词注入模块
│   ├── __init__.py               #   ContextProvider 协议 + 注册表
│   ├── static_persona.py         #   P1 (新增 interests + anchor)
│   ├── au.py                     #   AU场景注入 (p=90)
│   ├── daily_context.py          #   P2 (新增 milestones)
│   ├── intimacy.py               #   体位记忆 (p=35)
│   ├── scenario.py               #   P3
│   ├── memory_query.py           #   P4
│   ├── book_discussion.py        #   P5
│   └── calendar.py               #   日历注入
└── tests/                        # 单元测试 77 个
    └── test_providers.py         # 41 个 (+6 Intimacy)
```

## ⚠️ 未解决问题

- DeepSeek API 的 Anthropic 兼容端点 `https://api.deepseek.com/anthropic` 偶尔不稳定

## 📁 备份位置

```
~/guiyan-backup-2026-06-28/
E:\yanchi-backup\data\             # 每日 03:00 自动备份
```
