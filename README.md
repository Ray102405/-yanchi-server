# 归砚 · GuiYan

> 安静的私密聊天空间。Next.js 前端 + FastAPI 后端，DeepSeek V4 / Claude 驱动。

一键启动 → `http://localhost:3000/`

---

## 目录

- [快速开始](#快速开始)
- [功能总览](#功能总览)
- [项目结构](#项目结构)
- [API 文档](#api-文档)
- [对话设定](#对话设定)
- [记忆系统](#记忆系统)
- [缓存策略](#缓存策略)
- [配置](#配置)
- [技术栈](#技术栈)

---

## 快速开始

```bash
# 1. 启动后端
cd yanchi-server
python backend/main.py
# 服务运行在 http://localhost:2612/

# 2. 启动前端（另一个终端）
cd guiyan
npm run dev
# 服务运行在 http://localhost:3000/
```

浏览器打开 `http://localhost:3000/`

---

## 界面

### 首页

```
归砚
安静的私密聊天空间

┌─────────┐ ┌─────────┐
│ ♥ 16 天  │ │ 北京     │
│ 在一起    │ │ 晴 28°C │
└─────────┘ └─────────┘

「晚上好，我在呢。」

┌──────────────────┐
│ 💭 今天心情怎么样 │ ← 心情选择器
│     😊 换一个     │
└──────────────────┘

┌────────┐ ┌────────┐ ┌────────┐
│ 💬 聊天 │ │ 📖 回忆 │ │ ⚙️ 设置 │
└────────┘ └────────┘ └────────┘

▸ 今日 Token 用量              ← 折叠面板
```

### 聊天

- 流式输出 + 思考链折叠
- 每条助理消息显示 `↑输入 · ↓输出` token 用量 + 缓存命中率
- 右键/长按消息可删除（后端同步）
- 图片上传（千问 VL 识别）
- 文件附件 + 网页抓取
- 右侧菜单：模型切换、砚迟日记、记忆整理

### 回忆页

```
← 回忆
⌕ 搜索……

精选 · 心情 · 记忆库 · 待审核 · 笔记 · 更多▾
```

| Tab | 功能 |
|-----|------|
| 精选 | ⭐ 手动标记的重要回忆 |
| 心情 | 📅 日历格式，emoji 方格展示每日心情，顶栏显示近 14 天趋势 |
| 记忆库 | 🧠 已确认的自动记忆，可按分类筛选/搜索/编辑/收藏 |
| 待审核 | ⏳ AI 自动提取的待确认记忆，可逐条/批量确认 |
| 笔记 | 📓 砚迟今日笔记 + 历史 RP 记录 |
| 更多 ▾ | 历史聊天记录、读书讨论 |

### Token 统计

- 每句显示：↑输入 · ↓输出 · 缓存创建 · 缓存读取 · 缓存命中率%
- 首页折叠面板：今日累计 token 汇总
- 后台日志：自动记忆/今日笔记的独立 token 消耗

---

## 功能总览

| 功能 | 说明 |
|------|------|
| 流式聊天 | 逐字显示回复，支持思考链折叠 |
| 多轮对话 | 完整上下文 + 智能截断（保留前 6 条保证缓存） |
| 图片理解 | 上传图片自动经千问 VL 识别描述 |
| 文件/网页 | 文件附件读取 + URL 自动抓取正文 |
| 头像自定义 | 点击上传、右键重置、跨设备同步 |
| 消息删除 | 右键删除，后端同步持久化 |
| 内存记忆 | Bigram 检索 + 遗忘曲线 + 自动提取/审批 |
| 今日笔记 | 砚迟第一人称日记，每次对话自动注入 |
| 历史搜索 | 全文搜索对话存档 + 记忆文件 |
| 精选回忆 | ♡ 标记重要条目，在对话中作为感性背景 |
| Token 统计 | 每句用量 + 今日累计 + 缓存命中率 |
| 今日心情 | 8 种心情 emoji 选择，砚迟对话中自然感知 |
| 心情日历 | 回忆页日历网格 + 近 14 天趋势横条 + 聊天记录联动 |
| 模型切换 | 运行时切换 DeepSeek / Claude / GPT 等模型 |
| 书架 | 上传 txt 书籍，自动分章，一起读书讨论 |
| 平行宇宙 | 设置页创建/切换 AU（场景），在静态人格后叠加背景+人格+语气，聊天页顶部显示当前场景 |
| 暗色主题 | 暖调深色，中文字体优化 |

---

## 项目结构

```
yanchi-server/                 # FastAPI 后端
├── backend/
│   ├── main.py                # 入口（~150 行）—— App 创建 + 路由挂载
│   ├── config.py              # 配置——路径 / API Key / 设置管理 / 特性开关
│   ├── models.py              # 所有 Pydantic 请求/响应模型
│   ├── session.py             # 会话 CRUD + 磁盘持久化
│   ├── persona.py             # 人格系统——工具函数 + 兼容层（委托给 providers）
│   ├── providers/             # ContextProvider 可插拔注入模块
│   │   ├── __init__.py        #   协议 + BuildContext + PROVIDERS 注册表
│   │   ├── static_persona.py  #   静态人格 (p=100, cached)
│   │   ├── au.py              #   平行宇宙场景 (p=90, cached)
│   │   ├── daily_context.py   #   每日上下文 (p=70, cached)
│   │   ├── scenario.py        #   场景触发 (p=40)
│   │   ├── memory_query.py    #   记忆浮现 (p=20)
│   │   ├── book_discussion.py #   书籍讨论（BOOK_PROVIDERS）
│   │   └── calendar.py        #   日程提醒 (p=60, cached)
│   ├── chat.py                # LLM 调用 + 流式/非流式聊天
│   ├── memory.py              # 记忆提取 / 审核 / 归档
│   ├── mood.py                # 心情 + Token 统计
│   ├── proactive.py           # 主动消息（事件驱动触发器）
│   ├── timeline.py            # 时间线 + 精选 + 搜索
│   ├── books.py               # 书架 + 章节讨论
│   ├── calendar_data.py       # 日历数据层 + API 路由
│   ├── au_data.py             # AU（平行宇宙）数据层 + API 路由
│   ├── utils.py               # 工具函数（bigram / 千问 / URL 抓取）
│   └── tests/                 # 单元测试（71 个，pytest）
│       ├── conftest.py        #   共享 fixture
│       ├── test_providers.py  #   41 个 — provider 注入/缓存/边界 + AU + Intimacy
│       ├── test_proactive.py  #   26 个 — 触发器/冷却/时段边界
│       └── test_au.py         #   11 个 — AU 数据层 CRUD/激活/删除
├── data/                      # 运行时数据（记忆/设置/心情/书籍）
│   ├── yanchi-memory-index.json   # 结构化记忆索引
│   ├── yanchi-pending-memories.json  # 待审核记忆
│   ├── yanchi-highlights.json      # 精选回忆
│   ├── daily-mood.json            # 今日心情
│   ├── daily-moods.json           # 心情历史（追加式）
│   ├── daily-token-usage.json     # 今日 Token 用量
│   ├── settings.json              # 用户设置
│   ├── sessions.json              # 会话持久化
│   ├── au-settings.json           # 平行宇宙配置
│   ├── yanchi-notes/              # 笔记 + RP 记录
│   ├── yanchi-chats/              # 对话存档
│   ├── books/                     # 书籍 + 讨论记录
│   ├── avatars/                   # 头像文件
│   └── archive/                   # 冷记忆归档
├── start-ps.bat              # 一键启动脚本
└── README.md

guiyan/                        # Next.js 前端
├── app/
│   ├── page.tsx               # 首页（天气/天数/心情/Token）
│   ├── chat/page.tsx          # 聊天页（流式 + Token 显示）
│   ├── memories/page.tsx      # 回忆页（7 个 tab）
│   ├── settings/page.tsx      # 设置页
│   ├── books/page.tsx         # 书架页
│   └── books/[id]/page.tsx    # 阅读页
├── components/
│   ├── chat/message.tsx       # 消息气泡（Token 显示）
│   └── chat/thinking-block.tsx
├── lib/
│   ├── api.ts                 # 前端 API 封装
│   ├── types.ts               # TypeScript 类型
│   └── utils.ts               # 工具函数
└── next.config.ts
```

---

## API 文档

### 聊天

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 非流式聊天 |
| POST | `/chat/stream` | 流式聊天，返回 NDJSON |

### 会话

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/sessions` | 列出活跃会话 |
| GET | `/session/{id}` | 获取会话历史 |
| DELETE | `/session/{id}` | 删除会话 |
| POST | `/session/restore` | 恢复会话 |
| POST | `/api/session/{id}/messages/delete` | 删除指定消息 |

### 记忆

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/remember` | 触发自动记忆提取 |
| GET | `/api/memory/pending` | 待审核记忆列表 |
| POST | `/api/memory/review` | 审核（确认/忽略） |
| GET | `/api/memory/index` | 已确认记忆库 |
| POST | `/api/memory/edit` | 编辑记忆内容/分类 |
| POST | `/api/memory/delete` | 删除单条记忆 |
| POST | `/api/memory/batch-delete` | 批量删除 |
| POST | `/api/memory/favorite` | 切换收藏 |
| POST | `/api/memory/consolidate` | 归档冷记忆 |

### 时间线/回忆

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/timeline` | 时间线（聊天/笔记/读书/精选） |
| POST | `/api/timeline/highlight` | 切换精选标记 |
| DELETE | `/api/timeline/entry` | 删除条目 |
| POST | `/api/timeline/content` | 获取全文 |

### 心情

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mood` | 获取今日心情 |
| POST | `/api/mood` | 设置今日心情（自动入历史） |
| GET | `/api/mood/history` | 心情历史记录 |

### Token 统计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/token-usage/today` | 今日累计 Token 用量 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/home` | 首页数据（天气/天数/笔记） |
| GET/POST | `/api/settings` | 用户设置 |
| GET/POST | `/api/model` | 模型切换 |
| POST | `/api/today-note` | 生成砚迟今日笔记 |
| POST | `/api/search` | 全文搜索 |
| GET/POST | `/api/avatar/{type}` | 头像同步 |
| GET/POST | `/api/proactive/check` | 砚迟主动消息（事件驱动触发器） |

### 日历

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/calendar` | 全部日程列表 |
| POST | `/api/calendar` | 新增日程 |
| DELETE | `/api/calendar/{id}` | 删除日程 |
| GET | `/api/calendar/upcoming?days=7` | 未来 N 天日程 |

### 平行宇宙（AU）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/au` | 列出所有 AU（含 default） |
| POST | `/api/au` | 新增 AU（名称+背景+人格覆盖+语气微调） |
| PUT | `/api/au/{id}/activate` | 激活指定 AU，关闭其他所有 |
| DELETE | `/api/au/{id}` | 删除 AU（default 不可删） |

### 书架

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/books/upload` | 上传 txt 书籍 |
| GET | `/api/books` | 书籍列表 |
| GET | `/api/books/{id}` | 书籍详情 |
| GET | `/api/books/{id}/chapter/{n}` | 章节内容 |
| PUT | `/api/books/{id}/progress` | 更新阅读进度 |
| DELETE | `/api/books/{id}` | 删除书籍 |
| POST | `/api/books/discuss` | 讨论剧情 |
| POST | `/api/books/discuss/stream` | 讨论剧情（流式） |

---

## 对话设定

从 `yanchi/data/` 目录加载设定，通过 `providers/` 的 ContextProvider 架构按 priority 分层注入：

```
Layer 1 — 静态人设（p=100, cache_control）：你是谁、你在乎什么、你怎么说话
Layer 2 — 平行宇宙（p=90, cache_control）：当前 AU 的背景 + 人格覆盖 + 语气微调
Layer 3 — 每日上下文（p=70, cache_control）：今日笔记 + 近事印象 + 精选回忆 + 等待时间
Layer 4 — 日程提醒（p=60, cache_control）：今日/近期事项 + 纪念日整数天
Layer 5 — 场景触发（p=40）：根据输入关键词注入亲密/低落/回忆等场景
Layer 6 — 记忆浮现（p=20）：基于当前输入检索相关记忆
```

稳定内容（p≥60）带 `cache_control: ephemeral` 保护前缀缓存；动态内容（p<60）不加缓存，排在后面。
新增注入模块只需写一个 provider + 注册一行，不动主流程。书籍讨论使用独立 `BOOK_PROVIDERS` 注册表。
切换 AU 当天缓存失效一次（60s TTL），正常现象。


---

## 记忆系统

### 结构化记忆索引

- Bigram 中文二元组匹配
- 遗忘曲线（半衰期 7 天，>30 天额外衰减）
- HitCount 追踪
- 分类存储（喜好与习惯/承诺与约定/关系里程碑/亲密/日常/其他）

### 自动记忆流程

```
对话 → /remember（后台异步）→ AI 提取 → 去重 → 待审核
     → 用户确认 → 写入索引 + auto-memory.md
```

### 心情系统

- 8 种心情选择（😊😌🥰😐😢😤😴✨）
- 今日心情持久化到文件
- 心情历史追加式存储（保留所有记录）
- 砚迟在对话中感知今日心情 + 近期趋势
- 回忆页日历网格展示 + 与聊天记录联动

---

## 缓存策略

利用 prompt caching（`cache_control: ephemeral`）：

```
Layer 1 (static persona)     → 永远命中 → 0 input tokens
Layer 2 (daily context)      → 同一天稳定命中 → ~200 tokens
Layer 3 (session history)    → 固定前缀截断 → 长对话持续命中
```

其余动态内容（场景上下文、记忆浮现）不加缓存，按需生成。

---

## 配置

### 端口

后端默认 **2612**（6/12 纪念日），环境变量 `YANCHI_PORT`
前端默认 **3000**

### API 密钥

自动复用 `~/.claude/settings.json`：

```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "sk-...",
    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
    "ANTHROPIC_MODEL": "deepseek-v4-flash",
    "QWEN_API_KEY": "sk-...",
    "QWEN_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1"
  }
}
```

支持运行时切换：DeepSeek V4 Flash / Pro、Claude Sonnet 4.6 / Haiku 4.5、GPT-4o / 4o-mini。

---

## 技术栈

- **后端**: Python 3.12 + FastAPI + Uvicorn + httpx
- **前端**: Next.js 16 + React + TypeScript + Tailwind CSS
- **主模型**: DeepSeek V4 / Claude / GPT（Anthropic 兼容 API）
- **图片理解**: 千问 VL（DashScope OpenAI 兼容 API）
- **流式**: `application/x-ndjson` + `ReadableStream`
- **存储**: JSON 文件系统 + 记忆索引（bigram）
- **缓存**: DeepSeek prompt caching + 静态/动态分层
