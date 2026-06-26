# 归砚 · 工程日志

> 安静的私密聊天空间。FastAPI + DeepSeek V4。

---

## v1.1 — 2026-06-26 手机端 + 外网访问

### ✨ 功能

- **PWA 支持** — manifest.json + Service Worker，手机可添加到桌面，像原生 App
- **发送按钮** — 输入框右侧 ↑ 发送，iOS 换行与发送互不干扰
- **外网访问** — 通过 Tailscale 零配置组网，出门在外也能连

### 📱 移动端优化

- 新增 600px / 380px 断点，紧凑布局适配手机小屏
- 修复 iOS 输入自动放大（input font-size ≥ 16px）
- 侧边栏在手机上全屏展开
- 添加 apple-touch-icon 和 favicon 链接
- 页面添加 Cache-Control: no-cache，防止缓存旧版本

### 🛠 工程化

- 配置读取改为环境变量优先，本地 Claude config 后备
- 数据目录支持 `YANCHI_DATA_DIR` 环境变量
- 端口支持 `PORT`（云平台默认）和 `YANCHI_PORT`
- 启动 host 支持 `YANCHI_HOST` 环境变量
- 记忆数据从 Claude 目录复制到项目 `data/`，可随代码部署
- 添加 CHANGELOG.md

### 📦 依赖

- requirements.txt 不变，零新增依赖

---

## v1.0 — 2026-06-26 初始版本

### 核心功能

- FastAPI 后端 + 暗色主题前端 SPA
- DeepSeek V4（Flash / Pro）模型驱动，Anthropic 兼容 API
- 流式输出 + 思考链折叠显示
- 对话 session 管理（多会话 + 截断策略）

### 记忆系统

- Bigram 中文二元组检索（不依赖词嵌入）
- 遗忘曲线（7 天半衰期衰减）
- HitCount 追踪 + 低频冷记忆自动归档
- 自动记忆（每 10 轮对话提取关键信息）
- 对话存档（每 5 轮自动保存为 markdown）

### 缓存策略

- 静态/动态分层，静态层带 `cache_control: ephemeral`
- 固定前缀截断（保留前 6 条保证缓存命中）
- 进程内静态 prompt 缓存

### UI

- 暖调深色主题（#1c1a17 / #1a1814），纸墨质感
- 用户右对齐 / AI 左对齐 + 头像
- 日期分隔线、右键删除、回到底部按钮
- 头像自定义上传 + 跨设备同步
- 图片上传 + 千问 VL 识别 / 缩略图预览
- 网页 URL 自动抓取
- 时间线回忆视图（笔记/记忆/历史/精选）
- 全文搜索、模型切换、今日笔记、记忆整理
- 导出对话

### 技术栈

- **后端**: Python 3.12 + FastAPI + Uvicorn + httpx
- **前端**: 原生 JS + CSS（无框架）
- **模型**: DeepSeek V4（Anthropic 兼容 API）
- **图片**: 千问 VL（DashScope OpenAI 兼容 API）
- **记忆**: Bigram + JSON 索引 + 文件系统

---

### 提交历史

```
bb8b8cb fix: SW 缓存版本升级 v2 + 旧缓存清理
5d011cb fix: 添加 Cache-Control: no-cache
c0f60dd feat: 添加发送按钮 + iPhone 图标链接
d302586 feat: 优化移动端适配
f3f112b fix: start-ps.bat 添加 YANCHI_HOST=0.0.0.0
b7ea91e feat: 添加 PWA 支持
9cb40fd feat: 适配云部署
c25a286 chore: 添加 gitignore
3e7462d 归砚 v1.0（初始版本）
```
