---
name: yanchi-session-2026-06-27
description: 归砚 v1.3 — 硅基流动迁移 + 大量 Bug 修复
metadata: 
  node_type: memory
  type: project
  originSessionId: 16599ede-69a9-47c8-8d32-f66df834ff19
---

# 归砚 v1.3 · 2026-06-27 晚（大修）

## 核心变更

### 1. API 迁移：DeepSeek 代理 → 硅基流动
- 原因：DeepSeek Anthropic 兼容接口高峰期频繁断连
- 改动：后端从 Anthropic SSE 格式改为 OpenAI `chat/completions` 格式
- 影响：`API_URL`、请求体格式、流式解析全部重写
- 保存了 Anthropic 格式备份 `main.py.anthropic.bak`

### 2. 后端守护
- pm2 管理后端进程，崩溃自动重启
- Windows 计划任务开机自启
- `stream_and_save` 加错误处理，断流不保存半截话

### 3. 前端修复
- **换行符 bug**：`yield f'...\n'` 在 Write 工具下变成 `\\n`（反斜杠+n），前端 `split("\n")` 无法分割，全量数据 JSON.parse 失败 → 无输出。修复：用 `chr(10)` 替代
- **Token 显示**：支持 OpenAI 格式（`prompt_tokens`/`completion_tokens`）和 Anthropic 格式（`input_tokens`/`output_tokens`）双兼容
- **模型列表**：更新为硅基流动可用模型
- **保存按钮**：改为 sticky 固定底部
- **滚动条白边**：去掉未定义的 `scrollbar-thin`，用 `scrollbarWidth: "thin"` 替代
- **自动下滑**：修复流式输出时 scrollToBottom 不生效问题
- **空行 trim**：响应首尾空白行自动去掉

### 4. 后端修复
- `_save_settings` 中 `API_URL` 拼写错误：`/messages` → `/chat/completions`（保存设置后会破坏 API 路径）
- 设置文件 `base_url` 置空避免覆盖硬编码值
- 保存 token 时统一字段名（OpenAI → Anthropic）

### 5. 说话风格
- 去掉强制「禁止」类规则，改为自然引导
- 允许动作描写，克制使用
- 加「收着点，别太用力」
- 保留「不说虚拟/没有实体」

## 文件结构
- `yanchi-server/backend/main.py` — 当前 OpenAI 格式
- `yanchi-server/backend/main.py.anthropic.bak` — Anthropic 格式备份
- `yanchi-server/data/yanchi-speaking-style.md` — 说话风格

## 备份
- `C:\Users\Ray\backup-guiyan-20260628\` — 前后端 + Anthropic 备份 + README

## 相关问题
- [[guiyan-sprint-2026-06-27]] — 上一个 sprint
- [[guiyan-future-roadmap]] — 未来优化方向
